import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from .storage import private_storage
from platform_core.tenancy import OrganizationOwned, TenantOwned, TenantQuerySet, TenantManager


class HistoricoQuerySet(TenantQuerySet):
    def update(self, **kwargs):
        raise ValidationError('Use o fluxo auditado; atualização em lote não é permitida.')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('Use o fluxo auditado; atualização em lote não é permitida.')

    def delete(self):
        raise ValidationError('Ordens e históricos não podem ser excluídos.')


class Status(models.TextChoices):
    ABERTA = 'ABERTA', 'Aberta'
    EXECUCAO = 'EXECUCAO', 'Em atendimento'
    FINALIZADA = 'FINALIZADA', 'Finalizada'


class OrdemServico(OrganizationOwned):
    objects = TenantManager.from_queryset(HistoricoQuerySet)()
    codigo = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    unidade = models.ForeignKey('clientes.Unidade', on_delete=models.PROTECT, null=True, blank=True)
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT, related_name='ordens')
    tecnico = models.ForeignKey('contas.Tecnico', on_delete=models.PROTECT, related_name='ordens')
    tipo_atendimento = models.CharField(max_length=30, choices=[('CORRETIVA', 'Corretiva'), ('PREVENTIVA', 'Preventiva'), ('CALIBRACAO', 'Calibração'), ('OUTRO', 'Outro')], default='CORRETIVA')
    defeito = models.TextField('Defeito / reclamação')
    diagnostico = models.TextField('Diagnóstico', blank=True)
    servico_executado = models.TextField('Serviço executado', blank=True)
    pecas = models.TextField('Peças utilizadas', blank=True, help_text='Descrição e quantidades; não movimenta estoque.')
    observacoes = models.TextField('Observações', blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ABERTA)
    abertura = models.DateTimeField(auto_now_add=True)
    inicio = models.DateTimeField(null=True, blank=True)
    conclusao = models.DateTimeField(null=True, blank=True)
    revisao = models.PositiveIntegerField(default=1)
    ciclo = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-abertura', '-pk']
        verbose_name = 'Ordem de Serviço'
        verbose_name_plural = 'Ordens de Serviço'
        indexes = [models.Index(fields=['organization', 'status', '-abertura'], name='os_org_status_abertura')]

    @property
    def numero(self):
        return f'OS-{self.pk:06d}' if self.pk else 'Nova OS'

    def __str__(self):
        return self.numero

    def clean(self):
        super().clean()
        errors = {}
        if self.equipamento_id:
            if self.equipamento.cliente_id != self.cliente_id:
                errors['equipamento'] = 'O equipamento deve pertencer ao cliente.'
            if self.equipamento.unidade_id != self.unidade_id:
                errors['unidade'] = 'Selecione a unidade cadastrada no equipamento (ou deixe vazio se ele não tem unidade).'
        if self.unidade_id and self.unidade.cliente_id != self.cliente_id:
            errors['unidade'] = 'A unidade deve pertencer ao cliente.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.validate_tenant()
        if self.pk and not getattr(self, '_transicao_autorizada', False):
            anterior = type(self).objects.get(pk=self.pk)
            if anterior.status == Status.FINALIZADA:
                raise ValidationError('OS finalizada é imutável. Use a reabertura auditada.')
            for campo in ('status', 'inicio', 'conclusao', 'ciclo'):
                if getattr(anterior, campo) != getattr(self, campo):
                    raise ValidationError('Use o fluxo de atendimento para alterar datas e status.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Ordens de Serviço não podem ser excluídas.')


class Imutavel(TenantOwned):
    objects = TenantManager.from_queryset(HistoricoQuerySet)()
    tenant_lookup = 'ordem__organization_id'
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Registro histórico imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Registro histórico não pode ser excluído.')


class Localizacao(Imutavel):
    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name='localizacoes')
    ciclo = models.PositiveIntegerField()
    evento = models.CharField(max_length=10, choices=[('INICIO', 'Início'), ('FINAL', 'Finalização')])
    resultado = models.CharField(max_length=20, choices=[('OBTIDA', 'Obtida'), ('NEGADA', 'Permissão negada'), ('INDISPONIVEL', 'Indisponível'), ('TIMEOUT', 'Tempo esgotado'), ('NAO_SUPORTADA', 'Não suportada')])
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=7, null=True)
    precisao = models.FloatField(null=True)
    registrado_em = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(check=(models.Q(resultado='OBTIDA', latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180, latitude__isnull=False, longitude__isnull=False) | (~models.Q(resultado='OBTIDA') & models.Q(latitude__isnull=True, longitude__isnull=True, precisao__isnull=True))), name='geo_resultado_coerente'),
            models.CheckConstraint(check=models.Q(precisao__isnull=True) | models.Q(precisao__gte=0), name='geo_precisao_positiva'),
            models.UniqueConstraint(fields=['ordem', 'ciclo', 'evento'], condition=models.Q(evento='INICIO'), name='geo_inicio_unico_ciclo'),
        ]

    @property
    def mapa_url(self):
        if self.resultado == 'OBTIDA':
            return f'https://www.google.com/maps/search/?api=1&query={self.latitude}%2C{self.longitude}'
        return ''


def foto_path(instance, filename):
    return f'organizations/{instance.ordem.organization.public_id}/assistencia/ordens/{instance.ordem.codigo}/fotos/{uuid.uuid4().hex}.jpg'


class Foto(Imutavel):
    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name='fotos')
    arquivo = models.ImageField(upload_to=foto_path, storage=private_storage, max_length=500)
    descricao = models.CharField('Descrição', max_length=255, blank=True)
    sha256 = models.CharField(max_length=64)
    criado_em = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class Conferencia(Imutavel):
    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name='conferencias')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revisao = models.PositiveIntegerField()
    ciclo = models.PositiveIntegerField()
    dados = models.JSONField()
    digest = models.CharField(max_length=64)
    localizacao_final = models.OneToOneField(Localizacao, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)
    issuer = models.JSONField(default=dict, blank=True)  # Emissor de documentos anteriores à VERTYX, sem alterar snapshot/digest.


class Assinatura(Imutavel):
    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name='assinaturas')
    conferencia = models.OneToOneField(Conferencia, on_delete=models.PROTECT)
    ciclo = models.PositiveIntegerField()
    nome = models.CharField('Nome completo', max_length=150)
    cargo = models.CharField('Cargo / função', max_length=100)
    imagem = models.TextField()  # PNG validado, codificado em base64; acesso autenticado.
    imagem_sha256 = models.CharField(max_length=64)
    assinado_em = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['ordem', 'ciclo'], name='assinatura_unica_ciclo')]


class Auditoria(Imutavel):
    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name='historico')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    data = models.DateTimeField(auto_now_add=True)
    acao = models.CharField(max_length=50)
    alteracoes = models.JSONField(default=dict)
    justificativa = models.TextField(blank=True)

    class Meta:
        ordering = ['data', 'pk']

    @property
    def organization(self):
        return self.ordem.organization

    @property
    def erp_code(self):
        return 'assistencia'
