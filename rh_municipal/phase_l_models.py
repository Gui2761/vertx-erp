"""Phase L: tenant-scoped integration setup and non-sensitive attempt metadata.

No provider adapter is implemented here. Integrations remain disabled and no
network request is made. Payloads and responses are never stored in this phase;
only their SHA-256 digests may be retained for later reconciliation.
"""
import re
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .models import MunicipalRecord


INTEGRATION_MODULES = {
    'PNCP': 'compras_publicas',
    'TCE': 'contabilidade_pub',
    'SIAFIC': 'contabilidade_pub',
    'ESOCIAL': 'rh_municipal',
    'SUS': 'saude_sus',
    'ESUS': 'saude_sus',
    'CNES': 'saude_sus',
}


def _validate_endpoint(value):
    if not value:
        return
    parsed = urlsplit(value)
    if (parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValidationError('Use um endpoint HTTPS sem credenciais, parâmetros ou fragmento na URL.')
    if re.search(r'(?i)(?:token|secret|password|passwd|api[-_]?key|credential)', parsed.path):
        raise ValidationError('O caminho do endpoint parece conter credenciais; use somente uma URL base sem segredos.')


def _validate_secret_reference(value):
    if not value:
        return
    match = re.fullmatch(r'(?:cofre|vault)://([0-9a-fA-F-]{36})', value.strip())
    if not match:
        raise ValidationError('Informe apenas uma referência cofre://UUID ou vault://UUID; nunca um segredo.')
    try:
        uuid.UUID(match.group(1))
    except ValueError as exc:
        raise ValidationError('A referência do cofre deve conter um UUID válido.') from exc


class ConfiguracaoIntegracaoMunicipal(MunicipalRecord):
    class Provedor(models.TextChoices):
        PNCP = 'PNCP', 'PNCP'
        TCE = 'TCE', 'Tribunal de Contas (TCE)'
        SIAFIC = 'SIAFIC', 'SIAFIC'
        ESOCIAL = 'ESOCIAL', 'eSocial'
        SUS = 'SUS', 'Sistemas oficiais do SUS'
        ESUS = 'ESUS', 'e-SUS'
        CNES = 'CNES', 'CNES'

    class Ambiente(models.TextChoices):
        HOMOLOGACAO = 'HOMOLOGACAO', 'Homologação'
        PRODUCAO = 'PRODUCAO', 'Produção'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provedor = models.CharField(max_length=12, choices=Provedor.choices)
    nome = models.CharField(max_length=120)
    endpoint = models.URLField(max_length=500, blank=True)
    versao_api = models.CharField(max_length=60, blank=True)
    ambiente = models.CharField(max_length=14, choices=Ambiente.choices, default=Ambiente.HOMOLOGACAO)
    referencia_credencial = models.CharField(max_length=80, blank=True)
    habilitada = models.BooleanField(default=False, editable=False)
    criada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='integracoes_municipais_criadas')
    criada_em = models.DateTimeField(default=timezone.now, editable=False)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['provedor', 'nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'provedor', 'nome'], name='rhmun_integ_org_provider_name')]

    def clean(self):
        super().clean()
        _validate_endpoint(self.endpoint)
        _validate_secret_reference(self.referencia_credencial)
        if self.habilitada:
            raise ValidationError({'habilitada': 'As integrações permanecem desabilitadas até existir um adaptador oficial testado e autorizado.'})


class EventoIntegracaoMunicipal(MunicipalRecord):
    """Append-only audit trail; values must be redacted by the service layer."""
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    configuracao = models.ForeignKey(ConfiguracaoIntegracaoMunicipal, on_delete=models.PROTECT, related_name='eventos')
    acao = models.CharField(max_length=48)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    ator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='eventos_integracao_municipal')
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-criado_em', '-pk']

    def save(self, *args, **kwargs):
        if self.pk or not getattr(self, '_service_write', False):
            raise ValidationError('O histórico de integrações é imutável e só pode ser registrado pelo serviço autorizado.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('O histórico de integrações não pode ser excluído.')

    def clean(self):
        super().clean()
        if self.configuracao_id and self.configuracao.organization_id != self.organization_id:
            raise ValidationError({'configuracao': 'A configuração pertence a outra Prefeitura.'})


class TentativaIntegracaoMunicipal(MunicipalRecord):
    class Status(models.TextChoices):
        BLOQUEADA = 'BLOQUEADA', 'Bloqueada: adaptador oficial pendente'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    configuracao = models.ForeignKey(ConfiguracaoIntegracaoMunicipal, on_delete=models.PROTECT, related_name='tentativas')
    chave_idempotencia = models.CharField(max_length=128)
    digest_requisicao = models.CharField(max_length=64)
    digest_resposta = models.CharField(max_length=64, blank=True)
    protocolo_externo = models.CharField(max_length=160, blank=True)
    codigo_erro = models.CharField(max_length=48, default='ADAPTADOR_PENDENTE')
    mensagem_erro = models.CharField(max_length=240, default='Nenhuma transmissão foi realizada; adaptador oficial pendente.')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.BLOQUEADA)
    numero_tentativa = models.PositiveSmallIntegerField(default=1)
    solicitada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='tentativas_integracao_municipal')
    solicitada_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-solicitada_em', '-pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'chave_idempotencia'], name='rhmun_integ_org_idempotency')]

    def save(self, *args, **kwargs):
        if self.pk or not getattr(self, '_service_write', False):
            raise ValidationError('As tentativas são imutáveis e só podem ser registradas pelo serviço autorizado.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('As tentativas de integração não podem ser excluídas.')

    def clean(self):
        super().clean()
        if self.configuracao_id and self.configuracao.organization_id != self.organization_id:
            raise ValidationError({'configuracao': 'A configuração pertence a outra Prefeitura.'})
        if not re.fullmatch(r'[0-9a-f]{64}', self.digest_requisicao):
            raise ValidationError({'digest_requisicao': 'O digest SHA-256 da requisição está inválido.'})
        if self.digest_resposta and not re.fullmatch(r'[0-9a-f]{64}', self.digest_resposta):
            raise ValidationError({'digest_resposta': 'O digest SHA-256 da resposta está inválido.'})
