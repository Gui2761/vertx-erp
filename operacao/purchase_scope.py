"""Bounded authority for approved receipts; no general stock privilege."""
from contextlib import contextmanager
from contextvars import ContextVar
from django.core.exceptions import PermissionDenied
from platform_core.context import current_organization
from platform_core.modules import require_capability, module_enabled
_receipt=ContextVar('purchase_receipt_operation',default=None)
@contextmanager
def _execution(user,purchase,depot,item,quantity):
    require_capability(user,'compras')
    if not module_enabled('estoque') or purchase.organization_id!=current_organization().pk or purchase.status!='PEDIDO' or item.compra_id!=purchase.pk or quantity>item.quantidade_pendente:
        raise PermissionDenied('Recebimento fora do pedido/organização ou estoque desabilitado.')
    value=_receipt.set((user.pk,current_organization().pk,item.peca_id,depot.pk,quantity,item.pk))
    try: yield
    finally: _receipt.reset(value)
def _authorized(user,part_id,kind,quantity,depot_id,data):
    value=_receipt.get()
    return bool(value and current_organization() and kind=='ENTRADA' and data and value==(user.pk,current_organization().pk,part_id,depot_id,quantity,getattr(data.get('item_compra'),'pk',None)))
