"""Private, bounded integration authorization. Never sourced from HTTP parameters."""
from contextvars import ContextVar
from contextlib import contextmanager
from platform_core.context import current_organization
from platform_core.modules import require_capability, module_enabled
from django.core.exceptions import PermissionDenied

_scope = ContextVar('official_commerce_operation',default=None)

@contextmanager
def _execution(user, sale=None, session=None, entry=None, account_ids=()):
    require_capability(user,'pdv')
    if not module_enabled('financeiro') or sale and not module_enabled('estoque'):
        raise PermissionDenied('PDV requer os módulos de estoque e financeiro habilitados.')
    for obj in (sale,session,entry):
        if obj and obj.organization_id != current_organization().pk:
            raise PermissionDenied('Origem fora da organização.')
    from .models import ContaBancaria
    accounts=set(account_ids)
    if ContaBancaria.objects.filter(pk__in=accounts,ativo=True).count()!=len(accounts):
        raise PermissionDenied('Conta fora da organização ou inativa.')
    token=_scope.set({'user':user.pk,'org':current_organization().pk,'sale':sale,'session':session,'entry':entry,'accounts':accounts})
    try: yield
    finally: _scope.reset(token)

def _authorized(user, domain, **params):
    value=_scope.get()
    if not value or value['user']!=user.pk or not current_organization() or value['org']!=current_organization().pk:
        return False
    sale,session,entry=value['sale'],value['session'],value['entry']
    if domain=='stock':
        return bool(sale and params.get('sale_id')==sale.pk and params.get('kind')=='SAIDA' and params.get('depot_id')==sale.deposito_id and sale.itens.filter(peca_id=params.get('part_id')).exists())
    if domain=='payment':
        return bool(entry and entry.pk==params.get('entry_id'))
    if domain=='cash':
        return bool(session and (params.get('account_id')==session.conta_id or params.get('account_id') in value['accounts']))
    if domain=='reserve':
        return bool(sale and sale.pk==params.get('sale_id') and sale.deposito_id==params.get('depot_id') and sale.itens.filter(peca_id=params.get('part_id')).exists())
    return False
