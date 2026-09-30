from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from platform_core import media_views
from platform_core.health import health

urlpatterns = [
    path('health/', health, name='health'),
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name='platform_core:home', permanent=False)),
    path("vertyx/", include('platform_core.urls')),
    path("", include("core.urls")),
    path("contas/", include("contas.urls")),
    path("clientes/", include("clientes.urls")),
    path("equipamentos/", include("equipamentos.urls")),
    path("ordens/", include("ordens.urls")),
    path('media/<path:name>', media_views.legacy_media, name='legacy_media'),
]
