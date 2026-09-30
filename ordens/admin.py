from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import OrdemServico, Localizacao, Foto, Conferencia, Assinatura, Auditoria
from platform_core.business_admin import BusinessAdmin


class ConsultaAdmin(BusinessAdmin):
    pass


@admin.register(OrdemServico)
class OrdemAdmin(ConsultaAdmin):
    list_display = ['numero', 'cliente', 'tecnico', 'status', 'abrir']
    list_filter = ['status']

    @admin.display(description='Atendimento / reabertura auditada')
    def abrir(self, obj):
        return format_html('<a href="{}">Abrir OS</a>', reverse('ordens:detalhe', args=[obj.pk]))


@admin.register(Localizacao)
class LocalizacaoAdmin(ConsultaAdmin):
    list_display = ['ordem', 'evento', 'resultado', 'registrado_em', 'mapa']

    def mapa(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">Ver localização no mapa</a>', obj.mapa_url) if obj.mapa_url else 'Não obtida'


for model in [Foto, Conferencia, Assinatura, Auditoria]:
    admin.site.register(model, ConsultaAdmin)
