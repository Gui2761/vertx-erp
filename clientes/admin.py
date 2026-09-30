from django.contrib import admin

from .models import Cliente, ContatoCliente, Unidade
from platform_core.business_admin import BusinessAdmin


class ContatoInline(admin.TabularInline):
    model = ContatoCliente
    extra = 1


class UnidadeInline(admin.TabularInline):
    model = Unidade
    extra = 1


@admin.register(Cliente)
class ClienteAdmin(BusinessAdmin):
    list_display = ("nome_razao_social", "cpf_cnpj", "tipo_pessoa", "telefone", "ativo")
    list_filter = ("tipo_pessoa", "ativo")
    search_fields = ("nome_razao_social", "nome_fantasia", "cpf_cnpj")
    inlines = [ContatoInline, UnidadeInline]


@admin.register(Unidade)
class UnidadeAdmin(BusinessAdmin):
    list_display = ("nome", "cliente", "cidade", "uf", "ativo")
    list_filter = ("ativo", "uf")
    search_fields = ("nome", "cliente__nome_razao_social")
