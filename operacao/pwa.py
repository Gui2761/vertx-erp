import json
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.urls import reverse

def manifest(request):
    # Keep the installed application's identity; the server selects the role.
    return JsonResponse({'id': '/tecnico/', 'name': 'VERTYX Assistência', 'short_name': 'VERTYX', 'lang': 'pt-BR', 'start_url': reverse('platform_core:home'), 'scope': '/', 'display': 'standalone', 'background_color': '#f4f7fa', 'theme_color': '#006f74', 'icons': [{'src': '/static/pwa/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}, {'src': '/static/pwa/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}]}, content_type='application/manifest+json')

def worker(request):
    response = HttpResponse((Path(settings.BASE_DIR) / 'static/pwa/sw.js').read_text(encoding='utf-8'), content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response
