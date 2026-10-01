from django.db.models import F
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
    if label == 'orcamento' and action in ['ORCAMENTO_APROVADO', 'ORCAMENTO_RECUSADO']:
        deliver(key, action.replace('_', ' ').capitalize(), str(instance), ['ADMIN', 'GESTOR'], f'/orcamentos/{instance.pk}/')

def scan(user):
    from gestao.models import Peca, Contrato, Lancamento
    from gestao.permissions import allowed
    from ordens.services import visiveis
    from .models import PreventivaProgramada, DocumentoFiscal
    today = timezone.localdate()
    for order in visiveis(user).filter(prazo__lt=timezone.now()).exclude(status__in=['FINALIZADA','APROVADA','FATURADA','CANCELADA']):
        deliver(f'os-atrasada:{order.pk}:{today}', 'OS atrasada', str(order), ['ADMIN', 'GESTOR'], f'/ordens/{order.pk}/', order.tecnico.usuario if order.tecnico_id else None)
    if allowed(user, 'contratos'):
        for contract in Contrato.objects.exclude(status__in=['SUSPENSO','ENCERRADO']).filter(data_final__lte=today + timezone.timedelta(days=30)):
            deliver(f'contrato:{contract.pk}:{today}', 'Contrato vencendo/vencido', str(contract), ['ADMIN', 'GESTOR'], f'/contratos/{contract.pk}/')
        for item in PreventivaProgramada.objects.filter(plano__ativo=True, data__lte=today + timezone.timedelta(days=30), ordem__isnull=True, cancelada=False).select_related('plano__tecnico'):
            deliver(f'preventiva:{item.pk}:{today}', 'Preventiva próxima/atrasada', str(item), ['ADMIN', 'GESTOR'], '/planejamento/', item.plano.tecnico.usuario if item.plano.tecnico_id else None)
    if allowed(user, 'estoque_escrever'):
        from .stock import scan_stock
        scan_stock(user)
    if allowed(user, 'financeiro'):
        for entry in Lancamento.objects.filter(status__in=['PENDENTE','VENCIDO'], vencimento__lte=today + timezone.timedelta(days=7)):
            deliver(f'conta:{entry.pk}:{today}', 'Conta vencendo/vencida', entry.descricao, ['ADMIN', 'GESTOR', 'FINANCEIRO', 'CONTABILIDADE'], f'/financeiro/lancamentos/{entry.pk}/')
        for note in DocumentoFiscal.objects.filter(status='AUTORIZADA'):
            deliver(f'nota:{note.pk}', 'Nota emitida pelo provedor', str(note), ['ADMIN','GESTOR','FINANCEIRO','CONTABILIDADE'], f'/fiscal/{note.pk}/')
