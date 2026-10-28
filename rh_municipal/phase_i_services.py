"""Tenant-, contract-, permission- and scope-gated governance workflows."""
import hashlib
from pathlib import PurePosixPath

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from platform_core.context import current_organization
from . import phase_i_models as m
from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, require_municipal_permission, scoped_queryset


def _require(actor, capability, record=None):
    org = current_organization()
    if org is None or not public_module_available(org, m.GOVERNANCE_MODULE):
        raise PermissionDenied('Controle Interno não está contratado e ativo nesta Prefeitura.')
    require_municipal_permission(actor, capability, module=m.GOVERNANCE_MODULE, record=record)
    return org


def _scope_fields(row):
    return {name: getattr(row, name, None) for name in ('secretaria', 'departamento', 'setor', 'unidade')}


def _inherit_scope(data, related):
    if related is None:
        return data
    for name, value in _scope_fields(related).items():
        if data.get(name) is None:
            data[name] = getattr(related, name, None)
    return data


def _audit(actor, org, action, row, before=None, after=None):
    event = m.EventoControleInterno(
        organization=org, acao=action, entidade=row._meta.label_lower,
        entidade_id=str(row.pk), antes=before or {}, depois=after or {},
        usuario=actor, **_scope_fields(row),
    )
    event._service_write = True
    event.save()
    return event


@transaction.atomic
def create_risk(actor, *, data):
    org = _require(actor, 'governance.risks.manage')
    row = m.RiscoControleInterno(organization=org, criado_por=actor, **data)
    row.full_clean()
    row.save()
    _audit(actor, org, 'RISCO_CRIADO', row, after={'codigo': row.codigo, 'status': row.status})
    return row


@transaction.atomic
def create_control(actor, *, data):
    org = _require(actor, 'governance.controls.manage')
    data = _inherit_scope(dict(data), data.get('risco'))
    row = m.ControleInternoMunicipal(organization=org, criado_por=actor, **data)
    row.full_clean()
    row.save()
    _audit(actor, org, 'CONTROLE_CRIADO', row, after={'codigo': row.codigo, 'ativo': row.ativo})
    return row


@transaction.atomic
def create_finding(actor, *, data):
    org = _require(actor, 'governance.findings.manage')
    data = _inherit_scope(dict(data), data.get('risco') or data.get('controle'))
    row = m.AchadoControleInterno(organization=org, registrado_por=actor, **data)
    row.full_clean()
    row.save()
    _audit(actor, org, 'ACHADO_REGISTRADO', row, after={'codigo': row.codigo, 'status': row.status})
    return row


@transaction.atomic
def create_recommendation(actor, *, finding_id, text):
    org = _require(actor, 'governance.findings.manage')
    finding = scoped_queryset(actor, m.AchadoControleInterno.objects.filter(organization=org)).filter(pk=finding_id).first()
    if finding is None or not has_municipal_permission(actor, 'governance.findings.manage', module=m.GOVERNANCE_MODULE, record=finding):
        raise ValidationError('Achado não encontrado no escopo autorizado.')
    row = m.RecomendacaoControleInterno(organization=org, achado=finding, texto=text.strip(), registrada_por=actor,
                                        **_scope_fields(finding))
    row.full_clean()
    row.save()
    before = {'status': finding.status}
    finding.status = m.AchadoControleInterno.Status.COM_RECOMENDACAO
    finding.save(update_fields=['status', 'atualizado_em'])
    _audit(actor, org, 'RECOMENDACAO_CRIADA', row, after={'achado': finding.pk})
    _audit(actor, org, 'ACHADO_ATUALIZADO', finding, before, {'status': finding.status})
    return row


