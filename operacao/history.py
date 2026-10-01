from gestao.models import Contrato, Orcamento, Lancamento, Movimentacao
from gestao.permissions import allowed
from ordens.services import visiveis
from .models import DocumentoFiscal, PreventivaProgramada
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
        ctx['historico_financeiro'] = Lancamento.objects.filter(cliente=customer, **({'ordem__equipamento': equipment} if equipment else {}))[:30]
        ctx['historico_fiscal'] = DocumentoFiscal.objects.filter(cliente=customer, **({'ordem__equipamento': equipment} if equipment else {}))[:30]
    if equipment and allowed(user, 'estoque'):
        moves = Movimentacao.objects.filter(ordem__equipamento=equipment)
        if not allowed(user, 'estoque_escrever'):
            moves = moves.filter(ordem__tecnico__usuario=user)
        ctx['historico_pecas'] = moves.select_related('peca')[:50]
    return ctx
