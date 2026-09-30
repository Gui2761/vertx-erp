"""Escopo SQL por padrão. Sem organização, nenhuma linha empresarial é visível."""
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import models
from .context import current_organization


class TenantQuerySet(models.QuerySet):
    def update(self, **kwargs):
        # Evita bypass das validações de FKs, organização e histórico.
        raise ValidationError('Atualização em lote não permitida para dados de tenant.')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('Atualização em lote não permitida para dados de tenant.')

    def bulk_create(self, *args, **kwargs):
        raise ValidationError('Use criação individual validada no contexto da organização.')


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    def get_queryset(self):
        qs = super().get_queryset()
        organization = current_organization()
        if organization is None or organization.status != 'ATIVA':
            return qs.none()
        return qs.filter(**{self.model.tenant_lookup: organization.pk})


def instance_organization_id(instance):
    path = instance.tenant_lookup.split('__')
    value = instance
    for name in path:
        value = getattr(value, name)
    return value.pk if hasattr(value, 'pk') else value


class TenantOwned(models.Model):
    objects = TenantManager()
    # Somente infraestrutura/migrações de dados e arquivos. Nunca usar em views.
    all_objects = models.Manager()
    tenant_lookup = 'organization_id'

    class Meta:
        abstract = True

    def validate_tenant(self):
        organization = current_organization()
        if organization is None or organization.status != 'ATIVA':
            raise PermissionDenied('Selecione uma organização ativa antes de operar.')
        direct = any(f.name == 'organization' for f in self._meta.fields)
        if direct and not self.organization_id:
            self.organization_id = organization.pk
        try:
            owner_id = instance_organization_id(self)
        except ObjectDoesNotExist:
            raise ValidationError('Vincule o registro ao seu cliente ou OS antes de salvar.')
        if owner_id != organization.pk:
            raise ValidationError('Registro pertence a outra organização.')
        if self.pk:
            old = type(self).all_objects.filter(pk=self.pk).first()
            if old is not None and instance_organization_id(old) != organization.pk:
                raise ValidationError('Não é permitido transferir registros entre organizações.')
        for field in self._meta.fields:
            if not field.is_relation or not field.many_to_one and not field.one_to_one:
                continue
            if getattr(self, field.attname) is None:
                continue
            related = getattr(self, field.name)
            if isinstance(related, TenantOwned) and instance_organization_id(related) != organization.pk:
                raise ValidationError({field.name: 'Vínculo com outra organização não permitido.'})
        if hasattr(self, 'conferencia_id') and self.conferencia_id and self.conferencia.ordem_id != self.ordem_id:
            raise ValidationError('Conferência deve pertencer à mesma OS.')
        if hasattr(self, 'localizacao_final_id') and self.localizacao_final_id and self.localizacao_final.ordem_id != self.ordem_id:
            raise ValidationError('Localização deve pertencer à mesma OS.')

    def clean(self):
        super().clean()
        self.validate_tenant()

    def save(self, *args, **kwargs):
        self.validate_tenant()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.validate_tenant()
        return super().delete(*args, **kwargs)


class OrganizationOwned(TenantOwned):
    organization = models.ForeignKey('platform_core.Organization', on_delete=models.PROTECT, editable=False)

    class Meta:
        abstract = True
