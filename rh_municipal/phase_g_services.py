"""Fail-closed municipal health services with sensitive-read auditing."""
import hashlib
import json
import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from platform_core.context import current_organization
from . import phase_g_models as m
from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, require_municipal_permission
from .models import AcessoMunicipal, DepartamentoMunicipal, Secretaria, Servidor, SetorMunicipal, UnidadeMunicipal


def _require(actor, capability):
    org = current_organization()
    if org is None:
        raise PermissionDenied('Selecione uma Prefeitura ativa para continuar.')
    if not public_module_available(org, m.HEALTH_MODULE):
        raise PermissionDenied('Saúde SUS não está contratada e ativa para esta Prefeitura.')
    require_municipal_permission(actor, capability, module=m.HEALTH_MODULE)
    return org


def _record_allowed(actor, capability, record):
    if record.organization_id != current_organization().pk or not has_municipal_permission(
        actor, capability, module=m.HEALTH_MODULE, record=record,
    ):
        raise PermissionDenied('O registro está fora do escopo municipal autorizado.')


def _pk(value):
    return getattr(value, 'pk', value)


def _health_hierarchy(health_unit):
    unit = health_unit.unidade
    sector = unit.setor
    department = sector.departamento
    return {
        'secretaria_id': department.secretaria_id,
        'departamento_id': department.pk,
        'setor_id': sector.pk,
        'unidade_id': unit.pk,
    }


def _payload_fingerprint(*values):
    normalized = '\x1f'.join('' if value is None else str(value) for value in values)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def _audit_replay(actor, org, model, operation_id, action, capability, payload_hash):
    row = model.objects.filter(organization=org, public_id=operation_id).first()
    if row is None:
        return None
    _record_allowed(actor, capability, row)
    audit = m.AuditoriaAcessoSaude.objects.filter(
        organization=org, entidade=row._meta.label_lower, entidade_id=row.pk,
        acao=action, detalhes__request_id=str(operation_id),
    ).first()
    if audit is None or audit.detalhes.get('payload_hash') != payload_hash:
        raise ValidationError('Este identificador de operação já foi usado com outros dados.')
    return row


def _audit(actor, org, action, entity, entity_id=None, patient_id=None, reason='', details=None):
    return m.AuditoriaAcessoSaude.objects.create(
        organization=org, usuario=actor, acao=action, entidade=entity,
        entidade_id=entity_id, paciente_id=patient_id,
        justificativa=(reason or '')[:300], detalhes=details or {},
    )


def _fernet():
    key = getattr(settings, 'MUNICIPAL_HEALTH_ENCRYPTION_KEY', '')
    if not key:
        raise ValidationError('Registro clínico indisponível: chave de cifragem da Saúde não está provisionada.')
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (TypeError, ValueError) as exc:
        raise ValidationError('Registro clínico indisponível: configuração da chave de cifragem é inválida.') from exc


@transaction.atomic
def create_patient(actor, *, data):
    org = _require(actor, 'saude.patients.manage')
    row = m.CidadaoSaudeMunicipal(organization=org, **data)
    row.full_clean()
    _record_allowed(actor, 'saude.patients.manage', row)
    row.save()
    _audit(actor, org, 'PACIENTE_CADASTRADO', row._meta.label_lower, row.pk,
           details={'identificador': str(row.public_id)})
    return row


@transaction.atomic
def configure_health_unit(actor, *, data):
    org = _require(actor, 'saude.units.manage')
    municipal_unit = UnidadeMunicipal.objects.filter(organization=org, pk=_pk(data.get('unidade_id') or data.get('unidade'))).first()
    if municipal_unit is None:
        raise ValidationError('A unidade municipal não foi encontrada nesta Prefeitura.')
    row = m.UnidadeSaudeMunicipal(organization=org, **data)
    row.full_clean()
    _record_allowed(actor, 'saude.units.manage', row)
    row.save()
    _audit(actor, org, 'UNIDADE_SAUDE_CONFIGURADA', row._meta.label_lower, row.pk,
           details={'unidade_municipal': municipal_unit.pk, 'tipo': row.tipo})
    return row


@transaction.atomic
def configure_health_team(actor, *, data):
    org = _require(actor, 'saude.teams.manage')
    unit = m.UnidadeSaudeMunicipal.objects.filter(organization=org, pk=_pk(data.get('unidade_saude_id') or data.get('unidade_saude')), ativo=True).first()
    if unit is None:
        raise ValidationError('A unidade de saúde não foi encontrada ou está inativa.')
    _record_allowed(actor, 'saude.teams.manage', unit)
    row = m.EquipeSaudeMunicipal(organization=org, **data)
    row.full_clean()
    _record_allowed(actor, 'saude.teams.manage', row)
    row.save()
    _audit(actor, org, 'EQUIPE_SAUDE_CONFIGURADA', row._meta.label_lower, row.pk,
           details={'unidade': unit.pk, 'tipo': row.tipo})
    return row


@transaction.atomic
def configure_health_professional(actor, *, data):
    org = _require(actor, 'saude.professionals.manage')
    unit = m.UnidadeSaudeMunicipal.objects.filter(organization=org, pk=_pk(data.get('unidade_saude_id') or data.get('unidade_saude')), ativo=True).first()
    server = Servidor.objects.filter(organization=org, pk=_pk(data.get('servidor_id') or data.get('servidor')), ativo=True).first()
    team_id = _pk(data.get('equipe_id') or data.get('equipe'))
    team = m.EquipeSaudeMunicipal.objects.filter(organization=org, pk=team_id, ativo=True).first() if team_id else None
    if unit is None or server is None or (team_id and team is None):
        raise ValidationError('Selecione unidade, servidor e equipe ativos desta Prefeitura.')
    _record_allowed(actor, 'saude.professionals.manage', unit)
    _record_allowed(actor, 'saude.professionals.manage', server)
    if team and (team.unidade_saude_id != unit.pk or not has_municipal_permission(
            actor, 'saude.professionals.manage', module=m.HEALTH_MODULE, record=team)):
        raise PermissionDenied('A equipe está fora da unidade ou do escopo autorizado.')
    row = m.ProfissionalSaudeMunicipal(organization=org, **data)
    row.full_clean()
    _record_allowed(actor, 'saude.professionals.manage', row)
    row.save()
    _audit(actor, org, 'PROFISSIONAL_SAUDE_VINCULADO', row._meta.label_lower, row.pk,
           details={'servidor': server.pk, 'unidade': unit.pk})
    return row


@transaction.atomic
def configure_health_agenda(actor, *, data):
    org = _require(actor, 'saude.appointments.manage')
    unit = m.UnidadeSaudeMunicipal.objects.filter(organization=org, pk=_pk(data.get('unidade_saude_id') or data.get('unidade_saude')), ativo=True).first()
    professional = m.ProfissionalSaudeMunicipal.objects.filter(organization=org, pk=_pk(data.get('profissional_id') or data.get('profissional')), ativo=True).first()
    if unit is None or professional is None or professional.unidade_saude_id != unit.pk:
        raise ValidationError('O profissional deve estar ativo e vinculado à unidade selecionada.')
    _record_allowed(actor, 'saude.appointments.manage', unit)
    _record_allowed(actor, 'saude.appointments.manage', professional)
    row = m.AgendaSaudeMunicipal(organization=org, **data)
    row.full_clean()
    _record_allowed(actor, 'saude.appointments.manage', row)
    row.save()
    _audit(actor, org, 'AGENDA_SAUDE_CONFIGURADA', row._meta.label_lower, row.pk,
           details={'profissional': professional.pk, 'unidade': unit.pk})
    return row


