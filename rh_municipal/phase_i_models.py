"""Phase I governance records. No legal compliance or risk score is inferred."""
import hashlib
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from ordens.storage import private_storage
from .models import Servidor, RegistroMunicipalImutavel
from .phase_f_models import PhaseFRecord

GOVERNANCE_MODULE = 'controle_interno'


def _scope_conflicts(record, related):
    return any(
        getattr(record, f'{field}_id', None) and getattr(related, f'{field}_id', None)
        and getattr(record, f'{field}_id') != getattr(related, f'{field}_id')
        for field in ('secretaria', 'departamento', 'setor', 'unidade')
    )


def governance_evidence_upload(instance, filename):
    parent = instance.achado or instance.plano.recomendacao.achado
    suffix = PurePosixPath(filename).suffix.lower()[:12]
    return f'organizations/{instance.organization.public_id}/gestao-publica/controle-interno/{parent.public_id}/{uuid.uuid4().hex}{suffix}'


class RiscoControleInterno(PhaseFRecord):
    class Status(models.TextChoices):
        IDENTIFICADO = 'IDENTIFICADO', 'Identificado'
        EM_TRATAMENTO = 'EM_TRATAMENTO', 'Em tratamento'
        MONITORADO = 'MONITORADO', 'Monitorado'
        ENCERRADO = 'ENCERRADO', 'Encerrado'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    codigo = models.CharField(max_length=36)
    titulo = models.CharField(max_length=180)
    descricao = models.TextField()
    categoria = models.CharField(max_length=80, blank=True)
    probabilidade = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    impacto = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDENTIFICADO)
    responsavel = models.ForeignKey(Servidor, null=True, blank=True, on_delete=models.PROTECT, related_name='riscos_governanca')
    prazo_revisao = models.DateField(null=True, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='riscos_controle_interno_criados')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'prazo_revisao', 'titulo']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_risco_org_codigo'),
            models.CheckConstraint(condition=Q(probabilidade__gte=1, probabilidade__lte=5), name='rhmun_risco_prob_1_5'),
            models.CheckConstraint(condition=Q(impacto__gte=1, impacto__lte=5), name='rhmun_risco_impacto_1_5'),
        ]

    def clean(self):
        super().clean()
        if self.responsavel_id and self.responsavel.organization_id != self.organization_id:
            raise ValidationError({'responsavel': 'O servidor responsável pertence a outra Prefeitura.'})


class ControleInternoMunicipal(PhaseFRecord):
    class Frequencia(models.TextChoices):
        CONTINUO = 'CONTINUO', 'Contínuo'
        DIARIO = 'DIARIO', 'Diário'
        MENSAL = 'MENSAL', 'Mensal'
        TRIMESTRAL = 'TRIMESTRAL', 'Trimestral'
        ANUAL = 'ANUAL', 'Anual'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    codigo = models.CharField(max_length=36)
    titulo = models.CharField(max_length=180)
    descricao = models.TextField()
    risco = models.ForeignKey(RiscoControleInterno, null=True, blank=True, on_delete=models.PROTECT, related_name='controles')
    responsavel = models.ForeignKey(Servidor, null=True, blank=True, on_delete=models.PROTECT, related_name='controles_governanca')
    frequencia = models.CharField(max_length=12, choices=Frequencia.choices, default=Frequencia.MENSAL)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='controles_controle_interno_criados')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['titulo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_controle_org_codigo')]

    def clean(self):
        super().clean()
        if self.risco_id and self.risco.organization_id != self.organization_id:
            raise ValidationError({'risco': 'O risco pertence a outra Prefeitura.'})
        if self.risco_id and _scope_conflicts(self, self.risco):
            raise ValidationError({'risco': 'O controle e o risco possuem escopos organizacionais incompatíveis.'})
        if self.responsavel_id and self.responsavel.organization_id != self.organization_id:
            raise ValidationError({'responsavel': 'O servidor responsável pertence a outra Prefeitura.'})


class AchadoControleInterno(PhaseFRecord):
    class Severidade(models.TextChoices):
        BAIXA = 'BAIXA', 'Baixa'
        MODERADA = 'MODERADA', 'Moderada'
        ALTA = 'ALTA', 'Alta'
        CRITICA = 'CRITICA', 'Crítica'

    class Status(models.TextChoices):
        ABERTO = 'ABERTO', 'Aberto'
        EM_ANALISE = 'EM_ANALISE', 'Em análise'
        COM_RECOMENDACAO = 'COM_RECOMENDACAO', 'Com recomendação'
        EM_ACAO = 'EM_ACAO', 'Em plano de ação'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'
        ENCERRADO = 'ENCERRADO', 'Encerrado'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    codigo = models.CharField(max_length=36)
    titulo = models.CharField(max_length=180)
    descricao = models.TextField()
    origem = models.CharField(max_length=100, blank=True)
    risco = models.ForeignKey(RiscoControleInterno, null=True, blank=True, on_delete=models.PROTECT, related_name='achados')
    controle = models.ForeignKey(ControleInternoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='achados')
    severidade = models.CharField(max_length=10, choices=Severidade.choices, default=Severidade.MODERADA)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABERTO)
    prazo = models.DateField(null=True, blank=True)
    responsavel = models.ForeignKey(Servidor, null=True, blank=True, on_delete=models.PROTECT, related_name='achados_governanca')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='achados_controle_interno_criados')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'prazo', '-criado_em']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_achado_org_codigo')]

    def clean(self):
        super().clean()
        for name in ('risco', 'controle', 'responsavel'):
            value = getattr(self, name, None)
            if value and value.organization_id != self.organization_id:
                raise ValidationError({name: 'O registro relacionado pertence a outra Prefeitura.'})
        for name in ('risco', 'controle'):
            related = getattr(self, name, None)
            if related and _scope_conflicts(self, related):
                raise ValidationError({name: 'O achado e o vínculo possuem escopos organizacionais incompatíveis.'})


