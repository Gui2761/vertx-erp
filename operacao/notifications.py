from django.db.models import F
from django.db import transaction
from django.utils import timezone
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership
from .models import Notificacao

def deliver(key, title, message, roles, link='', assigned=None, occurrence=None):
    org = current_organization()
    recipients = OrganizationMembership.objects.filter(organization=org, status='ATIVO', user__is_active=True, role__in=roles, erp_accesses__erp__code='assistencia', erp_accesses__enabled=True).select_related('user')
    for member in recipients.distinct():
        if occurrence:
            Notificacao.objects.update_or_create(usuario=member.user,chave=key,defaults={'titulo':title[:180],'mensagem':message,'link':link,'ocorrencia_estoque':occurrence})
        else:
            Notificacao.objects.get_or_create(usuario=member.user, chave=key, defaults={'titulo': title[:180], 'mensagem': message, 'link': link})
    if assigned and assigned.is_active and assigned.memberships.filter(organization=org, status='ATIVO', role='TECNICO', erp_accesses__enabled=True, erp_accesses__erp__code='assistencia').exists():
        Notificacao.objects.get_or_create(usuario=assigned, chave=key, defaults={'titulo': title[:180], 'mensagem': message, 'link': link})

def event(user, action, instance):
    label = instance._meta.model_name
    key = f'{instance._meta.label}:{instance.pk}:{action}:{getattr(instance,"revisao",0)}'
    if label == 'ordemservico' and action in ['CRIACAO', 'ATRIBUICAO', 'ALTERACAO', 'ALTERACAO_APOS_REABERTURA', 'PLANEJAMENTO']:
        deliver(key, 'OS atribuída', str(instance), ['ADMIN', 'GESTOR'], f'/ordens/{instance.pk}/', instance.tecnico.usuario if instance.tecnico_id else None)
        for auxiliary in instance.auxiliares.filter(ativo=True, usuario__isnull=False):
            deliver(key, 'OS atribuída à equipe', str(instance), [], f'/ordens/{instance.pk}/', auxiliary.usuario)
    if label == 'orcamento' and action in ['ORCAMENTO_APROVADO', 'ORCAMENTO_RECUSADO']:
        deliver(key, action.replace('_', ' ').capitalize(), str(instance), ['ADMIN', 'GESTOR'], f'/orcamentos/{instance.pk}/')

def scan(user):
    from gestao.models import Peca, Contrato, Lancamento
    from gestao.permissions import allowed
    from ordens.services import visiveis
    from .models import PreventivaProgramada, DocumentoFiscal
    today = timezone.localdate()
    scan_operational(user)
    from .block3_notices import scan as scan_block3
    scan_block3(user)
    if allowed(user, 'estoque_escrever'):
        from .stock import scan_stock
        scan_stock(user)
    if allowed(user, 'financeiro'):
        wanted = {f'ops-fin:conta:{entry.pk}': ('Conta vencendo/vencida', entry.descricao, f'/financeiro/lancamentos/{entry.pk}/', None) for entry in Lancamento.objects.filter(status__in=['PENDENTE','VENCIDO'], vencimento__lte=today + timezone.timedelta(days=7))}
        sync_notices(user, 'ops-fin:', wanted, ['ADMIN', 'GESTOR', 'FINANCEIRO', 'CONTABILIDADE'])
        for note in DocumentoFiscal.objects.filter(status='AUTORIZADA'):
            deliver(f'nota:{note.pk}', 'Nota emitida pelo provedor', str(note), ['ADMIN','GESTOR','FINANCEIRO','CONTABILIDADE'], f'/fiscal/{note.pk}/')

@transaction.atomic
def sync_notices(user, prefix, wanted, roles, own_only=False):
    from platform_core.models import Organization
    from gestao.services import audit
    Organization.objects.select_for_update().get(pk=current_organization().pk)
    now = timezone.now()
    for key, (title, message, link, assigned) in wanted.items():
        deliver(key, title, message, roles, link, assigned)
        for notice in Notificacao.objects.filter(chave=key):
            reopened = bool(notice.resolvida_em)
            notice.titulo, notice.mensagem, notice.link = title[:180], message, link
            if reopened:
                notice.resolvida_em, notice.lida_em = None, None
                audit(user, 'ALERTA_REABERTO', notice, {'chave': key})
            notice.save()
    obsolete = Notificacao.objects.filter(chave__startswith=prefix, resolvida_em__isnull=True).exclude(chave__in=wanted)
    if own_only:
        obsolete = obsolete.filter(usuario=user)
    for notice in obsolete:
        notice.resolvida_em = now
        notice.save()
        audit(user, 'ALERTA_RESOLVIDO', notice, {'chave': notice.chave})

