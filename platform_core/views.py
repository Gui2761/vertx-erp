from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import OrganizationMembership, ERPCatalog, PlatformAudit


@login_required
def home(request):
    if request.membership and request.membership.role == 'TECNICO' and not request.GET.get('organizacoes'):
        from .access import has_erp_access
        if has_erp_access(request.user, request.organization):
            return redirect('operacao:tecnico')
    if request.membership and request.membership.role in ['VENDEDOR','PDV'] and not request.GET.get('organizacoes'):
        from .access import has_erp_access
        if has_erp_access(request.user, request.organization):
            return redirect('operacao:seller_home')
    memberships = request.user.memberships.filter(status='ATIVO', organization__status='ATIVA').select_related('organization')
    erps = []
    if request.organization:
        erps = ERPCatalog.objects.filter(code='assistencia', active=True, organizationerp__organization=request.organization, organizationerp__enabled=True, membershiperp__membership=request.membership, membershiperp__enabled=True).distinct()
    return render(request, 'platform_core/home.html', {'memberships': memberships, 'erps': erps})


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
            return redirect('operacao:seller_home')
    return redirect('platform_core:home')
