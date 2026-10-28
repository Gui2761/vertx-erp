from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import OrganizationMembership, ERPCatalog, PlatformAudit
from .access import erp_code_for_path as _product_route_code


@login_required
def home(request):
    if request.membership and request.membership.role == 'TECNICO' and not request.GET.get('organizacoes'):
        from .access import has_erp_access
        if has_erp_access(request.user, request.organization):
            return redirect('operacao:tecnico')
    if request.membership and request.membership.role in ['VENDEDOR','PDV'] and not request.GET.get('organizacoes'):
        from .access import has_erp_access
        if has_erp_access(request.user, request.organization):
            return redirect('operacao:pdv_home' if request.membership.role=='PDV' else 'operacao:seller_home')
    memberships = request.user.memberships.filter(status='ATIVO', organization__status='ATIVA').select_related('organization')
    erps = []
    if request.organization:
        catalog = ERPCatalog.objects.filter(
            active=True, organizationerp__organization=request.organization,
            organizationerp__enabled=True, membershiperp__membership=request.membership,
            membershiperp__enabled=True,
        ).distinct().order_by('name')
        for erp in catalog:
            if erp.code == 'assistencia':
                role = request.membership.role
                from .context import tenant_context
                from .modules import has_capability
                with tenant_context(request.organization):
                    seller_allowed = has_capability(request.user, 'central_vendedor')
                    cashier_allowed = has_capability(request.user, 'operar_pdv')
                if role in {'TECNICO', 'CLIENTE', 'VENDEDOR', 'PDV', 'PAINEL', 'PLANEJADOR', 'ATENDIMENTO'}:
                    if role == 'TECNICO':
                        url, label = '/tecnico/', 'Acessar meus atendimentos'
                    elif role == 'CLIENTE':
                        url, label = '/portal/', 'Acessar meu portal'
                    elif role in {'VENDEDOR', 'PDV'}:
                        if role == 'VENDEDOR' and seller_allowed:
                            url, label = '/vendedor/', 'Acessar minhas vendas'
                        elif role == 'PDV' and cashier_allowed:
                            url, label = '/pdv/', 'Abrir o caixa'
                        else:
                            url, label = '', 'Acesso operacional não atribuído.'
                    elif role == 'PAINEL':
                        url, label = '/painel-operacional/', 'Abrir painel operacional'
                    else:
                        url, label = '/planejamento/', 'Abrir planejamento'
                else:
                    url, label = '/assistencia/', 'Entrar no ERP Assistência'
                erps.append({'name': 'VERTYX Assistência Técnica', 'description': erp.description, 'url': url, 'label': label, 'enabled': bool(url)})
            elif erp.code == 'gestao-publica':
                from rh_municipal.public_services import has_municipal_permission
                allowed = has_municipal_permission(request.user, 'dashboard.view')
                erps.append({
                    'name': 'VERTYX Gestão Pública',
                    'description': erp.description or 'Gestão de servidores e estrutura municipal.',
                    'url': '/gestao-publica/' if allowed else '',
                    'label': 'Acessar Gestão Pública' if allowed else 'Acesso municipal ainda não atribuído.',
                    'enabled': allowed,
                })
            elif erp.operational and erp.entry_path and _product_route_code(erp.entry_path) == erp.code:
                erps.append({'name': erp.name, 'description': erp.description, 'url': erp.entry_path, 'label': f'Entrar em {erp.name}', 'enabled': True})
            else:
                erps.append({'name': erp.name, 'description': erp.description, 'url': '', 'label': 'Produto ainda não disponível neste ambiente.', 'enabled': False})
    if not request.GET.get('organizacoes') and len(erps) == 1 and erps[0]['enabled'] and erps[0]['url']:
        return redirect(erps[0]['url'])
    return render(request, 'platform_core/home.html', {
        'memberships': memberships,
        'erps': erps,
        'show_organization_selector': memberships.count() > 1,
    })


@login_required
@require_POST
def select_organization(request):
    public_id = request.POST.get('organization', '')
    from django.core.exceptions import ValidationError
    try:
        membership = get_object_or_404(OrganizationMembership, user=request.user, status='ATIVO', organization__status='ATIVA', organization__public_id=public_id)
    except ValidationError:
        return HttpResponseBadRequest('Identificador de organização inválido.')
    previous = request.session.get('organization_id')
    request.session['organization_id'] = membership.organization_id
    request.session.cycle_key()
    PlatformAudit.objects.create(organization=membership.organization, user=request.user, action='ORGANIZACAO_SELECIONADA', record=f'membership:{membership.pk}', changes={'anterior': previous, 'posterior': membership.organization_id})
    if membership.role == 'TECNICO':
        from .access import has_erp_access
        if has_erp_access(request.user, membership.organization):
            return redirect('operacao:tecnico')
    if membership.role in {'VENDEDOR','PDV'}:
        from .access import has_erp_access
        if has_erp_access(request.user, membership.organization):
            return redirect('operacao:pdv_home' if membership.role=='PDV' else 'operacao:seller_home')
    return redirect('platform_core:home')
