from gestao.models import Contrato, Orcamento, Lancamento, Movimentacao
from gestao.permissions import allowed
from gestao.financial_origin import origin_query
from ordens.services import visiveis
from .models import DocumentoFiscal, PreventivaProgramada, Chamado
from .permissions import documents

def related(user, customer, equipment=None):
    orders = visiveis(user).filter(cliente=customer)
    docs = documents(user).filter(cliente=customer)
    occurrences = PreventivaProgramada.objects.filter(plano__cliente=customer).select_related('plano', 'equipamento')
    if not allowed(user, 'contratos'):
        occurrences = occurrences.filter(plano__tecnico__usuario=user)
    if equipment:
        orders = orders.filter(equipamento=equipment)
        docs = docs.filter(equipamento=equipment) | docs.filter(ordem__equipamento=equipment)
        occurrences = occurrences.filter(equipamento=equipment)
    ctx = {'historico_os': orders[:50], 'historico_documentos': docs.distinct()[:50], 'historico_preventivas': occurrences[:50]}
    if allowed(user, 'contratos'):
        contracts = Contrato.objects.filter(cliente=customer)
        if equipment:
            contracts = contracts.filter(equipamentos=equipment)
        ctx['historico_contratos'] = contracts.distinct()[:30]
        ctx['historico_orcamentos'] = Orcamento.objects.filter(cliente=customer, **({'equipamento': equipment} if equipment else {}))[:30]
    if allowed(user, 'financeiro'):
        financial = Lancamento.objects.filter(cliente=customer)
        if equipment:
            financial = financial.filter(origin_query(ordem__equipamento=equipment) | origin_query(orcamento__equipamento=equipment) | origin_query(contrato__equipamentos=equipment))
        ctx['historico_financeiro'] = financial.distinct()[:30]
        ctx['historico_fiscal'] = DocumentoFiscal.objects.filter(cliente=customer, **({'ordem__equipamento': equipment} if equipment else {}))[:30]
    if equipment and allowed(user, 'estoque'):
        moves = Movimentacao.objects.filter(ordem__equipamento=equipment)
        if not allowed(user, 'estoque_escrever'):
            moves = moves.filter(ordem__in=visiveis(user))
        ctx['historico_pecas'] = moves.select_related('peca')[:50]
    return ctx


def equipment_timeline(user, equipment, portal=False):
    """Projection of official events; no second history or economic recalculation."""
    from django.core.exceptions import PermissionDenied
    from django.urls import reverse
    from django.utils import timezone
    from django.db.models import Q
    from platform_core.access import effective_role
    from platform_core.context import current_organization
    from platform_core.models import PlatformAudit
    from ordens.models import OrdemServico
    from gestao.models import AgendaPreventiva
    from .permissions import portal_clients
    if equipment.organization_id != current_organization().pk:
        raise PermissionDenied('Equipamento de outra organização.')
    if portal:
        if equipment.cliente_id not in portal_clients(user):
            raise PermissionDenied('Equipamento não autorizado no portal.')
        orders = OrdemServico.objects.filter(equipamento=equipment)
        calls = Chamado.objects.filter(equipamento=equipment)
    else:
        orders = visiveis(user).filter(equipamento=equipment)
        calls = Chamado.objects.filter(equipamento=equipment)
        if effective_role(user) != 'ADMIN' and effective_role(user) != 'GESTOR':
            calls = calls.filter(Q(tecnico__usuario=user) | Q(ordem__in=orders))
    docs = documents(user).filter(Q(equipamento=equipment) | Q(ordem__equipamento=equipment)).distinct()
    result = {}
    def append(source, pk, when, title, description='', url=''):
        if when:
            if not hasattr(when, 'hour'):
                when = timezone.make_aware(timezone.datetime.combine(when, timezone.datetime.min.time()))
            result[(source, pk)] = {'fonte': source, 'id': pk, 'data': when, 'titulo': title, 'descricao': description, 'url': url}
    append('cadastro', equipment.pk, equipment.criado_em, 'Equipamento cadastrado', equipment.nome)
    if equipment.data_instalacao:
        append('instalacao', equipment.pk, equipment.data_instalacao, 'Data de instalação cadastrada')
    for call in calls:
        append('chamado', call.pk, call.criado_em, call.numero, call.get_status_display(), reverse('operacao:portal_chamado_detalhe' if portal else 'operacao:chamado_detalhe', args=[call.pk]))
    for order in orders:
        url = reverse('operacao:portal_os' if portal else 'ordens:detalhe', args=[order.pk])
        append('os-abertura', order.pk, order.abertura, f'{order.numero} · {order.get_tipo_atendimento_display()}', order.get_status_display(), url)
        append('os-inicio', order.pk, order.inicio, f'{order.numero} · Atendimento iniciado', '', url)
        append('os-conclusao', order.pk, order.conclusao, f'{order.numero} · Atendimento concluído', '', url)
    for document in docs:
        append('documento', document.pk, document.criado_em, document.titulo, document.get_categoria_display() or document.get_tipo_display(), reverse('operacao:portal_documento' if portal else 'operacao:documento_arquivo', args=[document.pk]))
    for model, field, kwargs in [(PreventivaProgramada, 'data', {'plano__ativo': True}), (AgendaPreventiva, 'data_prevista', {})]:
        qs = model.objects.filter(equipamento=equipment, cancelada=False, **kwargs)
        if not portal and effective_role(user) == 'TECNICO':
            qs = qs.filter(Q(ordem__in=orders) | Q(**{('plano__tecnico__usuario' if model == PreventivaProgramada else 'tecnico__usuario'): user}))
        elif not portal and effective_role(user) not in ['ADMIN', 'GESTOR']:
            qs = qs.none()
        for item in qs:
            append(model._meta.model_name, item.pk, getattr(item, field), 'Preventiva prevista', item.situacao)
    if not portal and allowed(user, 'estoque'):
        for move in Movimentacao.objects.filter(ordem__in=orders).select_related('peca'):
            append('movimento', move.pk, move.criado_em, move.get_tipo_display(), f'{move.peca.sku} · {move.quantidade}')
    if not portal and effective_role(user) in ['ADMIN', 'GESTOR']:
        for audit in PlatformAudit.objects.filter(organization=current_organization(), record=f'{equipment._meta.label}:{equipment.pk}'):
            append('auditoria', audit.pk, audit.created_at, audit.action.replace('_', ' ').capitalize(), str(audit.user))
    return sorted(result.values(), key=lambda item: (item['data'], item['fonte'], item['id']), reverse=True)
