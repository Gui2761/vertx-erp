"""UI for preparing official integration endpoints; no transmission occurs."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from platform_core.context import current_organization
from . import phase_l_services as service
from .phase_e_services import public_module_available
from .phase_l_forms import IntegrationConfigurationForm
from .phase_l_models import INTEGRATION_MODULES, ConfiguracaoIntegracaoMunicipal
from .public_services import has_municipal_permission
from .public_views import _context


@login_required
@require_http_methods(['GET', 'POST'])
def integrations_home(request):
    organization = current_organization()
    if organization is None:
        raise PermissionDenied('Selecione uma Prefeitura para continuar.')

    visible_providers = []
    manageable_providers = []
    for provider, module in INTEGRATION_MODULES.items():
        if not public_module_available(organization, module):
            continue
        if has_municipal_permission(request.user, 'integration.view', module=module):
            visible_providers.append(provider)
        if has_municipal_permission(request.user, 'integration.manage', module=module):
            manageable_providers.append(provider)
    if not visible_providers and not manageable_providers:
        raise PermissionDenied('Nenhuma integração contratada e autorizada está disponível para esta Prefeitura.')

    form = IntegrationConfigurationForm(actor=request.user) if manageable_providers else None
    if request.method == 'POST':
        if form is None:
            raise PermissionDenied('Você não tem permissão para configurar integrações.')
        form = IntegrationConfigurationForm(request.POST, actor=request.user)
        if form.is_valid():
            try:
                row = service.create_configuration(
                    request.user, provider=form.cleaned_data['provedor'],
                    name=form.cleaned_data['nome'], endpoint=form.cleaned_data['endpoint'],
                    api_version=form.cleaned_data['versao_api'],
                    environment=form.cleaned_data['ambiente'],
                    credential_reference=form.cleaned_data['referencia_credencial'],
                )
            except (PermissionDenied, ValidationError) as exc:
                error = '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
                return render(request, 'rh_municipal/phase_l_integrations.html', _context(
                    request, title='Integrações oficiais', integration_form=form,
                    integration_error=error, integration_rows=_safe_rows(request.user, organization, visible_providers, manageable_providers),
                ), status=400)
            messages.success(request, f'Configuração {row.nome} salva como preparação. Nenhuma transmissão foi realizada.')
            return redirect('rh_municipal_public:integrations')
        status = 400
    else:
        status = 200

    return render(request, 'rh_municipal/phase_l_integrations.html', _context(
        request, title='Integrações oficiais', integration_form=form,
        integration_error=None,
        integration_rows=_safe_rows(request.user, organization, visible_providers, manageable_providers),
        integration_providers=visible_providers,
    ), status=status)


def _safe_rows(actor, organization, visible_providers, manageable_providers):
    providers = set(visible_providers) | set(manageable_providers)
    rows = ConfiguracaoIntegracaoMunicipal.objects.filter(
        organization=organization, provedor__in=providers,
    ).order_by('provedor', 'nome')
    return [{
        'nome': row.nome,
        'provedor': row.get_provedor_display(),
        'endpoint': row.endpoint,
        'versao_api': row.versao_api,
        'ambiente': row.get_ambiente_display(),
        'referencia_configurada': bool(row.referencia_credencial),
        'habilitada': False,
    } for row in rows]
