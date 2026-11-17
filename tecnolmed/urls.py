from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from platform_core import media_views
from platform_core.health import health

urlpatterns = [
    path('health/', health, name='health'),
    path('saas/', RedirectView.as_view(url='/vertyx/saas/', permanent=False)),
    path('saas/<path:subpath>', RedirectView.as_view(url='/vertyx/saas/%(subpath)s', permanent=False)),
    path("admin/", admin.site.urls),
    path("", include('commercial.urls')),
    path("vertyx/", include('platform_core.urls')),
    path("gestao-publica/", include('rh_municipal.public_urls')),
    path("gestao-publica/rh/", include('rh_municipal.urls')),
    path("", include("core.urls")),
    path("contas/", include("contas.urls")),
    path("clientes/", include("clientes.urls")),
    path("equipamentos/", include("equipamentos.urls")),
    path("ordens/", include("ordens.urls")),
    path("", include("gestao.urls")),
    path("", include("operacao.urls")),
    path('media/<path:name>', media_views.legacy_media, name='legacy_media'),
]