class RecomendacaoControleInterno(PhaseFRecord):
    class Status(models.TextChoices):
        ABERTA = 'ABERTA', 'Aberta'
        ACEITA = 'ACEITA', 'Aceita'
        RECUSADA = 'RECUSADA', 'Recusada'
        EM_EXECUCAO = 'EM_EXECUCAO', 'Em execução'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    achado = models.ForeignKey(AchadoControleInterno, on_delete=models.PROTECT, related_name='recomendacoes')
    texto = models.TextField()
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.ABERTA)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criada_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.achado_id and self.achado.organization_id != self.organization_id:
            raise ValidationError({'achado': 'O achado pertence a outra Prefeitura.'})


class PlanoAcaoInterno(PhaseFRecord):
    class Status(models.TextChoices):
        PLANEJADO = 'PLANEJADO', 'Planejado'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        AGUARDANDO_VALIDACAO = 'AGUARDANDO_VALIDACAO', 'Aguardando validação'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'
        ATRASADO = 'ATRASADO', 'Atrasado'
        CANCELADO = 'CANCELADO', 'Cancelado'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    recomendacao = models.ForeignKey(RecomendacaoControleInterno, on_delete=models.PROTECT, related_name='planos')
    titulo = models.CharField(max_length=180)
    descricao = models.TextField()
    responsavel = models.ForeignKey(Servidor, null=True, blank=True, on_delete=models.PROTECT, related_name='planos_acao_controle_interno')
    prazo = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PLANEJADO)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='planos_acao_controle_interno_criados')
    criado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['status', 'prazo', 'titulo']

    def clean(self):
        super().clean()
        if self.recomendacao_id and self.recomendacao.organization_id != self.organization_id:
            raise ValidationError({'recomendacao': 'A recomendação pertence a outra Prefeitura.'})
        if self.responsavel_id and self.responsavel.organization_id != self.organization_id:
            raise ValidationError({'responsavel': 'O servidor responsável pertence a outra Prefeitura.'})
        if self.recomendacao_id and _scope_conflicts(self, self.recomendacao):
            raise ValidationError({'recomendacao': 'O plano de ação e a recomendação possuem escopos incompatíveis.'})


class AcaoPlanoAcaoInterno(PhaseFRecord):
    plano = models.ForeignKey(PlanoAcaoInterno, on_delete=models.PROTECT, related_name='historico')
    status_anterior = models.CharField(max_length=24, blank=True)
    status_novo = models.CharField(max_length=24)
    descricao = models.TextField(blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    registrado_em = models.DateTimeField(default=timezone.now, editable=False)

    def save(self, *args, **kwargs):
        if self.pk or not getattr(self, '_service_write', False):
            raise ValidationError('Use o serviço auditado; o histórico de ações é imutável.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Histórico de ações não pode ser excluído.')

    def clean(self):
        super().clean()
        if self.plano_id and self.plano.organization_id != self.organization_id:
            raise ValidationError({'plano': 'O plano pertence a outra Prefeitura.'})


class EvidenciaControleInterno(PhaseFRecord):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    achado = models.ForeignKey(AchadoControleInterno, null=True, blank=True, on_delete=models.PROTECT, related_name='evidencias')
    plano = models.ForeignKey(PlanoAcaoInterno, null=True, blank=True, on_delete=models.PROTECT, related_name='evidencias')
    titulo = models.CharField(max_length=180)
    arquivo = models.FileField(upload_to=governance_evidence_upload, storage=private_storage, max_length=500)
    nome_original = models.CharField(max_length=180)
    content_type = models.CharField(max_length=100, blank=True)
    tamanho_bytes = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    sha256 = models.CharField(max_length=64)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    enviado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-enviado_em']

    def clean(self):
        super().clean()
        if self.pk or not getattr(self, '_service_write', False):
            raise ValidationError('Use o serviço de anexação privada de evidências.')
        if bool(self.achado_id) == bool(self.plano_id):
            raise ValidationError('A evidência deve estar vinculada a exatamente um achado ou plano de ação.')
        for name in ('achado', 'plano'):
            parent = getattr(self, name, None)
            if parent and parent.organization_id != self.organization_id:
                raise ValidationError({name: 'O registro pertence a outra Prefeitura.'})
            if parent and _scope_conflicts(self, parent):
                raise ValidationError({name: 'A evidência e o registro relacionado possuem escopos incompatíveis.'})
        if self.sha256 and (len(self.sha256) != 64 or any(ch not in '0123456789abcdef' for ch in self.sha256.lower())):
            raise ValidationError({'sha256': 'Hash SHA-256 inválido.'})

    def delete(self, *args, **kwargs):
        raise ValidationError('Evidências de controle interno não podem ser excluídas.')


class EventoControleInterno(PhaseFRecord):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    acao = models.CharField(max_length=50)
    entidade = models.CharField(max_length=100)
    entidade_id = models.CharField(max_length=80)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    motivo = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    def save(self, *args, **kwargs):
        if self.pk or not getattr(self, '_service_write', False):
            raise ValidationError('Use o serviço auditado; o evento é imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Histórico de governança não pode ser excluído.')