@transaction.atomic
def close_finding(actor, *, finding_id, reason):
    org = _require(actor, 'governance.findings.close')
    finding = scoped_queryset(actor, m.AchadoControleInterno.objects.select_for_update().filter(organization=org)).filter(pk=finding_id).first()
    if finding is None or not has_municipal_permission(actor, 'governance.findings.close', module=m.GOVERNANCE_MODULE, record=finding):
        raise ValidationError('Achado não encontrado no escopo autorizado.')
    if not reason.strip():
        raise ValidationError('Informe a justificativa para encerrar o achado.')
    blocking = m.PlanoAcaoInterno.objects.filter(
        organization=org, recomendacao__achado=finding,
    ).exclude(status__in=[m.PlanoAcaoInterno.Status.CONCLUIDO, m.PlanoAcaoInterno.Status.CANCELADO]).exists()
    if blocking:
        raise ValidationError('O achado possui planos de ação ainda não concluídos ou cancelados.')
    old = finding.status
    finding.status = m.AchadoControleInterno.Status.ENCERRADO
    finding.save(update_fields=['status', 'atualizado_em'])
    _audit(actor, org, 'ACHADO_ENCERRADO', finding, {'status': old}, {'status': finding.status, 'motivo': reason.strip()[:2000]})
    return finding


@transaction.atomic
def create_action_plan(actor, *, recommendation_id, data):
    org = _require(actor, 'governance.actions.manage')
    recommendation = scoped_queryset(actor, m.RecomendacaoControleInterno.objects.filter(organization=org)).filter(pk=recommendation_id).first()
    if recommendation is None or not has_municipal_permission(actor, 'governance.actions.manage', module=m.GOVERNANCE_MODULE, record=recommendation):
        raise ValidationError('Recomendação não encontrada no escopo autorizado.')
    row = m.PlanoAcaoInterno(organization=org, recomendacao=recommendation, criado_por=actor,
                            **_scope_fields(recommendation), **data)
    row.full_clean()
    row.save()
    finding = recommendation.achado
    old = finding.status
    finding.status = m.AchadoControleInterno.Status.EM_ACAO
    finding.save(update_fields=['status', 'atualizado_em'])
    _audit(actor, org, 'PLANO_ACAO_CRIADO', row, after={'prazo': str(row.prazo), 'status': row.status})
    _audit(actor, org, 'ACHADO_ATUALIZADO', finding, {'status': old}, {'status': finding.status})
    return row


@transaction.atomic
def update_action_plan(actor, *, plan_id, status, description='', approve=False):
    org = _require(actor, 'governance.actions.approve' if approve else 'governance.actions.manage')
    plan = scoped_queryset(actor, m.PlanoAcaoInterno.objects.select_for_update().filter(organization=org)).filter(pk=plan_id).first()
    if plan is None or not has_municipal_permission(
        actor, 'governance.actions.approve' if approve else 'governance.actions.manage',
        module=m.GOVERNANCE_MODULE, record=plan,
    ):
        raise ValidationError('Plano de ação não encontrado no escopo autorizado.')
    if status not in m.PlanoAcaoInterno.Status.values:
        raise ValidationError('Situação inválida para o plano de ação.')
    if approve and status != m.PlanoAcaoInterno.Status.CONCLUIDO:
        raise ValidationError('A validação administrativa só pode concluir um plano de ação.')
    transitions = {
        m.PlanoAcaoInterno.Status.PLANEJADO: {m.PlanoAcaoInterno.Status.EM_ANDAMENTO, m.PlanoAcaoInterno.Status.CANCELADO},
        m.PlanoAcaoInterno.Status.EM_ANDAMENTO: {m.PlanoAcaoInterno.Status.AGUARDANDO_VALIDACAO, m.PlanoAcaoInterno.Status.CANCELADO},
        m.PlanoAcaoInterno.Status.AGUARDANDO_VALIDACAO: {m.PlanoAcaoInterno.Status.EM_ANDAMENTO},
    }
    if status != plan.status and status not in transitions.get(plan.status, set()) and not approve:
        raise ValidationError('Transição de situação não permitida.')
    old = plan.status
    plan.status = status
    if approve:
        plan.concluido_em = timezone.now()
    elif status != m.PlanoAcaoInterno.Status.CONCLUIDO:
        plan.concluido_em = None
    plan.save(update_fields=['status', 'concluido_em'])
    event = m.AcaoPlanoAcaoInterno(organization=org, plano=plan, status_anterior=old,
        status_novo=status, descricao=description[:2000], registrado_por=actor, **_scope_fields(plan))
    event._service_write = True
    event.save()
    _audit(actor, org, 'PLANO_ACAO_STATUS_ALTERADO', plan, {'status': old}, {'status': status, 'validado': approve})
    return plan