@transaction.atomic
def configure_medicine(actor, *, data):
    """Create a tenant-wide medicine catalog item; global scope is required."""
    org = _require(actor, 'saude.pharmacy.manage')
    row = m.MedicamentoMunicipal(organization=org, **data)
    row.full_clean()
    _record_allowed(actor, 'saude.pharmacy.manage', row)
    row.save()
    _audit(actor, org, 'MEDICAMENTO_CADASTRADO', row._meta.label_lower, row.pk,
           details={'codigo': row.codigo, 'ativo': row.ativo})
    return row


@transaction.atomic
def receive_medicine_lot(actor, *, medicine_id, health_unit_id, lot, expires_on, quantity):
    """Register a unique lot once; repeated submissions never add stock twice."""
    org = _require(actor, 'saude.pharmacy.manage')
    medicine = m.MedicamentoMunicipal.objects.filter(
        organization=org, pk=medicine_id, ativo=True,
    ).first()
    health_unit = m.UnidadeSaudeMunicipal.objects.filter(
        organization=org, pk=health_unit_id, ativo=True,
    ).select_related('unidade__setor__departamento').first()
    if medicine is None or health_unit is None:
        raise ValidationError('Medicamento ou unidade de saúde não encontrado nesta Prefeitura.')
    _record_allowed(actor, 'saude.pharmacy.manage', health_unit)
    if expires_on < timezone.localdate():
        raise ValidationError('Não é permitido receber lote já vencido.')
    if m.LoteMedicamentoMunicipal.objects.filter(
        organization=org, medicamento=medicine, unidade_saude=health_unit, lote=lot,
    ).exists():
        raise ValidationError('Este lote já foi registrado para o medicamento e unidade; o saldo não foi alterado.')
    row = m.LoteMedicamentoMunicipal(
        organization=org, medicamento=medicine, unidade_saude=health_unit,
        lote=lot, validade=expires_on, saldo=quantity,
        **_health_hierarchy(health_unit),
    )
    row.full_clean()
    _record_allowed(actor, 'saude.pharmacy.manage', row)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        raise ValidationError('Este lote já foi registrado; nenhuma quantidade foi adicionada.') from exc
    _audit(actor, org, 'LOTE_MEDICAMENTO_RECEBIDO', row._meta.label_lower, row.pk,
           details={'medicamento': medicine.pk, 'unidade_saude': health_unit.pk,
                    'lote': row.lote, 'validade': row.validade.isoformat()})
    return row


