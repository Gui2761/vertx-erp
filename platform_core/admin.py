from django.contrib import admin
from .models import Organization, ERPCatalog, OrganizationERP, OrganizationMembership, MembershipERP, PlatformAudit
from .forms import OrganizationForm
from .saas_models import (
    AdministradorPlataforma, AssinaturaSaaS, AuditoriaSaaS,
    HistoricoPlanoSaaS, PlanoSaaS, PrimeiroAcessoSaaS,
)
from .saas_services import registrar


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


@admin.register(AdministradorPlataforma)
class AdministradorPlataformaAdmin(PlatformAdmin):
    list_display = ['user', 'active', 'created_by', 'created_at']
    list_filter = ['active']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at']

    def save_model(self, request, obj, form, change):
        obj.created_by_id = obj.created_by_id or request.user.pk
        super().save_model(request, obj, form, change)
        registrar(request.user, 'ACESSO_ADMIN_SAAS_ALTERADO', f'platform-admin:{obj.pk}',
                  details={'user_id': obj.user_id, 'active': obj.active, 'campos': form.changed_data})


@admin.register(PlanoSaaS)
class PlanoSaaSAdmin(PlatformAdmin):
    list_display = ['nome', 'slug', 'preco', 'periodicidade', 'ativo']
    list_filter = ['ativo', 'periodicidade']
    search_fields = ['nome', 'slug']


class SaaSReadOnlyAdmin(AuditAdmin):
    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)


for model in [AssinaturaSaaS, HistoricoPlanoSaaS, PrimeiroAcessoSaaS]:
    admin.site.register(model, SaaSReadOnlyAdmin)
admin.site.register(AuditoriaSaaS, SaaSReadOnlyAdmin)
