from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from .context import tenant_context
from .models import OrganizationMembership
from .access import erp_code_for_path
from .access import require_erp

PUBLIC_COMMERCIAL_PATHS = {'/', '/planos/', '/demonstracao/', '/contato/', '/solicitacao-recebida/', '/suporte/', '/termos/', '/privacidade/', '/login/', '/robots.txt'}


class OrganizationMiddleware:
    """Seleciona apenas memberships válidos; a sessão nunca é autoridade por si só."""
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        # SaaS administration has its own platform capability. Tenant role
        # routing is not an authority for these routes; the SaaS view guard is.
        if request.path.startswith('/saas/'):
            return None
        membership = getattr(request, 'membership', None)
        product_specific_route = request.path.startswith(('/gestao-publica/', '/loja-hospitalar/'))
        if membership and membership.role in {'VENDEDOR','PDV'} and request.path not in PUBLIC_COMMERCIAL_PATHS and not product_specific_route:
            from operacao.seller_access import route_allowed
            if not route_allowed(request.resolver_match,request.user):
                response = HttpResponseForbidden('Acesso restrito à Central de Vendas.')
                response['Cache-Control'] = 'private, no-store'
                return response
        if membership and membership.role == 'TECNICO' and request.path not in PUBLIC_COMMERCIAL_PATHS and not product_specific_route:
            from operacao.technician_access import route_allowed
            if request.path != '/' and not route_allowed(request.resolver_match):
                response = HttpResponseForbidden('Acesso restrito à operação técnica. Volte para Meus atendimentos.')
                response['Cache-Control'] = 'private, no-store'
                return response

    def __call__(self, request):
        request.organization = None
        request.membership = None
        if request.user.is_authenticated:
            memberships = OrganizationMembership.objects.filter(user=request.user, status='ATIVO', organization__status='ATIVA').select_related('organization')
            selected = request.session.get('organization_id')
            membership = memberships.filter(organization_id=selected).first() if isinstance(selected, int) else None
            if membership is None:
                request.session.pop('organization_id', None)
                candidates = list(memberships[:2])
                if len(candidates) == 1:
                    membership = candidates[0]
                    request.session['organization_id'] = membership.organization_id
            if membership:
                request.organization = membership.organization
                request.membership = membership
        # Todo endpoint fora de plataforma/login/admin/static é Assistência e exige ERP.
        public = request.path.startswith(('/vertyx/', '/contas/login/', '/contas/logout/', '/admin/', '/static/', '/saas/', '/primeiro-acesso/')) or request.path in PUBLIC_COMMERCIAL_PATHS | {'/health/', '/manifest.webmanifest', '/manifest-pdv.webmanifest', '/sw.js','/pdv/manifest.webmanifest','/vendedor/manifest.webmanifest','/pdv/sw.js','/vendedor/sw.js','/pdv/entrar/','/vendedor/entrar/'}
        if request.path.startswith('/admin/') and request.user.is_authenticated and not request.user.is_superuser:
            response = HttpResponseForbidden('O Django Admin pertence à operação VERTYX. Use a administração da organização no ERP.')
            response['Cache-Control'] = 'private, no-store'
            return response
        if not public:
            if not request.user.is_authenticated:
                login='operacao:pdv_login' if request.path.startswith('/pdv/') else 'operacao:seller_login' if request.path.startswith('/vendedor/') else 'contas:login'
                return redirect_to_login(request.get_full_path(), reverse(login))
            if request.organization is None:
                return redirect('platform_core:home')
            if request.membership.role in ['PAINEL', 'PAINEL_TV'] and not request.path.startswith('/painel-operacional/'):
                return HttpResponseForbidden('Acesso restrito ao painel operacional.')
            import re
            equipment_qr = bool(re.fullmatch(r'/equipamentos/qr/[0-9a-fA-F-]{36}/', request.path))
            if request.membership.role == 'CLIENTE' and not request.path.startswith('/portal/') and not equipment_qr:
                return HttpResponseForbidden('Acesso restrito ao portal do cliente.')
            try:
                require_erp(request.user, request.organization, code=erp_code_for_path(request.path))
            except PermissionDenied:
                return HttpResponseForbidden('Acesso ao ERP Assistência não autorizado nesta organização.')
        with tenant_context(request.organization):
            if not public:
                from .modules import module_enabled, module_for_path
                if not module_enabled(module_for_path(request.path)):
                    response=HttpResponseForbidden('Módulo desabilitado nesta organização.')
                    response['Cache-Control']='private, no-store'
                    return response
            response = self.get_response(request)
        if request.path != '/health/' and not request.path.startswith(('/static/', '/sw.js', '/manifest.webmanifest', '/manifest-pdv.webmanifest')):
            response['Cache-Control'] = 'private, no-store'
        return response
