from django.core.exceptions import PermissionDenied
from .context import current_organization
from .models import OrganizationMembership, OrganizationERP, MembershipERP


def _org_req_cache(organization):
    if organization is None:
        return None
    cache = getattr(organization, '_req_cache', None)
    if cache is None:
        try:
            organization._req_cache = {}
            cache = organization._req_cache
        except (AttributeError, TypeError):
            return None
    return cache


def membership_for(user, organization=None):
    organization = organization or current_organization()
    if organization is None or not user.is_authenticated or not user.is_active or organization.status != 'ATIVA':
        return None
    cache = _org_req_cache(organization)
    key = ('membership', user.pk)
    if cache is not None and key in cache:
        m = cache[key]
        if m is not None and m.status == 'ATIVO':
            return m
    m = OrganizationMembership.objects.filter(user=user, organization=organization, status='ATIVO').select_related('organization').first()
    if cache is not None:
        cache[key] = m
    return m


def has_erp_access(user, organization=None, code='assistencia'):
    organization = organization or current_organization()
    membership = membership_for(user, organization)
    if membership is None:
        return False
    cache = _org_req_cache(membership.organization)
    if cache is not None:
        org_erps = cache.get(('org_erps',))
        if org_erps is None:
            org_erps = set(
                OrganizationERP.objects.filter(
                    organization=membership.organization, erp__active=True, enabled=True
                ).values_list('erp__code', flat=True)
            )
            cache[('org_erps',)] = org_erps
        mem_key = ('member_erps', membership.pk)
        mem_erps = cache.get(mem_key)
        if mem_erps is None:
            mem_erps = set(
                MembershipERP.objects.filter(
                    membership=membership, erp__active=True, enabled=True
                ).values_list('erp__code', flat=True)
            )
            cache[mem_key] = mem_erps
        return code in org_erps and code in mem_erps
    return OrganizationERP.objects.filter(organization=membership.organization, erp__code=code, erp__active=True, enabled=True).exists() and MembershipERP.objects.filter(membership=membership, erp__code=code, erp__active=True, enabled=True).exists()


PRODUCT_ROUTE_PREFIXES = (
    # Municipal routes are a separate product and never fall through to the
    # business ERP.
    ('/gestao-publica/', 'gestao-publica'),
    ('/loja-hospitalar/', 'loja-hospitalar'),
    # Explicit compatibility map for the currently shipped assistance ERP.
    # PDV and seller experiences remain here until a separately approved
    # product entitlement migration moves organizations to Comercio e PDV.
    ('/assistencia/', 'assistencia'),
    ('/gestao/', 'assistencia'),
    ('/clientes/', 'assistencia'),
    ('/equipamentos/', 'assistencia'),
    ('/ordens/', 'assistencia'),
    ('/chamados/', 'assistencia'),
    ('/preventivas/', 'assistencia'),
    ('/planejamento/', 'assistencia'),
    ('/tecnico/', 'assistencia'),
    ('/portal/', 'assistencia'),
    ('/portal-acessos/', 'assistencia'),
    ('/conhecimento/', 'assistencia'),
    ('/pdv/', 'assistencia'),
    ('/vendedor/', 'assistencia'),
    ('/vendas/', 'assistencia'),
    ('/estoque/', 'assistencia'),
    ('/depositos/', 'assistencia'),
    ('/inventarios/', 'assistencia'),
    ('/transferencias/', 'assistencia'),
    ('/compras/', 'assistencia'),
    ('/orcamentos/', 'assistencia'),
    ('/categorias-pecas/', 'assistencia'),
    ('/checklists/', 'assistencia'),
    ('/configuracoes/', 'assistencia'),
    ('/cadastro-inicial/', 'assistencia'),
    ('/empresa/', 'assistencia'),
    ('/financeiro/', 'assistencia'),
    ('/bancos/', 'assistencia'),
    ('/relatorios/', 'assistencia'),
    ('/documentos/', 'assistencia'),
    ('/fiscal/', 'assistencia'),
    ('/rh/', 'assistencia'),
    ('/ponto/', 'assistencia'),
    ('/integracoes/', 'assistencia'),
    ('/contratos/', 'assistencia'),
    ('/painel-operacional/', 'assistencia'),
    # Operational notifications are served by the business ERP and still
    # enforce the user's active membership and role in the view.
    ('/notificacoes/', 'assistencia'),
    ('/pesquisa/', 'assistencia'),
    ('/contas/', 'assistencia'),
    ('/media/', 'assistencia'),
)


def erp_code_for_path(path):
    """Return an explicitly registered product or None for an unknown route."""
    return next((code for prefix, code in PRODUCT_ROUTE_PREFIXES if path.startswith(prefix)), None)


def require_erp(user, organization=None, roles=None, code='assistencia'):
    membership = membership_for(user, organization)
    if membership is None or not has_erp_access(user, organization, code=code) or roles is not None and membership.role not in roles:
        raise PermissionDenied('Organização, acesso ao ERP ou permissão insuficiente.')
    return membership


def effective_role(user):
    membership = membership_for(user)
    return membership.role if membership else ''
