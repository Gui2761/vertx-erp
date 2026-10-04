import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from decimal import Decimal
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
    AGENDADA = 'AGENDADA', 'Agendada'
    AG_PECA = 'AG_PECA', 'Aguardando peça'
    DESLOCAMENTO = 'DESLOCAMENTO', 'Em deslocamento'
    AG_APROVACAO = 'AG_APROVACAO', 'Aguardando aprovação'
    AG_CLIENTE = 'AG_CLIENTE', 'Aguardando cliente'
    APROVADA = 'APROVADA', 'Aprovada'
    FATURADA = 'FATURADA', 'Faturada'
    CANCELADA = 'CANCELADA', 'Cancelada'


class OrdemServico(OrganizationOwned):
    @property
    def custo_pecas(self):
        return sum(((-1 if movement.tipo == 'DEVOLUCAO' else 1) * movement.valor_custo for movement in self.movimentacoes_estoque.filter(tipo__in=['OS','DEVOLUCAO'])), Decimal('0'))

    objects = TenantManager.from_queryset(HistoricoQuerySet)()
    codigo = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    unidade = models.ForeignKey('clientes.Unidade', on_delete=models.PROTECT, null=True, blank=True)
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT, related_name='ordens')
    tecnico = models.ForeignKey('contas.Tecnico', on_delete=models.PROTECT, related_name='ordens', null=True, blank=True)
    auxiliares = models.ManyToManyField('contas.Tecnico', through='TecnicoAuxiliar', blank=True, related_name='ordens_auxiliares')
    modelo_checklist = models.ForeignKey('operacao.ModeloChecklist', on_delete=models.PROTECT, null=True, blank=True)
    tipo_atendimento = models.CharField(max_length=30, choices=[('CORRETIVA', 'Corretiva'), ('PREVENTIVA', 'Preventiva'), ('CALIBRACAO', 'Calibração'), ('INSTALACAO', 'Instalação'), ('INSPECAO', 'Inspeção'), ('VISITA', 'Visita técnica'), ('RETIRADA', 'Retirada'), ('ENTREGA', 'Entrega'), ('TREINAMENTO', 'Treinamento'), ('AVALIACAO', 'Avaliação/orçamento'), ('OUTRO', 'Outro')], default='CORRETIVA')
    contrato = models.ForeignKey('gestao.Contrato', on_delete=models.PROTECT, null=True, blank=True)
    prioridade = models.CharField(max_length=10, choices=[('BAIXA', 'Baixa'), ('NORMAL', 'Normal'), ('ALTA', 'Alta'), ('URGENTE', 'Urgente')], default='NORMAL', blank=True)
    agendada_para = models.DateTimeField(null=True, blank=True)
    agendada_ate = models.DateTimeField('Término previsto', null=True, blank=True)
    prazo = models.DateTimeField('Prazo de atendimento', null=True, blank=True)
    horas = models.DecimalField('Horas trabalhadas', max_digits=8, decimal_places=2, default=Decimal('0'), blank=True, validators=[MinValueValidator(Decimal('0'))])
    deslocamento_km = models.DecimalField('Deslocamento (km)', max_digits=9, decimal_places=2, default=Decimal('0'), blank=True, validators=[MinValueValidator(Decimal('0'))])
    checklist = models.JSONField(default=list, blank=True)
    numero_personalizado = models.CharField(max_length=40, blank=True, editable=False)
    defeito = models.TextField('Defeito / reclamação')
    diagnostico = models.TextField('Diagnóstico', blank=True)
    condicao_final = models.CharField('Condição final após atendimento', max_length=20, blank=True, choices=[('OK','Funcionando'),('RESTRICAO','Funcionando com restrição'),('INOPERANTE','Inoperante'),('NAO_TESTADO','Não testado')])
    pendencias_tecnicas = models.TextField('Pendências do atendimento', blank=True)
    causa_provavel = models.TextField('Causa provável', blank=True)
    solucao = models.TextField('Solução aplicada', blank=True)
    recomendacoes = models.TextField('Recomendações', blank=True)
    materiais = models.TextField('Materiais utilizados', blank=True)
    servico_executado = models.TextField('Serviço executado', blank=True)
    pecas = models.TextField('Peças utilizadas', blank=True, help_text='Descrição e quantidades; não movimenta estoque.')
    observacoes = models.TextField('Observações', blank=True)
    valor_cobranca = models.DecimalField('Valor a cobrar (R$)', max_digits=14, decimal_places=2, default=Decimal('0'), blank=True, validators=[MinValueValidator(Decimal('0'))], help_text='0: sem cobrança automática. Conta a receber gerada na finalização.')
    vencimento_cobranca = models.DateField('Vencimento da cobrança', null=True, blank=True)
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
        return self.numero_personalizado or (f'OS-{self.pk:06d}' if self.pk else 'Nova OS')

    def __str__(self):
        return self.numero

    def clean(self):
        super().clean()
        errors = {}
        if self.status == 'EXECUCAO' and not self.tecnico_id:
            errors['tecnico'] = 'Atendimento em execução exige técnico responsável.'
        if self.agendada_ate and (not self.agendada_para or self.agendada_ate <= self.agendada_para):
            errors['agendada_ate'] = 'Informe início e término previsto posterior ao início.'
        if self.equipamento_id:
            if self.equipamento.cliente_id != self.cliente_id:
                errors['equipamento'] = 'O equipamento deve pertencer ao cliente.'
            if self.equipamento.unidade_id != self.unidade_id:
                errors['unidade'] = 'Selecione a unidade cadastrada no equipamento (ou deixe vazio se ele não tem unidade).'
        if self.unidade_id and self.unidade.cliente_id != self.cliente_id:
            errors['unidade'] = 'A unidade deve pertencer ao cliente.'
        if errors:
            raise ValidationError(errors)
        from operacao.models import checklist_valido
        checklist_valido(self.checklist)
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if original.checklist and original.modelo_checklist_id != self.modelo_checklist_id:
                raise ValidationError({'modelo_checklist': 'O modelo copiado para a OS deve ser preservado; alterações pertencem a novas OS.'})
        if self.contrato_id and (self.contrato.cliente_id != self.cliente_id or not self.contrato.equipamentos.filter(pk=self.equipamento_id).exists()):
            raise ValidationError({'contrato': 'Equipamento deve estar coberto pelo contrato deste cliente.'})
        if self.pk and self.lancamentos.filter(tipo='RECEBER').exists():
            old = type(self).objects.get(pk=self.pk)
            if self.cliente_id != old.cliente_id or self.valor_cobranca != old.valor_cobranca:
                raise ValidationError('Cliente e valor da cobrança já lançada devem ser preservados.')

    def save(self, *args, **kwargs):
        self.validate_tenant()
        if self.pk and not getattr(self, '_transicao_autorizada', False):
            anterior = type(self).objects.get(pk=self.pk)
            if anterior.status in [Status.FINALIZADA, Status.APROVADA, Status.FATURADA, Status.CANCELADA]:
                raise ValidationError('OS finalizada é imutável. Use a reabertura auditada.')
            for campo in ('status', 'inicio', 'conclusao', 'ciclo'):
                if getattr(anterior, campo) != getattr(self, campo):
                    raise ValidationError('Use o fluxo de atendimento para alterar datas e status.')
        self.full_clean()
        new = self._state.adding
        result = super().save(*args, **kwargs)
        if new:
            from operacao.models import Configuracao
            config = Configuracao.objects.first()
            if config:
                self.numero_personalizado = f'{config.prefixo_os}-{self.pk:0{config.digitos_numero}d}'
                super().save(update_fields=['numero_personalizado'])
        return result

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
    categoria = models.CharField(max_length=15, blank=True, choices=[('ANTES', 'Antes'), ('DURANTE', 'Durante'), ('DEPOIS', 'Depois'), ('DEFEITO', 'Defeito'), ('IDENTIFICACAO', 'Identificação'), ('SERIE', 'Número de série'), ('PECA', 'Peça'), ('OUTROS', 'Outros')])
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
    imagem_tecnico = models.TextField(blank=True, editable=False)
    imagem_tecnico_sha256 = models.CharField(max_length=64, blank=True, editable=False)
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


