"""Consulta a mesma origem em contas originais e parcelas, sem duplicar recebíveis."""
from django.db.models import Q


def origin_query(**criteria):
    return Q(**criteria) | Q(**{'origem_raiz__' + key: value for key, value in criteria.items()})


def origin_type_query(kind):
    names = {'OS': 'ordem', 'ORCAMENTO': 'orcamento', 'CONTRATO': 'contrato', 'VENDA': 'venda_origem', 'COMPRA': 'compra_origem','DEVOLUCAO':'devolucao_origem'}
    if kind in names:
        return origin_query(**{names[kind] + '__isnull': False})
    if kind == 'MANUAL':
        condition = Q()
        for name in names.values():
            condition &= ~origin_query(**{name + '__isnull': False})
        return condition
    return Q()
