from django.contrib import admin


class BusinessAdmin(admin.ModelAdmin):
    """Consulta no tenant explicitamente selecionado; alterações pelo fluxo do ERP."""
    def has_view_permission(self, request, obj=None):
        from .access import has_erp_access, effective_role
        return request.user.is_superuser and has_erp_access(request.user) and effective_role(request.user) in ['ADMIN', 'GESTOR']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