class DocumentoOSAssinado(Imutavel):
    """Arquivo emitido uma única vez; hash e conteúdo preservados por assinatura."""
    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT)
    assinatura = models.OneToOneField(Assinatura, on_delete=models.PROTECT, related_name='documento_emitido')
    arquivo = models.FileField(storage=private_storage, upload_to='documentos-os', max_length=500)
    sha256 = models.CharField(max_length=64)
    emitido_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.assinatura.ordem_id != self.ordem_id:
            raise ValidationError('Documento fora da OS assinada.')


class TecnicoAuxiliar(OrganizationOwned):
    ordem = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name='vinculos_auxiliares')
    tecnico = models.ForeignKey('contas.Tecnico', on_delete=models.PROTECT)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['ordem', 'tecnico'], name='os_auxiliar_unico')]
    def clean(self):
        super().clean()
        if self.ordem.status in ['FINALIZADA', 'APROVADA', 'FATURADA', 'CANCELADA']:
            raise ValidationError('Equipe de OS encerrada é preservada.')
        if not self.tecnico.ativo or self.tecnico_id == self.ordem.tecnico_id:
            raise ValidationError('Selecione auxiliar ativo diferente do responsável.')
    def save(self, *args, **kwargs):
        self.validate_tenant()
        self.full_clean()
        return super().save(*args, **kwargs)
