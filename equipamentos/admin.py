from django.contrib import admin

from .models import CategoriaEquipamento, Equipamento
from platform_core.business_admin import BusinessAdmin


@admin.register(CategoriaEquipamento)
class CategoriaEquipamentoAdmin(BusinessAdmin):
    list_display = ("nome", "descricao")
    search_fields = ("nome",)


@admin.register(Equipamento)
class EquipamentoAdmin(BusinessAdmin):
    list_display = (
        "nome",
        "cliente",
        "unidade",
        "categoria",
        "situacao_operacional",
        "codigo_interno",
    )
    list_filter = ("categoria", "situacao_operacional", "cliente")
    search_fields = ("nome", "codigo_interno", "numero_serie", "cliente__nome_razao_social")
    readonly_fields = ("codigo_publico", "qr_code")
