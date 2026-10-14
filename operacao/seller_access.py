"""Backend boundary for the sales experience, using the active membership."""
from platform_core.access import effective_role

SELLER_ROLES = {'VENDEDOR', 'PDV'}

def is_seller(user):
    return effective_role(user) in SELLER_ROLES

def route_allowed(match, user=None):
    if match is None:
        return True
    namespace, name = match.namespace, match.url_name
    if namespace == 'platform_core':
        return name in {'home', 'select_organization'}
    if namespace == 'contas':
        return name in {'login', 'logout'}
    if namespace == 'clientes':
        return name == 'cliente_create'  # Existing limited creation permission.
    if namespace == 'operacao':
        if name in {'pdv_home','pdv_cash','pdv_sale','pdv_products','pdv_receipt','pdv_history','pdv_offline','pdv_prepare','pdv_sync','pdv_sync_context','pdv_offline_shell'}:
            from platform_core.modules import has_capability
            return bool(user and has_capability(user,'operar_pdv'))
        return name in {
            'seller_home','seller_sales','seller_goal','seller_commission','seller_alerts',
            'seller_customer','seller_notice_read','pdv_home','pdv_cash','pdv_sale',
            'pdv_products','pdv_receipt','ponto_home','ponto_mirror','ponto_overtime',
            'documento_arquivo','documento_lista','documento_detalhe','documento_novo',
            'manifest','pdv_manifest','pdv_manifest_scoped','seller_manifest','worker','pdv_worker','seller_worker',
            'seller_login','pdv_login','seller_ponto','seller_overtime','seller_mirror','seller_sale_detail',
        }
    return name in {'health', 'legacy_media'}
