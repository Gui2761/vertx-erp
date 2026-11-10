from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from .context import tenant_context
from .models import OrganizationMembership
from .access import erp_code_for_path, require_erp

PUBLIC_COMMERCIAL_PATHS = {'/', '/planos/', '/demonstracao/', '/contato/', '/solicitacao-recebida/', '/suporte/', '/termos/', '/privacidade/', '/login/', '/cadastro/', '/cadastro/confirmacao/', '/cadastro/primeiro-acesso/', '/robots.txt'}


def _forbidden(request, message, title='Acesso Não Permitido'):
    from django.shortcuts import render
    try:
        response = render(request, '403.html', {'exception': message, 'titulo': title}, status=403)
    except Exception:
        response = HttpResponseForbidden(message)
    response['Cache-Control'] = 'private, no-store'
    return response


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
                return _forbidden(request, 'Acesso restrito à Central de Vendas.', 'Central de Vendas')
        if membership and membership.role == 'TECNICO' and request.path not in PUBLIC_COMMERCIAL_PATHS and not product_specific_route:
            from operacao.technician_access import route_allowed
            if request.path != '/' and not route_allowed(request.resolver_match):
                return _forbidden(request, 'Acesso restrito à operação técnica. Volte para Meus atendimentos.', 'Operação Técnica')

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
        public = request.path.startswith(('/vertyx/', '/contas/login/', '/contas/logout/', '/admin/', '/static/', '/saas/', '/primeiro-acesso/', '/gestao-publica/convites/aceitar/', '/gestao-publica/publico/')) or request.path in PUBLIC_COMMERCIAL_PATHS | {'/health/', '/manifest.webmanifest', '/manifest-pdv.webmanifest', '/sw.js','/pdv/manifest.webmanifest','/vendedor/manifest.webmanifest','/tecnico/manifest.webmanifest','/pdv/sw.js','/vendedor/sw.js','/tecnico/sw.js','/pdv/entrar/','/vendedor/entrar/','/gestao-publica/','/gestao-publica/login/','/gestao-publica/manifest.webmanifest','/gestao-publica/sw.js'}
        if request.path.startswith('/admin/') and request.user.is_authenticated and not request.user.is_superuser:
            return _forbidden(request, 'O Django Admin pertence à operação VERTYX. Use a administração da organização no ERP.', 'Administração VERTYX')
        if not public:
            if not request.user.is_authenticated:
                login='operacao:pdv_login' if request.path.startswith('/pdv/') else 'operacao:seller_login' if request.path.startswith('/vendedor/') else 'contas:login'
                return redirect_to_login(request.get_full_path(), reverse(login))
            if request.organization is None:
                return redirect('platform_core:home')
            if request.membership.role in ['PAINEL', 'PAINEL_TV'] and not request.path.startswith('/painel-operacional/'):
                return _forbidden(request, 'Acesso restrito ao painel operacional.', 'Painel Operacional')
            import re
            equipment_qr = bool(re.fullmatch(r'/equipamentos/qr/[0-9a-fA-F-]{36}/', request.path))
            if request.membership.role == 'CLIENTE' and not request.path.startswith('/portal/') and not equipment_qr:
                return _forbidden(request, 'Acesso restrito ao portal do cliente.', 'Portal do Cliente')
            product_code = erp_code_for_path(request.path)
            if product_code is None:
                return _forbidden(request, 'Esta rota ainda não está associada a um produto VERTYX autorizado.', 'Rota Não Autorizada')
            try:
                require_erp(request.user, request.organization, code=product_code)
            except PermissionDenied:
                return _forbidden(request, 'Produto ou acesso do usuário não autorizado nesta organização.', 'Permissão Insuficiente')
            with tenant_context(request.organization):
                if not public:
                    from .modules import product_module_enabled, required_modules_for_path
                    required = required_modules_for_path(request.path, request.resolver_match)
                    if any(not product_module_enabled(request.user, product_code, code, request.organization) for code in required):
                        return _forbidden(request, 'Módulo não contratado ou desabilitado nesta organização.', 'Módulo Não Contratado')
                response = self.get_response(request)
        else:
            with tenant_context(request.organization):
                response = self.get_response(request)
        if request.path != '/health/' and not request.path.startswith(('/static/', '/sw.js', '/manifest.webmanifest', '/manifest-pdv.webmanifest')):
            response['Cache-Control'] = 'private, no-store'
        return response