@transaction.atomic
def upload_evidence(actor, *, finding_id=None, plan_id=None, title, uploaded_file, content_type=''):
    org = _require(actor, 'governance.evidence.manage')
    if bool(finding_id) == bool(plan_id):
        raise ValidationError('Selecione exatamente um achado ou plano de ação para vincular a evidência.')
    if not uploaded_file or uploaded_file.size <= 0 or uploaded_file.size > 25 * 1024 * 1024:
        raise ValidationError('O arquivo precisa ter conteúdo e não pode ultrapassar 25 MB.')
    suffix = PurePosixPath(uploaded_file.name).suffix.lower()
    if suffix not in {'.pdf', '.png', '.jpg', '.jpeg', '.docx', '.xlsx', '.txt'}:
        raise ValidationError('Formato não permitido. Use PDF, imagem, DOCX, XLSX ou TXT.')
    if finding_id:
        parent = scoped_queryset(actor, m.AchadoControleInterno.objects.filter(organization=org)).filter(pk=finding_id).first()
        if not parent or not has_municipal_permission(actor, 'governance.evidence.manage', module=m.GOVERNANCE_MODULE, record=parent):
            raise ValidationError('Achado não encontrado no escopo autorizado.')
        parent_fields = {'achado': parent, 'plano': None}
    else:
        parent = scoped_queryset(actor, m.PlanoAcaoInterno.objects.filter(organization=org)).filter(pk=plan_id).first()
        if not parent or not has_municipal_permission(actor, 'governance.evidence.manage', module=m.GOVERNANCE_MODULE, record=parent):
            raise ValidationError('Plano de ação não encontrado no escopo autorizado.')
        parent_fields = {'achado': None, 'plano': parent}
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    row = m.EvidenciaControleInterno(
        organization=org, **parent_fields, **_scope_fields(parent), titulo=title.strip()[:180],
        arquivo=uploaded_file, nome_original=PurePosixPath(uploaded_file.name).name[:180],
        content_type=(content_type or '')[:100], tamanho_bytes=uploaded_file.size,
        sha256=digest.hexdigest(), enviado_por=actor,
    )
    row._service_write = True
    row.save()
    _audit(actor, org, 'EVIDENCIA_ANEXADA', row, after={'sha256': row.sha256, 'tamanho_bytes': row.tamanho_bytes})
    return row


def dashboard(actor):
    org = _require(actor, 'governance.dashboard.view')
    def count_for(model, permission, **filters):
        if not has_municipal_permission(actor, permission, module=m.GOVERNANCE_MODULE):
            return None
        return scoped_queryset(actor, model.objects.filter(organization=org, **filters)).count()
    today = timezone.localdate()
    return {
        'risks': count_for(m.RiscoControleInterno, 'governance.risks.view'),
        'controls': count_for(m.ControleInternoMunicipal, 'governance.controls.view', ativo=True),
        'findings': count_for(m.AchadoControleInterno, 'governance.findings.view'),
        'open_findings': count_for(m.AchadoControleInterno, 'governance.findings.view', status__in=[
            m.AchadoControleInterno.Status.ABERTO, m.AchadoControleInterno.Status.EM_ANALISE,
            m.AchadoControleInterno.Status.COM_RECOMENDACAO, m.AchadoControleInterno.Status.EM_ACAO,
        ]),
        'overdue_actions': count_for(m.PlanoAcaoInterno, 'governance.actions.view',
                                     prazo__lt=today, status__in=[m.PlanoAcaoInterno.Status.PLANEJADO, m.PlanoAcaoInterno.Status.EM_ANDAMENTO]),
    }


def permitted_evidence(actor, evidence_id):
    org = _require(actor, 'governance.evidence.view')
    row = scoped_queryset(actor, m.EvidenciaControleInterno.objects.filter(organization=org)).filter(pk=evidence_id).first()
    if row is None or not has_municipal_permission(actor, 'governance.evidence.view', module=m.GOVERNANCE_MODULE, record=row):
        return None
    return row


@transaction.atomic
def audit_evidence_access(actor, row):
    org = _require(actor, 'governance.evidence.view', row)
    _audit(actor, org, 'EVIDENCIA_CONSULTADA', row, after={'sha256': row.sha256})
