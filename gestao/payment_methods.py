"""Organization-scoped defaults for the existing PDV payment-method catalog."""

from platform_core.context import tenant_context
from .models import FormaPagamento


DEFAULT_PDV_METHODS = (
    ('Dinheiro', 'DINHEIRO', True),
    ('PIX', 'PIX', False),
    ('Cartão de Débito', 'DEBITO', False),
    ('Cartão de Crédito', 'CREDITO', False),
    ('Boleto', 'BOLETO', False),
    ('Transferência Bancária', 'TRANSFERENCIA', False),
    ('Outros', 'OUTRO', False),
)


def ensure_default_pdv_methods(organization):
    """Create the catalog for a newly provisioned tenant; never rewrite existing choices."""
    created = []
    with tenant_context(organization):
        for name, kind, active in DEFAULT_PDV_METHODS:
            method, was_created = FormaPagamento.objects.get_or_create(
                organization=organization,
                nome=name,
                defaults={'tipo_pdv': kind, 'ativo': active},
            )
            if was_created:
                created.append(method)
    return created
