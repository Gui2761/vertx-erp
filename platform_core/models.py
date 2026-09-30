import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from .validators import normalize_cnpj, validate_cnpj, formatted_cnpj


class Organization(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ATIVA', 'Ativa'
        INACTIVE = 'INATIVA', 'Inativa'
        SUSPENDED = 'SUSPENSA', 'Suspensa'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    slug = models.SlugField(unique=True)
    razao_social = models.CharField('Razão social', max_length=255)
    nome_fantasia = models.CharField(max_length=150, blank=True)
    cnpj = models.CharField('CNPJ', max_length=14, blank=True, default='', validators=[validate_cnpj])
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Chave relativa do storage privado; futura personalização sem filesystem.path.
    logo_key = models.CharField('Chave da logomarca no storage privado', max_length=255, blank=True)
    document_details = models.TextField('Informações adicionais nos documentos', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['cnpj'], condition=~models.Q(cnpj=''), name='organization_cnpj_unique')]

    @property
    def display_name(self):
        return self.nome_fantasia or self.razao_social

    @property
    def cnpj_formatado(self):
        return formatted_cnpj(self.cnpj)

    def __str__(self):
        return self.display_name

    def clean(self):
        super().clean()
        self.cnpj = normalize_cnpj(self.cnpj)
        validate_cnpj(self.cnpj)
        if self.logo_key and (not self.logo_key.startswith(f'organizations/{self.public_id}/branding/') or '..' in self.logo_key.split('/') or '\\' in self.logo_key):
            raise ValidationError({'logo_key': 'A logomarca deve usar uma chave privada de branding desta organização.'})

    def save(self, *args, **kwargs):
        self.cnpj = normalize_cnpj(self.cnpj)
        self.full_clean()
        return super().save(*args, **kwargs)


class ERPCatalog(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class OrganizationERP(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='erp_accesses')
    erp = models.ForeignKey(ERPCatalog, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=True)
    enabled_at = models.DateTimeField(default=timezone.now)
    disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'erp'], name='organization_erp_unique')]


class OrganizationMembership(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ATIVO', 'Ativo'
        INACTIVE = 'INATIVO', 'Inativo'
        BLOCKED = 'BLOQUEADO', 'Bloqueado'

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='memberships')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    role = models.CharField(max_length=20, choices=[('ADMIN', 'Administrador da organização'), ('GESTOR', 'Gestor'), ('TECNICO', 'Técnico'), ('ESTOQUE', 'Estoquista'), ('FINANCEIRO', 'Financeiro'), ('CONTABILIDADE', 'Contabilidade')], default='TECNICO')
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'user'], name='organization_user_unique')]

    def __str__(self):
        return f'{self.user} · {self.organization} · {self.get_role_display()}'


class MembershipERP(models.Model):
    membership = models.ForeignKey(OrganizationMembership, on_delete=models.PROTECT, related_name='erp_accesses')
    erp = models.ForeignKey(ERPCatalog, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['membership', 'erp'], name='membership_erp_unique')]


class PlatformAudit(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    erp = models.ForeignKey(ERPCatalog, on_delete=models.PROTECT, null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    record = models.CharField(max_length=150)
    changes = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Auditoria da plataforma é imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Auditoria não pode ser excluída.')