def scan_operational(user):
    from django.db.models import Q
    from platform_core.access import effective_role
    from gestao.permissions import allowed
    from gestao.models import Contrato, AgendaPreventiva
    from equipamentos.models import Equipamento
    from ordens.services import visiveis
    from .models import PreventivaProgramada, Documento, ENCERRADAS, NecessidadePecaOS
    today = timezone.localdate()
    manager = allowed(user, 'contratos')
    role = effective_role(user)
    if role in ['ADMIN', 'GESTOR', 'ESTOQUE', 'TECNICO']:
        from .stock import need_remaining
        needs = NecessidadePecaOS.objects.filter(resolvida_em__isnull=True).exclude(ordem__status__in=ENCERRADAS).select_related('ordem__tecnico', 'peca', 'deposito')
        if role == 'TECNICO':
            needs = needs.filter(ordem__in=visiveis(user))
        wanted_needs = {f'peca-necessaria:{need.pk}': ('Peça necessária para atendimento', f'{need.ordem.numero} · {need.peca} · pendente {need_remaining(need)}', '/estoque/necessidades/', need.ordem.tecnico.usuario if need.ordem.tecnico_id else None) for need in needs if need_remaining(need)}
        sync_notices(user, 'peca-necessaria:', wanted_needs, ['ADMIN', 'GESTOR', 'ESTOQUE'], own_only=role == 'TECNICO')
    wanted = {}
    for order in visiveis(user).filter(prazo__lt=timezone.now()).exclude(status__in=ENCERRADAS):
        wanted[f'ops-os:{order.pk}'] = ('OS atrasada', str(order), f'/ordens/{order.pk}/', order.tecnico.usuario if order.tecnico_id else None)
    sync_notices(user, 'ops-os:', wanted, ['ADMIN', 'GESTOR'], own_only=not manager)
    if not manager:
        return
    wanted = {}
    def add(key, title, message, link, assigned=None):
        wanted['ops:' + key] = (title, message, link, assigned)
    for contract in Contrato.objects.exclude(status__in=['SUSPENSO', 'ENCERRADO']):
        if contract.data_final <= today + timezone.timedelta(days=30):
            add(f'contrato:{contract.pk}', 'Contrato vencido' if contract.data_final < today else 'Contrato próximo do vencimento', str(contract), f'/contratos/{contract.pk}/')
        completed = contract.ordemservico_set.filter(tipo_atendimento__in=['VISITA', 'PREVENTIVA'], status__in=['FINALIZADA', 'APROVADA', 'FATURADA'], conclusao__date__range=(contract.data_inicial, contract.data_final)).count()
        if contract.quantidade_visitas > completed and contract.data_inicial <= today:
            add(f'visitas:{contract.pk}', 'Visitas contratuais pendentes', f'{contract.numero}: {contract.quantidade_visitas - completed} visitas previstas ainda não executadas', f'/contratos/{contract.pk}/')
    for model, field, kwargs in [(PreventivaProgramada, 'data', {'plano__ativo': True}), (AgendaPreventiva, 'data_prevista', {})]:
        qs = model.objects.filter(cancelada=False, **{field + '__lte': today + timezone.timedelta(days=30)}, **kwargs).exclude(ordem__status__in=ENCERRADAS)
        if model == AgendaPreventiva:
            qs = qs.exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO'])
        for item in qs:
            tech = item.plano.tecnico if model == PreventivaProgramada else item.tecnico
            add(f'{model._meta.model_name}:{item.pk}', 'Preventiva vencida' if getattr(item, field) < today else 'Preventiva próxima', str(item), '/planejamento/', tech.usuario if tech else None)
    for equipment in Equipamento.objects.filter(periodicidade_preventiva_meses__isnull=False).exclude(situacao_cadastro__in=['INATIVO', 'FORA_USO', 'BAIXADO']).exclude(situacao_operacional='DESATIVADO'):
        has_plan = PreventivaProgramada.objects.filter(equipamento=equipment, plano__ativo=True, cancelada=False).exclude(ordem__status__in=ENCERRADAS).exists()
        has_visit = AgendaPreventiva.objects.filter(equipamento=equipment, cancelada=False).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO']).exclude(ordem__status__in=ENCERRADAS).exists()
        if not has_plan and not has_visit:
            add(f'sem-plano:{equipment.pk}', 'Equipamento sem plano preventivo', equipment.nome, f'/equipamentos/{equipment.pk}/')
    for document in Documento.objects.filter(validade__lte=today + timezone.timedelta(days=30)):
        add(f'documento:{document.pk}', 'Documento vencido' if document.validade < today else 'Documento próximo do vencimento', document.titulo, f'/documentos/{document.pk}/')
    sync_notices(user, 'ops:', wanted, ['ADMIN', 'GESTOR'])
