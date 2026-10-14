import hashlib
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


MODULES = frozenset({
    'assistencia', 'pdv', 'estoque', 'compras', 'financeiro', 'ponto',
    'rh', 'portal', 'contratos', 'fiscal', 'documentos',
})
LIMIT_KEYS = frozenset({'usuarios', 'filiais', 'armazenamento_mb', 'vendas_mes', 'ordens_mes'})


class AdministradorPlataforma(models.Model):
    """Explicit platform access; tenant ADMIN/superuser flags do not imply it."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='saas_platform_access')
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='saas_platform_grants')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'administrador da plataforma VERTYX'
        verbose_name_plural = 'administradores da plataforma VERTYX'

    def clean(self):
        if self.user_id and not self.user.is_active:
            raise ValidationError({'user': 'O usuário da plataforma precisa estar ativo.'})

    def delete(self, *args, **kwargs):
        raise ValidationError('Preserve o histórico; desative o acesso da plataforma.')


class PlanoSaaS(models.Model):
    class Period(models.TextChoices):
        MONTH = 'MENSAL', 'Mensal'
        YEAR = 'ANUAL', 'Anual'

    slug = models.SlugField(unique=True)
    nome = models.CharField(max_length=100)
    descricao = models.CharField(max_length=300, blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    periodicidade = models.CharField(max_length=8, choices=Period.choices, default=Period.MONTH)
    modulos = models.JSONField(default=list, blank=True)
    limites = models.JSONField(default=dict, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome', 'pk']
        verbose_name = 'plano SaaS'
        verbose_name_plural = 'planos SaaS'

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        if not isinstance(self.modulos, list) or any(not isinstance(code, str) or code not in MODULES for code in self.modulos) or len(set(self.modulos)) != len(self.modulos):
            raise ValidationError({'modulos': 'Selecione módulos válidos e sem duplicidade.'})
        if not isinstance(self.limites, dict):
            raise ValidationError({'limites': 'Limites devem ser um objeto.'})
        for key, value in self.limites.items():
            if key not in LIMIT_KEYS or value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValidationError({'limites': 'Use limites conhecidos como inteiros não negativos ou null para “A definir”.'})
        if self.limites.get('usuarios') == 0:
            raise ValidationError({'limites': 'O limite de usuários precisa comportar o administrador inicial.'})
        if self.preco is not None and self.preco < 0:
            raise ValidationError({'preco': 'Preço não pode ser negativo.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Planos não são excluídos; desative o plano para preservar o histórico.')


class AssinaturaSaaS(models.Model):
    class Status(models.TextChoices):
        IMPLANTACAO = 'IMPLANTACAO', 'Em implantação'
        ACTIVE = 'ATIVA', 'Ativa'
        SUSPENDED = 'SUSPENSA', 'Suspensa'

    organization = models.OneToOneField('platform_core.Organization', on_delete=models.PROTECT, related_name='assinatura_saas')
    plano = models.ForeignKey(PlanoSaaS, on_delete=models.PROTECT, related_name='assinaturas')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IMPLANTACAO)
    periodicidade = models.CharField(max_length=8, choices=PlanoSaaS.Period.choices, default=PlanoSaaS.Period.MONTH)
    inicio_em = models.DateTimeField(default=timezone.now)
    vencimento_em = models.DateField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'vínculo SaaS'
        verbose_name_plural = 'vínculos SaaS'

    def clean(self):
        if self.plano_id and not self.plano.ativo and not self.pk:
            raise ValidationError({'plano': 'Não é possível contratar um plano inativo.'})


class HistoricoPlanoSaaS(models.Model):
    assinatura = models.ForeignKey(AssinaturaSaaS, on_delete=models.PROTECT, related_name='historico_planos')
    plano_anterior = models.ForeignKey(PlanoSaaS, on_delete=models.PROTECT, null=True, blank=True, related_name='historico_anterior')
    plano_novo = models.ForeignKey(PlanoSaaS, on_delete=models.PROTECT, related_name='historico_novo')
    anterior = models.JSONField(default=dict)
    posterior = models.JSONField(default=dict)
    motivo = models.CharField(max_length=300, blank=True)
    alterado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Histórico de plano é imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Histórico de plano não pode ser apagado.')


class PrimeiroAcessoSaaS(models.Model):
    organization = models.ForeignKey('platform_core.Organization', on_delete=models.PROTECT, related_name='primeiros_acessos_saas')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='primeiros_acessos_saas')
    token_digest = models.CharField(max_length=64, unique=True)
    expira_em = models.DateTimeField()
    usado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def clean(self):
        if not re.fullmatch(r'[0-9a-f]{64}', self.token_digest or ''):
            raise ValidationError({'token_digest': 'Armazene somente o SHA-256 do token.'})
        if self.user_id and self.organization_id and not self.user.memberships.filter(organization_id=self.organization_id, role='ADMIN').exists():
            raise ValidationError({'user': 'O usuário deve ser ADMIN vinculado à organização do token.'})

    @staticmethod
    def digest(raw_token):
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


class AuditoriaSaaS(models.Model):
    organization = models.ForeignKey('platform_core.Organization', on_delete=models.PROTECT, null=True, blank=True, related_name='auditoria_saas')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='auditoria_saas')
    action = models.CharField(max_length=80)
    record = models.CharField(max_length=160)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        verbose_name = 'auditoria SaaS'
        verbose_name_plural = 'auditoria SaaS'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Auditoria SaaS é imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Auditoria SaaS não pode ser apagada.')
