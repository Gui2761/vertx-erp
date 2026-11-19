import json
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.urls import reverse

def _get_org_name(request):
    org = getattr(request, 'organization', None)
    if org and getattr(org, 'display_name', None):
        return org.display_name
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        m = user.memberships.filter(status='ATIVO').select_related('organization').first()
        if m and m.organization:
            return m.organization.display_name
    return 'VERTYX'


def manifest(request):
    # Keep the installed application's identity; the server selects the role.
    org_name = _get_org_name(request)
    display_title = f"{org_name} Assistência" if org_name != 'VERTYX' else "VERTYX Assistência"
    short_title = org_name if org_name != 'VERTYX' else "VERTYX"
    return JsonResponse({'id': '/tecnico/', 'name': display_title, 'short_name': short_title, 'lang': 'pt-BR', 'start_url': reverse('platform_core:home'), 'scope': '/', 'display': 'standalone', 'background_color': '#f4f7fa', 'theme_color': '#006f74', 'icons': [{'src': '/static/pwa/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}, {'src': '/static/pwa/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}]}, content_type='application/manifest+json')


def pdv_manifest(request):
    # Separate launch identity, same ERP, authentication and service worker.
    response=manifest(request)
    data=json.loads(response.content)
    data.update(id='/pdv/',name='VERTYX PDV',short_name='VERTYX PDV',start_url=reverse('operacao:pdv_home'),scope='/pdv/',theme_color='#112b3e',description='Caixa e vendas VERTYX. Operações offline ficam pendentes até sincronização.')
    response=JsonResponse(data,content_type='application/manifest+json')
    response['Cache-Control']='no-cache'
    return response


def seller_manifest(request):
    data=json.loads(manifest(request).content)
    data.update(id='/vendedor/',name='VERTYX Vendedor',short_name='VERTYX Vendedor',start_url='/vendedor/',scope='/vendedor/',description='Rotina, ponto, resultados e mensagens pessoais do vendedor.')
    response=JsonResponse(data,content_type='application/manifest+json')
    response['Cache-Control']='no-cache'
    return response


def technician_manifest(request):
    """Give the field technician app its own install identity and scope."""
    data=json.loads(manifest(request).content)
    data.update(
        id='/tecnico/', name='VERTYX Técnico', short_name='VERTYX Técnico',
        start_url='/tecnico/', scope='/tecnico/',
        description='Atendimentos e rotina operacional do técnico VERTYX.',
    )
    response=JsonResponse(data,content_type='application/manifest+json')
    response['Cache-Control']='no-cache'
    return response


def admin_manifest(request):
    """PWA manifest for Administrators, Managers and ERP desktop/mobile install."""
    org_name = _get_org_name(request)
    display_title = f"{org_name} · Gestão ERP" if org_name != 'VERTYX' else "VERTYX Admin & Gestão"
    short_title = f"{org_name} Admin" if org_name != 'VERTYX' else "VERTYX Admin"
    return JsonResponse({
        'id': '/admin-app/',
        'name': display_title,
        'short_name': short_title,
        'description': f'Painel Administrativo, Gestão, Loja e Assistência Técnica {org_name}',
        'lang': 'pt-BR',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#0b111d',
        'theme_color': '#0b111d',
        'icons': [
            {'src': '/static/pwa/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
            {'src': '/static/pwa/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}
        ]
    }, content_type='application/manifest+json')


def scoped_worker(request,app):
    assert app in {'pdv','vendedor','tecnico'}
    response=HttpResponse((Path(settings.BASE_DIR)/f'static/pwa/{app}-sw.js').read_text(encoding='utf-8'),content_type='application/javascript')
    response['Service-Worker-Allowed']=f'/{app}/'
    response['Cache-Control']='no-cache, no-store, must-revalidate'
    return response

def worker(request):
    response = HttpResponse((Path(settings.BASE_DIR) / 'static/pwa/sw.js').read_text(encoding='utf-8'), content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response
