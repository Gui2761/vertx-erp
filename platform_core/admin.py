from django.contrib import admin
from .models import Organization, ERPCatalog, OrganizationERP, OrganizationMembership, MembershipERP, PlatformAudit
from .forms import OrganizationForm


class PlatformAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False  # Desativar/suspender preserva histórico.

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        organization = obj if isinstance(obj, Organization) else getattr(obj, 'organization', None)
        if isinstance(obj, MembershipERP):
            organization = obj.membership.organization
        if organization:
            PlatformAudit.objects.create(organization=organization, erp=getattr(obj, 'erp', None), user=request.user, action='PLATAFORMA_ALTERACAO' if change else 'PLATAFORMA_CRIACAO', record=f'{obj._meta.label}:{obj.pk}', changes={'campos': [name for name in form.changed_data if name not in ['password']]})


class AuditAdmin(PlatformAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(PlatformAdmin):
    form = OrganizationForm
    list_display = ['display_name', 'cnpj_formatado', 'status']


for model in [ERPCatalog, OrganizationERP, OrganizationMembership, MembershipERP]:
    admin.site.register(model, PlatformAdmin)
admin.site.register(PlatformAudit, AuditAdmin)