@transaction.atomic
def record_field_visit(actor, *, request_id, visit_type, agent_id, family_id=None,
                       citizen_id=None, property_id=None, performed_at=None, observations=''):
    """Record an online ACS/ACE visit with tenant/scope checks and replay protection."""
    import uuid
    from .phase_f_models import ImovelMunicipal

    org = _require(actor, 'saude.field.manage')
    try:
        operation_id = uuid.UUID(str(request_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('Identificador da operação inválido.') from exc
    if visit_type not in dict(m.VisitaTerritorialSaude.Tipo.choices):
        raise ValidationError('Tipo de visita inválido.')
    observations = str(observations or '').strip()
    if not observations:
        raise ValidationError('Registre o resultado ou as providências da visita.')
    if performed_at is None or performed_at > timezone.now() + timedelta(minutes=5):
        raise ValidationError('Informe uma data válida, que não esteja no futuro.')

    observation_hash = hashlib.sha256(observations.encode('utf-8')).hexdigest()
    payload_hash = hashlib.sha256('\x1f'.join((
        visit_type, str(agent_id), str(family_id or ''), str(citizen_id or ''),
        str(property_id or ''), performed_at.isoformat(), observation_hash,
    )).encode('utf-8')).hexdigest()

    existing = m.VisitaTerritorialSaude.objects.filter(
        organization=org, public_id=operation_id,
    ).first()
    if existing is not None:
        _record_allowed(actor, 'saude.field.manage', existing)
        audit = m.AuditoriaAcessoSaude.objects.filter(
            organization=org, entidade=existing._meta.label_lower, entidade_id=existing.pk,
            acao='VISITA_TERRITORIAL_REGISTRADA', detalhes__request_id=str(operation_id),
        ).first()
        if audit is None or audit.detalhes.get('payload_hash') != payload_hash:
            raise ValidationError('Este identificador de operação já foi utilizado com outros dados.')
        return existing

    agent = m.ProfissionalSaudeMunicipal.objects.filter(
        organization=org, pk=agent_id, ativo=True,
        servidor__ativo=True, servidor__situacao_funcional='ATIVO', unidade_saude__ativo=True,
    ).select_related('servidor', 'equipe', 'unidade_saude__unidade').first()
    if agent is None:
        raise ValidationError('Agente não encontrado ou inativo nesta Prefeitura.')
    _record_allowed(actor, 'saude.field.manage', agent)
    if agent.equipe_id:
        accepted_team_types = {'ACS', 'ESF'} if visit_type == m.VisitaTerritorialSaude.Tipo.ACS else {'ACE'}
        if agent.equipe.tipo not in accepted_team_types:
            raise ValidationError('O tipo de agente não corresponde à equipe vinculada.')

    family = None
    if family_id:
        family = m.FamiliaTerritorialSaude.objects.filter(
            organization=org, pk=family_id, ativo=True, unidade_saude__ativo=True,
        ).select_related('unidade_saude__unidade').first()
        if family is None:
            raise ValidationError('Família não encontrada ou inativa nesta Prefeitura.')
        _record_allowed(actor, 'saude.field.manage', family)
        if family.unidade_saude_id != agent.unidade_saude_id:
            raise ValidationError('A família não pertence à unidade de saúde do agente.')

    citizen = None
    if citizen_id:
        citizen = m.CidadaoSaudeMunicipal.objects.filter(
            organization=org, pk=citizen_id, situacao='ATIVO',
        ).first()
        if citizen is None:
            raise ValidationError('Cidadão não encontrado ou inativo nesta Prefeitura.')
        _record_allowed(actor, 'saude.field.manage', citizen)
        if citizen.unidade_id and citizen.unidade_id != agent.unidade_saude.unidade_id:
            raise ValidationError('O cidadão pertence a outra unidade de saúde.')
        if family and not m.VinculoFamiliaSaude.objects.filter(
            organization=org, familia=family, cidadao=citizen,
        ).exists():
            raise ValidationError('O cidadão não está vinculado à família selecionada.')

    property_record = None
    if property_id:
        property_record = ImovelMunicipal.objects.filter(
            organization=org, pk=property_id, situacao=ImovelMunicipal.Situacao.ATIVO,
        ).first()
        if property_record is None:
            raise ValidationError('Imóvel não encontrado ou inativo nesta Prefeitura.')
        _record_allowed(actor, 'saude.field.manage', property_record)
    if visit_type == m.VisitaTerritorialSaude.Tipo.ACS and family is None and citizen is None:
        raise ValidationError('Para visita ACS, informe uma família ou um cidadão acompanhado.')
    if visit_type == m.VisitaTerritorialSaude.Tipo.ACE and property_record is None:
        raise ValidationError('Para visita ACE, informe o imóvel inspecionado.')

    cipher = _fernet()
    hierarchy = _health_hierarchy(agent.unidade_saude)
    row = m.VisitaTerritorialSaude(
        organization=org, public_id=operation_id, tipo=visit_type, agente=agent,
        familia=family, cidadao=citizen, imovel=property_record,
        realizada_em=performed_at, observacoes_cifradas=cipher.encrypt(observations.encode('utf-8')),
        status='REALIZADA', **hierarchy,
    )
    row.full_clean()
    _record_allowed(actor, 'saude.field.manage', row)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        replay = m.VisitaTerritorialSaude.objects.filter(
            organization=org, public_id=operation_id,
        ).first()
        if replay is None:
            raise ValidationError('Identificador de operação já utilizado; a visita não foi duplicada.') from exc
        _record_allowed(actor, 'saude.field.manage', replay)
        audit = m.AuditoriaAcessoSaude.objects.filter(
            organization=org, entidade=replay._meta.label_lower, entidade_id=replay.pk,
            acao='VISITA_TERRITORIAL_REGISTRADA', detalhes__request_id=str(operation_id),
        ).first()
        if audit is None or audit.detalhes.get('payload_hash') != payload_hash:
            raise ValidationError('Este identificador de operação já foi utilizado com outros dados.') from exc
        return replay
    _audit(
        actor, org, 'VISITA_TERRITORIAL_REGISTRADA', row._meta.label_lower, row.pk,
        citizen.pk if citizen else None,
        details={
            'request_id': str(operation_id), 'payload_hash': payload_hash,
            'tipo': visit_type, 'agente': agent.pk, 'familia': family.pk if family else None,
            'cidadao': citizen.pk if citizen else None,
            'imovel': property_record.pk if property_record else None,
        },
    )
    return row


@transaction.atomic
def configure_sanitary_establishment(actor, *, data):
    org = _require(actor, 'saude.sanitary.manage')
    try:
        operation_id = uuid.UUID(str(data['request_id']))
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        raise ValidationError('Identificador da operação inválido.') from exc
    secretaria = Secretaria.objects.filter(organization=org, pk=_pk(data.get('secretaria'))).first()
    department = DepartamentoMunicipal.objects.filter(
        organization=org, pk=_pk(data.get('departamento')),
    ).first()
    sector = SetorMunicipal.objects.filter(organization=org, pk=_pk(data.get('setor'))).first()
    unit = UnidadeMunicipal.objects.filter(organization=org, pk=_pk(data.get('unidade'))).first()
    if not all((secretaria, department, sector, unit)):
        raise ValidationError('Selecione uma estrutura municipal válida desta Prefeitura.')
    contributor = None
    if data.get('contribuinte'):
        from .phase_f_models import ContribuinteMunicipal
        contributor = ContribuinteMunicipal.objects.filter(
            organization=org, pk=_pk(data['contribuinte']), situacao='ATIVO',
        ).first()
        if contributor is None:
            raise ValidationError('O contribuinte não foi encontrado nesta Prefeitura.')
        _record_allowed(actor, 'saude.sanitary.manage', contributor)
    if department.secretaria_id != secretaria.pk or sector.departamento_id != department.pk or unit.setor_id != sector.pk:
        raise ValidationError('A estrutura do estabelecimento possui vínculos incompatíveis.')
    document = ''.join(character for character in str(data.get('documento') or '') if character.isdigit())
    payload_hash = _payload_fingerprint(
        contributor.pk if contributor else '', str(data.get('razao_social', '')).strip(), document,
        str(data.get('atividade', '')).strip(), str(data.get('endereco', '')).strip(),
        secretaria.pk, department.pk, sector.pk, unit.pk,
    )
    replay = _audit_replay(
        actor, org, m.EstabelecimentoSanitarioMunicipal, operation_id,
        'ESTABELECIMENTO_SANITARIO_CADASTRADO', 'saude.sanitary.manage', payload_hash,
    )
    if replay:
        return replay
    row = m.EstabelecimentoSanitarioMunicipal(
        organization=org, public_id=operation_id, contribuinte=contributor,
        razao_social=str(data['razao_social']).strip(), documento=document,
        atividade=str(data.get('atividade') or '').strip(), endereco=str(data['endereco']).strip(),
        situacao='ATIVO', secretaria=secretaria, departamento=department, setor=sector, unidade=unit,
    )
    row.full_clean()
    _record_allowed(actor, 'saude.sanitary.manage', row)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        replay = _audit_replay(
            actor, org, m.EstabelecimentoSanitarioMunicipal, operation_id,
            'ESTABELECIMENTO_SANITARIO_CADASTRADO', 'saude.sanitary.manage', payload_hash,
        )
        if replay:
            return replay
        raise ValidationError('Identificador já utilizado; o estabelecimento não foi duplicado.') from exc
    _audit(actor, org, 'ESTABELECIMENTO_SANITARIO_CADASTRADO', row._meta.label_lower, row.pk,
           details={'request_id': str(operation_id), 'payload_hash': payload_hash})
    return row


@transaction.atomic
def register_sanitary_inspection(actor, *, request_id, establishment_id, professional_id,
                                 performed_at, result, return_deadline=None, observations=''):
    org = _require(actor, 'saude.sanitary.manage')
    try:
        operation_id = uuid.UUID(str(request_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('Identificador da operação inválido.') from exc
    # Serialize idempotency checks within this tenant; InspecaoSanitariaMunicipal
    # predates the request-key field and cannot carry a unique key itself.
    org.__class__.objects.select_for_update().get(pk=org.pk)
    establishment = m.EstabelecimentoSanitarioMunicipal.objects.select_for_update().filter(
        organization=org, pk=establishment_id,
    ).first()
    professional = m.ProfissionalSaudeMunicipal.objects.filter(
        organization=org, pk=professional_id, ativo=True,
        servidor__ativo=True, servidor__situacao_funcional='ATIVO', unidade_saude__ativo=True,
    ).select_related('servidor').first()
    if establishment is None or establishment.situacao == 'INATIVO':
        raise ValidationError('Estabelecimento não encontrado ou inativo nesta Prefeitura.')
    if professional is None:
        raise ValidationError('Fiscal/profissional não encontrado ou inativo nesta Prefeitura.')
    _record_allowed(actor, 'saude.sanitary.manage', establishment)
    _record_allowed(actor, 'saude.sanitary.manage', professional)
    if result not in dict(m.InspecaoSanitariaMunicipal._meta.get_field('resultado').choices):
        raise ValidationError('Resultado da inspeção inválido.')
    if performed_at is None or performed_at > timezone.now() + timedelta(minutes=5):
        raise ValidationError('Informe uma data válida para a inspeção.')
    if return_deadline and return_deadline < performed_at.date():
        raise ValidationError('O prazo de retorno não pode anteceder a inspeção.')
    observations = str(observations or '').strip()
    if not observations:
        raise ValidationError('Registre as observações da inspeção.')
    observation_hash = hashlib.sha256(observations.encode('utf-8')).hexdigest()
    payload_hash = _payload_fingerprint(
        establishment.pk, professional.pk, performed_at.isoformat(), result,
        return_deadline.isoformat() if return_deadline else '', observation_hash,
    )
    replay_audit = m.AuditoriaAcessoSaude.objects.filter(
        organization=org, entidade=m.InspecaoSanitariaMunicipal._meta.label_lower,
        acao='INSPECAO_SANITARIA_REGISTRADA',
        detalhes__request_id=str(operation_id),
    ).first()
    if replay_audit:
        existing = m.InspecaoSanitariaMunicipal.objects.filter(
            organization=org, pk=replay_audit.entidade_id,
        ).first()
        if existing is None or replay_audit.detalhes.get('payload_hash') != payload_hash:
            raise ValidationError('Este identificador de operação já foi usado com outros dados.')
        _record_allowed(actor, 'saude.sanitary.manage', existing)
        return existing

    cipher = _fernet()
    hierarchy = {f'{name}_id': getattr(establishment, f'{name}_id') for name in ('secretaria', 'departamento', 'setor', 'unidade')}
    row = m.InspecaoSanitariaMunicipal(
        organization=org, estabelecimento=establishment, realizada_por=professional,
        realizada_em=performed_at, resultado=result, prazo_retorno=return_deadline,
        observacoes_cifradas=cipher.encrypt(observations.encode('utf-8')), **hierarchy,
    )
    row.full_clean()
    _record_allowed(actor, 'saude.sanitary.manage', row)
    row.save()
    _audit(actor, org, 'INSPECAO_SANITARIA_REGISTRADA', row._meta.label_lower, row.pk,
           details={'request_id': str(operation_id), 'payload_hash': payload_hash,
                    'estabelecimento': establishment.pk, 'resultado': result})
    return row


@transaction.atomic
def create_epidemiology_notification(actor, *, request_id, citizen_id=None, code='', description='',
                                     notified_on=None, details=''):
    org = _require(actor, 'saude.epidemiology.manage')
    try:
        operation_id = uuid.UUID(str(request_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('Identificador da operação inválido.') from exc
    code, description, details = str(code or '').strip(), str(description or '').strip(), str(details or '').strip()
    if not code and not description:
        raise ValidationError('Informe uma referência local do agravo; não há validação de classificação oficial.')
    if not details:
        raise ValidationError('Informe os detalhes restritos da notificação.')
    if notified_on is None or notified_on > timezone.localdate():
        raise ValidationError('A data da notificação não pode estar no futuro.')
    citizen = None
    if citizen_id:
        citizen = m.CidadaoSaudeMunicipal.objects.filter(
            organization=org, pk=citizen_id, situacao='ATIVO',
        ).first()
        if citizen is None:
            raise ValidationError('Cidadão não encontrado nesta Prefeitura.')
        _record_allowed(actor, 'saude.epidemiology.manage', citizen)
    elif not AcessoMunicipal.objects.filter(
        membership__user=actor, membership__organization=org, ativo=True,
        escopo=AcessoMunicipal.Escopo.PREFEITURA,
    ).exists():
        raise ValidationError('Vincule um cidadão do seu escopo para registrar a notificação.')
    details_hash = hashlib.sha256(details.encode('utf-8')).hexdigest()
    payload_hash = _payload_fingerprint(
        citizen.pk if citizen else '', code, description, notified_on.isoformat(), details_hash,
    )
    replay = _audit_replay(
        actor, org, m.NotificacaoEpidemiologicaMunicipal, operation_id,
        'NOTIFICACAO_EPIDEMIOLOGICA_REGISTRADA', 'saude.epidemiology.manage', payload_hash,
    )
    if replay:
        return replay
    hierarchy = {}
    if citizen:
        hierarchy = {f'{name}_id': getattr(citizen, f'{name}_id') for name in ('secretaria', 'departamento', 'setor', 'unidade')}
    row = m.NotificacaoEpidemiologicaMunicipal(
        organization=org, public_id=operation_id, cidadao=citizen, codigo_agravo=code,
        descricao_agravo=description, notificada_em=notified_on,
        detalhes_cifrados=_fernet().encrypt(details.encode('utf-8')),
        situacao='ABERTA', criado_por=actor, **hierarchy,
    )
    row.full_clean()
    _record_allowed(actor, 'saude.epidemiology.manage', row)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        replay = _audit_replay(
            actor, org, m.NotificacaoEpidemiologicaMunicipal, operation_id,
            'NOTIFICACAO_EPIDEMIOLOGICA_REGISTRADA', 'saude.epidemiology.manage', payload_hash,
        )
        if replay:
            return replay
        raise ValidationError('Identificador já utilizado; a notificação não foi duplicada.') from exc
    _audit(actor, org, 'NOTIFICACAO_EPIDEMIOLOGICA_REGISTRADA', row._meta.label_lower, row.pk,
           citizen.pk if citizen else None,
           details={'request_id': str(operation_id), 'payload_hash': payload_hash,
                    'codigo_local': code, 'situacao': row.situacao})
    return row


@transaction.atomic
def transition_epidemiology_notification(actor, *, notification_id, situation, justification):
    org = _require(actor, 'saude.epidemiology.manage')
    row = m.NotificacaoEpidemiologicaMunicipal.objects.select_for_update().filter(
        organization=org, pk=notification_id,
    ).first()
    if row is None:
        raise ValidationError('Notificação não encontrada nesta Prefeitura.')
    _record_allowed(actor, 'saude.epidemiology.manage', row)
    transitions = {'ABERTA': {'EM_ANALISE', 'ENCERRADA'}, 'EM_ANALISE': {'ENCERRADA'}}
    if situation not in transitions.get(row.situacao, set()):
        raise ValidationError('Transição inválida; notificação encerrada não pode ser reaberta.')
    justification = str(justification or '').strip()
    if not justification:
        raise ValidationError('Informe uma justificativa para a transição.')
    previous = row.situacao
    row.situacao = situation
    row.save(update_fields=['situacao'])
    _audit(actor, org, 'SITUACAO_NOTIFICACAO_EPI_ALTERADA', row._meta.label_lower, row.pk,
           row.cidadao_id, justification, {'anterior': previous, 'nova': situation})
    return row


@transaction.atomic
def create_clinical_entry(actor, *, appointment_id, content, justification=''):
    org = _require(actor, 'saude.records.sensitive')
    _require(actor, 'saude.records.create')
    _require(actor, 'saude.records.view')
    _require(actor, 'saude.patients.view')
    appointment = m.AtendimentoSaudeMunicipal.objects.select_for_update().filter(
        pk=appointment_id, organization=org,
    ).first()
    if appointment is None:
        raise ValidationError('Atendimento não encontrado nesta Prefeitura.')
    _record_allowed(actor, 'saude.records.sensitive', appointment)
    _record_allowed(actor, 'saude.records.create', appointment)
    _record_allowed(actor, 'saude.records.view', appointment)
    _record_allowed(actor, 'saude.patients.view', appointment.cidadao)
    if appointment.status != m.AtendimentoSaudeMunicipal.Status.EM_ATENDIMENTO:
        raise ValidationError('A evolução só pode ser registrada durante um atendimento em andamento.')
    if not str(content or '').strip():
        raise ValidationError('Informe o conteúdo da evolução clínica.')
    return _persist_clinical_entry(actor, appointment, content, justification=justification)


def _persist_clinical_entry(actor, appointment, content, *, justification='', public_id=None, retifica=None):
    """Internal writer; callers must authorize and lock the encounter first."""
    org = current_organization()
    cipher = _fernet()
    plaintext = str(content).encode('utf-8')
    row = m.EvolucaoClinicaMunicipal(
        organization=org, atendimento=appointment, conteudo_cifrado=cipher.encrypt(plaintext),
        public_id=public_id or uuid.uuid4(), retifica=retifica,
        conteudo_hash=hashlib.sha256(plaintext).hexdigest(), autor=actor,
        **{f'{key}_id': getattr(appointment, f'{key}_id') for key in ('secretaria', 'departamento', 'setor', 'unidade')},
    )
    row.save()
    _audit(actor, org, 'EVOLUCAO_CLINICA_CRIADA', row._meta.label_lower, row.pk,
           appointment.cidadao_id, justification, {'atendimento': appointment.pk})
    return row


@transaction.atomic
def read_clinical_entry(actor, *, entry_id, justification):
    org = _require(actor, 'saude.records.sensitive')
    _require(actor, 'saude.records.view')
    _require(actor, 'saude.patients.view')
    justification = (justification or '').strip()
    if not justification:
        raise ValidationError('Informe a justificativa para consultar o prontuário.')
    row = m.EvolucaoClinicaMunicipal.objects.select_related('atendimento').filter(
        pk=entry_id, organization=org,
    ).first()
    if row is None:
        raise ValidationError('Registro clínico não encontrado nesta Prefeitura.')
    _record_allowed(actor, 'saude.records.sensitive', row)
    _record_allowed(actor, 'saude.records.view', row)
    _record_allowed(actor, 'saude.patients.view', row.atendimento.cidadao)
    # Audit is committed with the read request; never log plaintext or identifiers beyond local PKs.
    _audit(actor, org, 'PRONTUARIO_ACESSADO', row._meta.label_lower, row.pk,
           row.atendimento.cidadao_id, justification, {'atendimento': row.atendimento_id})
    try:
        return _fernet().decrypt(bytes(row.conteudo_cifrado)).decode('utf-8')
    except InvalidToken as exc:
        raise ValidationError('Registro clínico não pôde ser validado; acesso bloqueado.') from exc


@transaction.atomic
def create_appointment(actor, *, agenda_id, citizen_id, request_id=None):
    org = _require(actor, 'saude.appointments.manage')
    agenda = m.AgendaSaudeMunicipal.objects.select_for_update().filter(pk=agenda_id, organization=org).first()
    citizen = m.CidadaoSaudeMunicipal.objects.filter(pk=citizen_id, organization=org).first()
    if agenda is None or citizen is None:
        raise ValidationError('Agenda ou cidadão não encontrado nesta Prefeitura.')
    _record_allowed(actor, 'saude.appointments.manage', agenda)
    _record_allowed(actor, 'saude.appointments.manage', citizen)
    try:
        operation_id = uuid.UUID(str(request_id)) if request_id else uuid.uuid4()
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('Identificador de agendamento inválido.') from exc
    previous = m.AtendimentoSaudeMunicipal.objects.filter(
        organization=org, public_id=operation_id,
    ).first()
    if previous:
        _record_allowed(actor, 'saude.appointments.manage', previous)
        if previous.agenda_id != agenda.pk or previous.cidadao_id != citizen.pk:
            raise ValidationError('A chave deste envio já foi utilizada em outro agendamento.')
        return previous
    # public_id is globally unique; reject a collision without revealing another tenant.
    if m.AtendimentoSaudeMunicipal.all_objects.filter(public_id=operation_id).exists():
        raise ValidationError('Identificador de agendamento já utilizado. Atualize o formulário e tente novamente.')
    if citizen.situacao != 'ATIVO' or not agenda.unidade_saude.ativo or not agenda.profissional.ativo:
        raise ValidationError('Agendamento indisponível: cidadão, unidade ou profissional inativo.')
    if agenda.situacao != 'ABERTA' or agenda.inicio <= timezone.now():
        raise ValidationError('A agenda não está aberta para novos atendimentos.')
    if agenda.atendimentos.filter(status=m.AtendimentoSaudeMunicipal.Status.AGENDADO).count() >= agenda.capacidade:
        raise ValidationError('A agenda atingiu a capacidade configurada.')
    row = m.AtendimentoSaudeMunicipal(
        organization=org, public_id=operation_id, cidadao=citizen, unidade_saude=agenda.unidade_saude,
        profissional=agenda.profissional, agenda=agenda,
        status=m.AtendimentoSaudeMunicipal.Status.AGENDADO, criado_por=actor,
        **{f'{key}_id': getattr(agenda, f'{key}_id') for key in ('secretaria', 'departamento', 'setor', 'unidade')},
    )
    row.full_clean()
    _record_allowed(actor, 'saude.appointments.manage', row)
    try:
        # Keep the unique public id safe even when duplicate submissions target
        # different agendas and therefore do not contend on the same row lock.
        with transaction.atomic():
            row.save()
    except IntegrityError:
        previous = m.AtendimentoSaudeMunicipal.objects.filter(
            organization=org, public_id=operation_id,
        ).first()
        if previous is None:
            raise
        _record_allowed(actor, 'saude.appointments.manage', previous)
        if previous.agenda_id != agenda.pk or previous.cidadao_id != citizen.pk:
            raise ValidationError('A chave deste envio já foi utilizada em outro agendamento.')
        return previous
    _audit(actor, org, 'ATENDIMENTO_AGENDADO', row._meta.label_lower, row.pk,
           citizen.pk, details={'agenda': agenda.pk, 'unidade': agenda.unidade_saude_id,
                               'request_id': str(operation_id)})
    return row


@transaction.atomic
def transition_appointment(actor, *, appointment_id, status, justification=''):
    """Apply an audited, tenant- and scope-checked appointment transition."""
    org = _require(actor, 'saude.appointments.manage')
    row = m.AtendimentoSaudeMunicipal.objects.select_for_update().filter(
        pk=appointment_id, organization=org,
    ).first()
    if row is None:
        raise ValidationError('Atendimento não encontrado nesta Prefeitura.')
    _record_allowed(actor, 'saude.appointments.manage', row)

    transitions = {
        m.AtendimentoSaudeMunicipal.Status.AGENDADO: {
            m.AtendimentoSaudeMunicipal.Status.EM_ATENDIMENTO,
            m.AtendimentoSaudeMunicipal.Status.CANCELADO,
            m.AtendimentoSaudeMunicipal.Status.FALTOU,
        },
        m.AtendimentoSaudeMunicipal.Status.EM_ATENDIMENTO: {
            m.AtendimentoSaudeMunicipal.Status.CONCLUIDO,
            m.AtendimentoSaudeMunicipal.Status.CANCELADO,
        },
    }
    if status not in transitions.get(row.status, set()):
        raise ValidationError('Esta mudança de situação não é permitida para o atendimento.')

    reason = (justification or '').strip()
    if status in {m.AtendimentoSaudeMunicipal.Status.CANCELADO,
                  m.AtendimentoSaudeMunicipal.Status.FALTOU} and not reason:
        raise ValidationError('Informe uma justificativa para cancelar ou registrar falta.')
    if status == m.AtendimentoSaudeMunicipal.Status.FALTOU:
        if row.agenda_id is None or row.agenda.fim > timezone.now():
            raise ValidationError('A falta só pode ser registrada após o fim do horário agendado.')

    previous = row.status
    now = timezone.now()
    row.status = status
    update_fields = ['status']
    if status == m.AtendimentoSaudeMunicipal.Status.EM_ATENDIMENTO:
        row.iniciado_em = now
        update_fields.append('iniciado_em')
    elif status == m.AtendimentoSaudeMunicipal.Status.CONCLUIDO:
        if row.iniciado_em is None:
            raise ValidationError('Inicie o atendimento antes de concluí-lo.')
        row.concluido_em = now
        update_fields.append('concluido_em')
    row.save(update_fields=update_fields)
    _audit(actor, org, 'STATUS_ATENDIMENTO_ALTERADO', row._meta.label_lower, row.pk,
           row.cidadao_id, reason, {'anterior': previous, 'novo': status})
    return row


@transaction.atomic
def dispense_fefo(actor, *, citizen_id, health_unit_id, items, request_id):
    """Atomically dispense from nonexpired lots ordered by FEFO and replay idempotently."""
    org = _require(actor, 'saude.dispense')
    try:
        operation_id = uuid.UUID(str(request_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError('Identificador de operação inválido.') from exc
    citizen = m.CidadaoSaudeMunicipal.objects.filter(pk=citizen_id, organization=org).first()
    health_unit = m.UnidadeSaudeMunicipal.objects.filter(
        pk=health_unit_id, organization=org, ativo=True,
    ).select_related('unidade__setor__departamento').first()
    if citizen is None or citizen.situacao != 'ATIVO' or health_unit is None:
        raise ValidationError('Cidadão ou unidade não encontrado nesta Prefeitura.')
    _record_allowed(actor, 'saude.dispense', health_unit)
    _record_allowed(actor, 'saude.dispense', citizen)
    try:
        normalized = sorted((int(item['medicine_id']), Decimal(str(item['quantity']))) for item in items)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ValidationError('Informe medicamentos e quantidades válidas.') from exc
    if not normalized or any(
            not quantity.is_finite() or quantity <= 0
            or quantity > Decimal('999999999.999')
            or quantity != quantity.quantize(Decimal('0.001'))
            for _, quantity in normalized):
        raise ValidationError('Informe itens e quantidades positivas.')
    medicine_ids = {medicine_id for medicine_id, _ in normalized}
    active_medicines = set(m.MedicamentoMunicipal.objects.filter(
        organization=org, ativo=True, pk__in=medicine_ids,
    ).values_list('pk', flat=True))
    if active_medicines != medicine_ids:
        raise ValidationError('Um ou mais medicamentos não estão ativos nesta Prefeitura.')
    old = m.DispensacaoMedicamentoMunicipal.objects.filter(organization=org, request_id=operation_id).first()
    if old:
        prior = defaultdict(Decimal)
        for item in old.itens.select_related('lote'):
            prior[item.lote.medicamento_id] += item.quantidade
        requested_totals = defaultdict(Decimal)
        for medicine_id, quantity in normalized:
            requested_totals[medicine_id] += quantity
        if (old.cidadao_id != citizen.pk or old.unidade_saude_id != health_unit.pk
                or dict(prior) != dict(requested_totals)):
            raise ValidationError('A chave de operação já foi usada com outro conteúdo.')
        _record_allowed(actor, 'saude.dispense', old)
        return old

    row = m.DispensacaoMedicamentoMunicipal(
        organization=org, cidadao=citizen, unidade_saude=health_unit,
        request_id=operation_id, dispensada_por=actor,
        **_health_hierarchy(health_unit),
    )
    _record_allowed(actor, 'saude.dispense', row)
    row.save()
    for medicine_id, requested in normalized:
        remaining = requested
        lots = m.LoteMedicamentoMunicipal.objects.select_for_update().filter(
            organization=org, unidade_saude=health_unit, medicamento_id=medicine_id,
            validade__gte=timezone.localdate(), saldo__gt=0,
        ).order_by('validade', 'pk')
        for lot in lots:
            take = min(lot.saldo, remaining)
            if take <= 0:
                continue
            lot.saldo -= take
            lot.save(update_fields=['saldo'])
            m.ItemDispensacaoSaude.objects.create(
                organization=org, dispensacao=row, lote=lot, quantidade=take,
                **{f'{key}_id': getattr(row, f'{key}_id') for key in ('secretaria', 'departamento', 'setor', 'unidade')},
            )
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            raise ValidationError('Estoque válido insuficiente; nenhuma dispensação foi confirmada.')
    _audit(actor, org, 'MEDICAMENTO_DISPENSADO', row._meta.label_lower, row.pk,
           citizen.pk, details={'itens': len(normalized), 'request_id': str(operation_id)})
    return row


@transaction.atomic
def change_regulation_priority(actor, *, request_id, priority, justification):
    org = _require(actor, 'saude.regulation.prioritize')
    justification = (justification or '').strip()
    if not justification:
        raise ValidationError('Informe justificativa para alterar prioridade da fila.')
    if priority not in dict(m.SolicitacaoRegulacaoSaude._meta.get_field('prioridade').choices):
        raise ValidationError('Prioridade inválida.')
    with transaction.atomic():
        row = m.SolicitacaoRegulacaoSaude.objects.select_for_update().filter(
            pk=request_id, organization=org,
        ).first()
        if row is None:
            raise ValidationError('Solicitação não encontrada nesta Prefeitura.')
        _record_allowed(actor, 'saude.regulation.prioritize', row)
        if row.status != 'FILA':
            raise ValidationError('A prioridade só pode ser alterada enquanto a solicitação estiver na fila.')
        previous = row.prioridade
        row.prioridade = priority
        row.prioridade_justificativa = 'Justificativa protegida'
        row.save(update_fields=['prioridade', 'prioridade_justificativa'])
        encrypted_reason = _fernet().encrypt(justification.encode('utf-8')).decode('ascii')
        _audit(actor, org, 'PRIORIDADE_REGULACAO_ALTERADA', row._meta.label_lower, row.pk,
               row.cidadao_id, details={'anterior': previous, 'nova': priority,
                                        'justificativa_cifrada': encrypted_reason})
    return row


def create_regulation_request(actor, *, request_id, citizen_id, origin_unit_id,
                              destination_unit_id=None, procedure, priority, justification):
    org = _require(actor, 'saude.regulation.manage')
    require_municipal_permission(actor, 'saude.patients.view', module=m.HEALTH_MODULE)
    payload_hash = _payload_fingerprint(
        citizen_id, origin_unit_id, destination_unit_id, procedure, priority, justification,
    )
    replay = _audit_replay(
        actor, org, m.SolicitacaoRegulacaoSaude, request_id,
        'SOLICITACAO_REGULACAO_CRIADA', 'saude.regulation.manage', payload_hash,
    )
    if replay:
        return replay
    citizen = m.CidadaoSaudeMunicipal.objects.filter(
        organization=org, pk=citizen_id, situacao='ATIVO',
    ).first()
    origin = m.UnidadeSaudeMunicipal.objects.filter(organization=org, pk=origin_unit_id, ativo=True).first()
    destination = None
    if destination_unit_id:
        destination = m.UnidadeSaudeMunicipal.objects.filter(
            organization=org, pk=destination_unit_id, ativo=True,
        ).first()
    if citizen is None or origin is None or (destination_unit_id and destination is None):
        raise ValidationError('Cidadão ou unidade não está disponível nesta Prefeitura.')
    _record_allowed(actor, 'saude.regulation.manage', citizen)
    _record_allowed(actor, 'saude.regulation.manage', origin)
    if destination:
        _record_allowed(actor, 'saude.regulation.manage', destination)
    procedure = (procedure or '').strip()
    justification = (justification or '').strip()
    if not procedure or not justification:
        raise ValidationError('Informe procedimento/especialidade e justificativa clínica.')
    if priority not in dict(m.SolicitacaoRegulacaoSaude._meta.get_field('prioridade').choices):
        raise ValidationError('Prioridade inicial inválida.')
    encrypted_justification = _fernet().encrypt(justification.encode('utf-8'))
    with transaction.atomic():
        from platform_core.models import Organization
        Organization.objects.select_for_update().get(pk=org.pk)
        if m.SolicitacaoRegulacaoSaude.objects.filter(organization=org, public_id=request_id).exists():
            replay = _audit_replay(
                actor, org, m.SolicitacaoRegulacaoSaude, request_id,
                'SOLICITACAO_REGULACAO_CRIADA', 'saude.regulation.manage', payload_hash,
            )
            if replay:
                return replay
            raise ValidationError('Identificador de solicitação já utilizado com outros dados.')
        row = m.SolicitacaoRegulacaoSaude.objects.create(
            organization=org, public_id=request_id, cidadao=citizen, unidade_origem=origin,
            unidade_destino=destination, procedimento=procedure, prioridade=priority,
            justificativa_cifrada=encrypted_justification, solicitado_por=actor,
            **_health_hierarchy(origin),
        )
        _audit(actor, org, 'SOLICITACAO_REGULACAO_CRIADA', row._meta.label_lower, row.pk,
               citizen.pk, details={'request_id': str(request_id), 'payload_hash': payload_hash})
    return row


def create_regulation_slot(actor, *, request_id, health_unit_id, procedure, starts_at, capacity):
    org = _require(actor, 'saude.regulation.manage')
    payload_hash = _payload_fingerprint(health_unit_id, procedure, starts_at, capacity)
    unit = m.UnidadeSaudeMunicipal.objects.filter(organization=org, pk=health_unit_id, ativo=True).first()
    if unit is None:
        raise ValidationError('A unidade ofertante não está ativa nesta Prefeitura.')
    _record_allowed(actor, 'saude.regulation.manage', unit)
    procedure = (procedure or '').strip()
    try:
        capacity_value = int(capacity)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError('Informe capacidade inteira entre 1 e 500.') from exc
    if not procedure or starts_at <= timezone.now() or isinstance(capacity, bool) or not 1 <= capacity_value <= 500:
        raise ValidationError('Informe procedimento, horário futuro e capacidade entre 1 e 500.')
    with transaction.atomic():
        from platform_core.models import Organization
        Organization.objects.select_for_update().get(pk=org.pk)
        prior = m.AuditoriaAcessoSaude.objects.filter(
            organization=org, acao='VAGA_REGULACAO_CRIADA',
            detalhes__request_id=str(request_id),
        ).first()
        if prior:
            if prior.entidade != m.VagaRegulacaoSaude._meta.label_lower or prior.detalhes.get('payload_hash') != payload_hash:
                raise ValidationError('Identificador de vaga já utilizado com outros dados.')
            row = m.VagaRegulacaoSaude.objects.filter(organization=org, pk=prior.entidade_id).first()
            if row is None:
                raise ValidationError('O registro original da vaga não está disponível; revise a auditoria.')
            _record_allowed(actor, 'saude.regulation.manage', row)
            return row
        row = m.VagaRegulacaoSaude.objects.create(
            organization=org, unidade_saude=unit,
            procedimento=procedure, inicio=starts_at, capacidade=capacity_value, ativo=True,
            **_health_hierarchy(unit),
        )
        _audit(actor, org, 'VAGA_REGULACAO_CRIADA', row._meta.label_lower, row.pk,
               details={'request_id': str(request_id), 'payload_hash': payload_hash})
    return row


def schedule_regulation_request(actor, *, operation_id, request_id, slot_id):
    org = _require(actor, 'saude.regulation.manage')
    require_municipal_permission(actor, 'saude.appointments.manage', module=m.HEALTH_MODULE)
    payload_hash = _payload_fingerprint(request_id, slot_id)
    replay = _audit_replay(
        actor, org, m.AgendamentoRegulacaoSaude, operation_id,
        'REGULACAO_AGENDADA', 'saude.regulation.manage', payload_hash,
    )
    if replay:
        return replay
    with transaction.atomic():
        request = m.SolicitacaoRegulacaoSaude.objects.select_for_update().filter(
            organization=org, pk=request_id,
        ).first()
        slot = m.VagaRegulacaoSaude.objects.select_for_update().filter(
            organization=org, pk=slot_id,
        ).first()
        if request is None or slot is None:
            raise ValidationError('Solicitação ou vaga não encontrada nesta Prefeitura.')
        _record_allowed(actor, 'saude.regulation.manage', request)
        _record_allowed(actor, 'saude.regulation.manage', slot)
        if request.status != 'FILA' or not slot.ativo or slot.inicio <= timezone.now():
            raise ValidationError('A solicitação não está na fila ou a vaga não está disponível.')
        if request.unidade_destino_id and request.unidade_destino_id != slot.unidade_saude_id:
            raise ValidationError('A vaga não pertence à unidade de destino indicada na solicitação.')
        if request.procedimento.casefold() != slot.procedimento.casefold():
            raise ValidationError('A vaga não corresponde ao procedimento/especialidade solicitado.')
        occupied = m.AgendamentoRegulacaoSaude.objects.filter(
            organization=org, vaga=slot, situacao='AGENDADO',
        ).count()
        if occupied >= slot.capacidade:
            raise ValidationError('Esta vaga já atingiu sua capacidade.')
        if m.AgendamentoRegulacaoSaude.objects.filter(organization=org, solicitacao=request).exists():
            raise ValidationError('A solicitação já possui agendamento ativo ou histórico de agendamento.')
        appointment = m.AtendimentoSaudeMunicipal.objects.create(
            organization=org, cidadao=request.cidadao, unidade_saude=slot.unidade_saude,
            profissional=None, agenda=None, status=m.AtendimentoSaudeMunicipal.Status.AGENDADO,
            criado_por=actor, **_health_hierarchy(slot.unidade_saude),
        )
        link = m.AgendamentoRegulacaoSaude.objects.create(
            organization=org, public_id=operation_id, solicitacao=request, vaga=slot,
            atendimento=appointment, criado_por=actor, **_health_hierarchy(slot.unidade_saude),
        )
        request.status = 'AGENDADA'
        request.unidade_destino = slot.unidade_saude
        request.save(update_fields=['status', 'unidade_destino'])
        _audit(actor, org, 'REGULACAO_AGENDADA', link._meta.label_lower, link.pk,
               request.cidadao_id, details={'request_id': str(operation_id), 'payload_hash': payload_hash,
                                           'solicitacao': request.pk, 'vaga': slot.pk,
                                           'atendimento': appointment.pk})
    return link


def transition_regulation_schedule(actor, *, schedule_id, situation, justification):
    org = _require(actor, 'saude.regulation.manage')
    require_municipal_permission(actor, 'saude.appointments.manage', module=m.HEALTH_MODULE)
    justification = (justification or '').strip()
    if situation not in {'ATENDIDO', 'CANCELADO'} or not justification:
        raise ValidationError('Selecione uma transição permitida e informe a justificativa.')
    with transaction.atomic():
        link = m.AgendamentoRegulacaoSaude.objects.select_for_update().select_related(
            'solicitacao', 'atendimento', 'vaga',
        ).filter(organization=org, pk=schedule_id).first()
        if link is None:
            raise ValidationError('Agendamento de regulação não encontrado nesta Prefeitura.')
        _record_allowed(actor, 'saude.regulation.manage', link)
        if link.situacao != 'AGENDADO':
            raise ValidationError('Este agendamento já foi concluído ou cancelado.')
        previous = link.situacao
        link.situacao = situation
        link.save(update_fields=['situacao'])
        appointment = link.atendimento
        request = link.solicitacao
        if situation == 'ATENDIDO':
            appointment.status = m.AtendimentoSaudeMunicipal.Status.CONCLUIDO
            appointment.iniciado_em = appointment.iniciado_em or timezone.now()
            appointment.concluido_em = timezone.now()
            request.status = 'ATENDIDA'
        else:
            appointment.status = m.AtendimentoSaudeMunicipal.Status.CANCELADO
            request.status = 'FILA'
        appointment.save(update_fields=['status', 'iniciado_em', 'concluido_em'])
        request.save(update_fields=['status'])
        encrypted_reason = _fernet().encrypt(justification.encode('utf-8')).decode('ascii')
        _audit(actor, org, 'REGULACAO_AGENDAMENTO_ALTERADO', link._meta.label_lower, link.pk,
               request.cidadao_id, details={'anterior': previous, 'nova': situation,
                                            'justificativa_cifrada': encrypted_reason,
                                            'solicitacao': request.pk, 'vaga': link.vaga_id})
    return link


def create_tfd_request(actor, *, request_id, citizen_id, destination, treatment, accompaniment=''):
    org = _require(actor, 'saude.tfd.manage')
    require_municipal_permission(actor, 'saude.patients.view', module=m.HEALTH_MODULE)
    payload_hash = _payload_fingerprint(citizen_id, destination, treatment, accompaniment)
    replay = _audit_replay(
        actor, org, m.TFDMunicipal, request_id, 'TFD_SOLICITACAO_CRIADA',
        'saude.tfd.manage', payload_hash,
    )
    if replay:
        return replay
    citizen = m.CidadaoSaudeMunicipal.objects.filter(
        organization=org, pk=citizen_id, situacao='ATIVO',
    ).first()
    if citizen is None:
        raise ValidationError('O cidadão não está ativo nesta Prefeitura.')
    _record_allowed(actor, 'saude.tfd.manage', citizen)
    values = {
        'destino': (destination or '').strip(),
        'tratamento': (treatment or '').strip(),
        'acompanhante': (accompaniment or '').strip(),
    }
    if not values['destino'] or not values['tratamento']:
        raise ValidationError('Informe destino e finalidade da solicitação.')
    encrypted = _fernet().encrypt(json.dumps(values, ensure_ascii=False).encode('utf-8')).decode('ascii')
    with transaction.atomic():
        if m.TFDMunicipal.objects.filter(organization=org, public_id=request_id).exists():
            replay = _audit_replay(
                actor, org, m.TFDMunicipal, request_id, 'TFD_SOLICITACAO_CRIADA',
                'saude.tfd.manage', payload_hash,
            )
            if replay:
                return replay
            raise ValidationError('Identificador da solicitação já utilizado.')
        row = m.TFDMunicipal.objects.create(
            organization=org, public_id=request_id, cidadao=citizen,
            # Legacy text columns remain generic; actual health details only exist encrypted.
            destino='Dados protegidos', tratamento='Dados protegidos', acompanhante='',
            documentos=[{'tipo': 'TFD_DADOS_CIFRADOS', 'payload': encrypted}],
            criado_por=actor,
        )
        _audit(actor, org, 'TFD_SOLICITACAO_CRIADA', row._meta.label_lower, row.pk,
               citizen.pk, details={'request_id': str(request_id), 'payload_hash': payload_hash})
    return row


def transition_tfd_request(actor, *, request_id, status, justification):
    org = _require(actor, 'saude.tfd.manage')
    justification = (justification or '').strip()
    if not justification:
        raise ValidationError('Informe a justificativa da decisão.')
    with transaction.atomic():
        row = m.TFDMunicipal.objects.select_for_update().filter(organization=org, pk=request_id).first()
        if row is None:
            raise ValidationError('Solicitação de TFD não encontrada nesta Prefeitura.')
        _record_allowed(actor, 'saude.tfd.manage', row)
        allowed = {
            'PENDENTE': {'AUTORIZADA', 'NEGADA'},
            'AUTORIZADA': {'CONCLUIDA'},
        }
        if status not in allowed.get(row.status, set()):
            raise ValidationError('Transição de TFD inválida; solicitações negadas ou concluídas não podem ser reabertas.')
        previous = row.status
        row.status = status
        row.save(update_fields=['status'])
        _audit(actor, org, 'TFD_SITUACAO_ALTERADA', row._meta.label_lower, row.pk,
               row.cidadao_id, justification, {'anterior': previous, 'nova': status})
    return row


def register_sus_production(actor, *, request_id, competence, record_type, health_unit_id,
                            citizen_id=None, professional_id=None, procedure_code='', quantity=1):
    org = _require(actor, 'saude.production.manage')
    if citizen_id:
        require_municipal_permission(actor, 'saude.patients.view', module=m.HEALTH_MODULE)
    payload_hash = _payload_fingerprint(
        competence, record_type, health_unit_id, citizen_id, professional_id, procedure_code, quantity,
    )
    replay = _audit_replay(
        actor, org, m.RegistroProducaoSUS, request_id, 'PRODUCAO_SUS_REGISTRADA',
        'saude.production.manage', payload_hash,
    )
    if replay:
        return replay
    import re
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', str(competence or '')):
        raise ValidationError('Competência inválida; use AAAA-MM.')
    if record_type not in dict(m.RegistroProducaoSUS.Tipo.choices):
        raise ValidationError('Tipo de registro de produção inválido.')
    try:
        quantity_value = int(quantity)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError('Informe uma quantidade válida entre 1 e 100.000.') from exc
    if isinstance(quantity, bool) or quantity_value < 1 or quantity_value > 100000:
        raise ValidationError('Informe uma quantidade entre 1 e 100.000.')
    unit = m.UnidadeSaudeMunicipal.objects.filter(organization=org, pk=health_unit_id, ativo=True).first()
    if unit is None:
        raise ValidationError('A unidade de saúde não está ativa nesta Prefeitura.')
    _record_allowed(actor, 'saude.production.manage', unit)
    citizen = None
    if citizen_id:
        citizen = m.CidadaoSaudeMunicipal.objects.filter(organization=org, pk=citizen_id, situacao='ATIVO').first()
        if citizen is None:
            raise ValidationError('O cidadão não está ativo nesta Prefeitura.')
        _record_allowed(actor, 'saude.production.manage', citizen)
    professional = None
    if professional_id:
        professional = m.ProfissionalSaudeMunicipal.objects.filter(
            organization=org, pk=professional_id, ativo=True, unidade_saude=unit,
        ).first()
        if professional is None:
            raise ValidationError('O profissional não está ativo na unidade selecionada.')
        _record_allowed(actor, 'saude.production.manage', professional)
    with transaction.atomic():
        if m.RegistroProducaoSUS.objects.filter(organization=org, public_id=request_id).exists():
            replay = _audit_replay(
                actor, org, m.RegistroProducaoSUS, request_id, 'PRODUCAO_SUS_REGISTRADA',
                'saude.production.manage', payload_hash,
            )
            if replay:
                return replay
            raise ValidationError('Identificador da operação já utilizado.')
        row = m.RegistroProducaoSUS.objects.create(
            organization=org, public_id=request_id, competencia=competence,
            tipo=record_type, unidade_saude=unit, cidadao=citizen, profissional=professional,
            codigo_procedimento=(procedure_code or '').strip(), quantidade=quantity_value,
            dados_snapshot_cifrado=b'', status_transmissao='NAO_TRANSMITIDO', criado_por=actor,
            **_health_hierarchy(unit),
        )
        _audit(actor, org, 'PRODUCAO_SUS_REGISTRADA', row._meta.label_lower, row.pk,
               citizen.pk if citizen else None,
               details={'request_id': str(request_id), 'payload_hash': payload_hash,
                        'status_transmissao': 'NAO_TRANSMITIDO'})
    return row


def health_dashboard(actor):
    org = _require(actor, 'saude.dashboard.view')
    # Only aggregate counts are returned; no patient identity or clinical detail is exposed.
    from .public_services import scoped_queryset
    return {
        'units': scoped_queryset(actor, m.UnidadeSaudeMunicipal.objects.filter(organization=org)).filter(ativo=True).count(),
        'teams': scoped_queryset(actor, m.EquipeSaudeMunicipal.objects.filter(organization=org)).filter(ativo=True).count(),
        'appointments_today': scoped_queryset(actor, m.AtendimentoSaudeMunicipal.objects.filter(
            organization=org, iniciado_em__date=timezone.localdate(),
        )).count(),
        'dispensations_today': scoped_queryset(actor, m.DispensacaoMedicamentoMunicipal.objects.filter(
            organization=org, dispensada_em__date=timezone.localdate(), status='CONFIRMADA',
        )).count(),
        'official_integrations': 'PENDENTES_DE_HOMOLOGACAO',
    }
