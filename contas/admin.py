from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario, Tecnico
from platform_core.business_admin import BusinessAdmin


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "perfil", "is_active", "is_staff")
    list_filter = ("perfil", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("Dados TECNOLMED", {"fields": ("perfil", "telefone")}),
    )


@admin.register(Tecnico)
class TecnicoAdmin(BusinessAdmin):
    list_display = ("nome", "especialidades", "ativo", "usuario")
    list_filter = ("ativo",)
    search_fields = ("nome", "especialidades", "registro_profissional")
