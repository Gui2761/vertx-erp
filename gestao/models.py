from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from platform_core.tenancy import OrganizationOwned, TenantManager, TenantQuerySet

ZERO = Decimal('0')


class Validado(OrganizationOwned):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.validate_tenant()
        self.full_clean()
        return super().save(*args, **kwargs)


class SemExclusao(TenantQuerySet):
    def delete(self):
        raise ValidationError('Histórico não pode ser excluído.')


class RegistroImutavel(Validado):
    objects = TenantManager.from_queryset(SemExclusao)()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk or not getattr(self, '_service_write', False):
            raise ValidationError('Use o serviço transacional; histórico é imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Histórico não pode ser excluído.')


class Fornecedor(Validado):
    nome = models.CharField(max_length=150)
    documento = models.CharField(max_length=20, blank=True)
    contato = models.CharField(max_length=150, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Peca(Validado):
    sku = models.CharField('Código interno / SKU', max_length=60)
    descricao = models.CharField('Descrição', max_length=255)
    fabricante = models.CharField(max_length=150, blank=True)
    marca = models.CharField(max_length=100, blank=True)
    referencia = models.CharField('Modelo / referência', max_length=150, blank=True)
    categoria = models.ForeignKey('operacao.CategoriaPeca', on_delete=models.PROTECT, null=True, blank=True)
    estoque_maximo = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(ZERO)])
    ncm = models.CharField('NCM', max_length=8, blank=True)
    cfop = models.CharField('CFOP', max_length=4, blank=True)
    cst_csosn = models.CharField('CST/CSOSN', max_length=5, blank=True)
    unidade_medida = models.CharField('Unidade de medida', max_length=20, default='UN')
    quantidade_atual = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO, editable=False)
    estoque_minimo = models.DecimalField('Estoque mínimo', max_digits=14, decimal_places=3, default=ZERO, validators=[MinValueValidator(ZERO)])
    localizacao = models.CharField('Localização física', max_length=150, blank=True)
    custo_aquisicao = models.DecimalField('Custo de aquisição', max_digits=14, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    preco_venda = models.DecimalField('Preço de venda', max_digits=14, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT, null=True, blank=True)
    lote = models.CharField(max_length=100, blank=True)
    validade = models.DateField(null=True, blank=True)
    controla_validade = models.BooleanField('Exige validade nas entradas por lote', default=False)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['sku']
        constraints = [models.UniqueConstraint(fields=['organization', 'sku'], name='peca_sku_org'), models.CheckConstraint(check=models.Q(quantidade_atual__gte=0), name='peca_saldo_nao_negativo')]

    def __str__(self):
        return f'{self.sku} · {self.descricao}'

    @property
    def abaixo_minimo(self):
        return self.ativo and self.quantidade_atual <= self.estoque_minimo

    def save(self, *args, **kwargs):
        if not getattr(self, '_stock_write', False):
            old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            if self.quantidade_atual != (old.quantidade_atual if old else ZERO):
                raise ValidationError('Quantidade é alterada somente por movimentação de estoque.')
        return super().save(*args, **kwargs)


class Movimentacao(RegistroImutavel):
    detalhamento = models.JSONField(default=dict, blank=True, editable=False)
    class Tipo(models.TextChoices):
        ENTRADA = 'ENTRADA', 'Entrada'
        SAIDA = 'SAIDA', 'Saída'
        AJUSTE = 'AJUSTE', 'Ajuste de saldo'
        DEVOLUCAO = 'DEVOLUCAO', 'Devolução'
        OS = 'OS', 'Utilização em OS'
        TRANSFERENCIA = 'TRANSFER', 'Transferência entre depósitos'

    peca = models.ForeignKey(Peca, on_delete=models.PROTECT, related_name='movimentacoes')
    origem = models.ForeignKey('operacao.Deposito', on_delete=models.PROTECT, null=True, blank=True, related_name='movimentos_saida')
    destino = models.ForeignKey('operacao.Deposito', on_delete=models.PROTECT, null=True, blank=True, related_name='movimentos_entrada')
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(ZERO)])
    variacao = models.DecimalField(max_digits=14, decimal_places=3)
    saldo_apos = models.DecimalField(max_digits=14, decimal_places=3)
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    ordem = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, related_name='movimentacoes_estoque')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observacao = models.TextField('Observação', blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    request_id = models.UUIDField(editable=False)

    class Meta:
        ordering = ['-criado_em', '-pk']
        constraints = [models.CheckConstraint(check=models.Q(saldo_apos__gte=0), name='mov_saldo_nao_negativo'), models.UniqueConstraint(fields=['organization', 'request_id'], name='mov_request_org_unique')]

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.peca.sku} · {self.quantidade}'


class Orcamento(Validado):
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        ENVIADO = 'ENVIADO', 'Enviado'
        APROVADO = 'APROVADO', 'Aprovado'
        RECUSADO = 'RECUSADO', 'Recusado'
        VENCIDO = 'VENCIDO', 'Vencido'
        CONVERTIDO = 'CONVERTIDO', 'Convertido em OS'
        CANCELADO = 'CANCELADO', 'Cancelado'

    numero_personalizado = models.CharField(max_length=40, blank=True, editable=False)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    unidade = models.ForeignKey('clientes.Unidade', on_delete=models.PROTECT, null=True, blank=True)
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT, null=True, blank=True)
    ordem = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, related_name='orcamentos')
    ordem_convertida = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, related_name='orcamentos_convertidos', editable=False)
    data = models.DateField(default=timezone.localdate)
    validade = models.DateField()
    diagnostico = models.TextField('Diagnóstico', blank=True)
    servicos = models.TextField('Serviços previstos', blank=True)
    desconto = models.DecimalField('Desconto global (R$)', max_digits=14, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    deslocamento = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO, blank=True, validators=[MinValueValidator(ZERO)])
    impostos = models.DecimalField('Impostos informados (R$)', max_digits=14, decimal_places=2, default=ZERO, blank=True, validators=[MinValueValidator(ZERO)])
    observacoes = models.TextField('Observações', blank=True)
    condicoes_pagamento = models.TextField('Condições de pagamento', blank=True)
    prazo_execucao = models.CharField('Prazo de execução', max_length=150, blank=True)
    gerar_recebivel = models.BooleanField('Gerar conta a receber ao aprovar', default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RASCUNHO, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)

    class Meta:
        ordering = ['-data', '-pk']

    @property
    def numero(self):
        return self.numero_personalizado or (f'ORC-{self.pk:06d}' if self.pk else 'Novo orçamento')

    @property
    def subtotal(self):
        return sum((item.subtotal for item in self.itens.all()), ZERO) if self.pk else ZERO

    @property
    def total(self):
        return self.subtotal - self.desconto + self.deslocamento + self.impostos

    @property
    def situacao(self):
        if self.status in [self.Status.RASCUNHO, self.Status.ENVIADO] and self.validade < timezone.localdate():
            return self.Status.VENCIDO
        return self.status

    def __str__(self):
        return self.numero

    def clean(self):
        super().clean()
        if self.data and self.validade and self.validade < self.data:
            raise ValidationError({'validade': 'Validade não pode ser anterior à data.'})
        validar_cliente(self)
        if self.ordem_id and (self.ordem.cliente_id != self.cliente_id or self.ordem.equipamento_id != self.equipamento_id or self.ordem.unidade_id != self.unidade_id):
            raise ValidationError({'ordem': 'Cliente, unidade e equipamento devem coincidir com a OS.'})

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if not getattr(self, '_service_write', False) and (self.status != self.Status.RASCUNHO or old and old.status != self.Status.RASCUNHO):
            raise ValidationError('Orçamento enviado/aprovado não pode ser editado diretamente.')
        new = self._state.adding
        result = super().save(*args, **kwargs)
        if new:
            from operacao.models import Configuracao
            config = Configuracao.objects.first()
            if config:
                self.numero_personalizado = f'{config.prefixo_orcamento}-{self.pk:0{config.digitos_numero}d}'
                super().save(update_fields=['numero_personalizado'])
        return result


def validar_cliente(instance):
    if getattr(instance, 'unidade_id', None) and instance.unidade.cliente_id != instance.cliente_id:
        raise ValidationError({'unidade': 'A unidade deve pertencer ao cliente.'})
    if getattr(instance, 'equipamento_id', None):
        if instance.equipamento.cliente_id != instance.cliente_id:
            raise ValidationError({'equipamento': 'O equipamento deve pertencer ao cliente.'})
        if instance.equipamento.unidade_id != instance.unidade_id:
            raise ValidationError({'unidade': 'Use a unidade do equipamento.'})


class ItemOrcamento(Validado):
    orcamento = models.ForeignKey(Orcamento, on_delete=models.PROTECT, related_name='itens')
    tipo = models.CharField(max_length=10, choices=[('SERVICO', 'Serviço'), ('PECA', 'Peça')])
    peca = models.ForeignKey(Peca, on_delete=models.PROTECT, null=True, blank=True)
    descricao = models.CharField('Descrição', max_length=255)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    valor_unitario = models.DecimalField('Valor unitário', max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)])
    desconto = models.DecimalField('Desconto do item (R$)', max_digits=14, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])

    class Meta:
        ordering = ['pk']

    @property
    def subtotal(self):
        return (self.quantidade * self.valor_unitario).quantize(Decimal('0.01')) - self.desconto

    def clean(self):
        super().clean()
        if self.orcamento.status != Orcamento.Status.RASCUNHO:
            raise ValidationError('Itens só podem mudar em orçamento rascunho.')
        if self.peca_id and self.tipo != 'PECA':
            raise ValidationError({'peca': 'Selecione tipo Peça para vincular estoque.'})
        if self.quantidade is not None and self.valor_unitario is not None and self.desconto is not None and self.subtotal < 0:
            raise ValidationError({'desconto': 'Desconto excede o valor do item.'})

    def delete(self, *args, **kwargs):
        self.clean()
        return super().delete(*args, **kwargs)


class Contrato(Validado):
    numero = models.CharField('Número do contrato', max_length=60)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    unidades = models.ManyToManyField('clientes.Unidade', through='ContratoUnidade')
    equipamentos = models.ManyToManyField('equipamentos.Equipamento', through='ContratoEquipamento')
    data_inicial = models.DateField()
    data_final = models.DateField()
    valor = models.DecimalField('Valor por cobrança', max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)])
    periodicidade_cobranca = models.CharField('Periodicidade de cobrança', max_length=12, choices=[('UNICA', 'Única'), ('MENSAL', 'Mensal'), ('TRIMESTRAL', 'Trimestral'), ('SEMESTRAL', 'Semestral'), ('ANUAL', 'Anual')], default='MENSAL')
    tipo = models.CharField('Tipo de contrato', max_length=100, default='Manutenção')
    quantidade_visitas = models.PositiveIntegerField('Quantidade de visitas previstas', default=0, help_text='0: todas as visitas segundo a periodicidade. Cada visita abrange os equipamentos cobertos.')
    periodicidade_preventiva_meses = models.PositiveIntegerField('Periodicidade das preventivas (meses)', default=1, validators=[MinValueValidator(1)])
    sla_horas = models.PositiveIntegerField('SLA em horas', null=True, blank=True, validators=[MinValueValidator(1)])
    observacoes = models.TextField('Observações', blank=True)
    reajuste = models.CharField('Regra de reajuste', max_length=255, blank=True)
    cobertura_servicos = models.TextField('Cobertura de serviços', blank=True)
    cobertura_pecas = models.TextField('Cobertura de peças', blank=True)
    status = models.CharField(max_length=12, choices=[('ATIVO', 'Ativo'), ('PROXIMO', 'Próximo do vencimento'), ('VENCIDO', 'Vencido'), ('SUSPENSO', 'Suspenso'), ('ENCERRADO', 'Encerrado')], default='ATIVO')

    class Meta:
        ordering = ['data_final', 'numero']
        constraints = [models.UniqueConstraint(fields=['organization', 'numero'], name='contrato_numero_org'), models.CheckConstraint(check=models.Q(data_final__gte=models.F('data_inicial')), name='contrato_datas_validas')]

    def __str__(self):
        return self.numero

    @property
    def situacao(self):
        if self.status in ['SUSPENSO', 'ENCERRADO']:
            return self.status
        remaining = (self.data_final - timezone.localdate()).days
        return 'VENCIDO' if remaining < 0 else 'PROXIMO' if remaining <= 30 else 'ATIVO'

    def clean(self):
        super().clean()
        if self.data_inicial and self.data_final and self.data_final < self.data_inicial:
            raise ValidationError({'data_final': 'Data final deve ser posterior ou igual à inicial.'})
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if old and self.lancamentos.exists() and any(getattr(old, field) != getattr(self, field) for field in ['cliente_id', 'data_inicial', 'data_final', 'valor', 'periodicidade_cobranca']):
            raise ValidationError('Condições de cobrança já lançadas são preservadas. Encerre o contrato e cadastre a renovação.')


class ContratoUnidade(Validado):
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT)
    unidade = models.ForeignKey('clientes.Unidade', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['contrato', 'unidade'], name='contrato_unidade_unique')]

    def clean(self):
        super().clean()
        if self.unidade.cliente_id != self.contrato.cliente_id:
            raise ValidationError('Unidade deve pertencer ao cliente do contrato.')


class ContratoEquipamento(Validado):
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT)
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['contrato', 'equipamento'], name='contrato_equipamento_unique')]

    def clean(self):
        super().clean()
        if self.equipamento.cliente_id != self.contrato.cliente_id:
            raise ValidationError('Equipamento deve pertencer ao cliente do contrato.')
        units = list(self.contrato.unidades.values_list('pk', flat=True))
        if units and self.equipamento.unidade_id not in units:
            raise ValidationError('Equipamento fora das unidades cobertas pelo contrato.')


class AgendaPreventiva(Validado):
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name='agenda')
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT)
    data_prevista = models.DateField()
    tecnico = models.ForeignKey('contas.Tecnico', on_delete=models.PROTECT, null=True, blank=True)
    ordem = models.OneToOneField('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, related_name='agenda_contrato')
    cancelada = models.BooleanField(default=False)

    class Meta:
        ordering = ['data_prevista', 'pk']
        constraints = [models.UniqueConstraint(fields=['contrato', 'equipamento', 'data_prevista'], name='agenda_contrato_equip_data')]

    @property
    def situacao(self):
        if self.ordem_id and self.ordem.status in ['FINALIZADA','APROVADA','FATURADA']:
            return 'CONCLUIDA'
        if self.cancelada or self.contrato.status in ['SUSPENSO', 'ENCERRADO'] or self.ordem_id and self.ordem.status == 'CANCELADA':
            return 'CANCELADA'
        if self.ordem_id:
            return 'AGENDADA'
        return 'ATRASADA' if self.data_prevista < timezone.localdate() else 'PENDENTE'

    def clean(self):
        super().clean()
        if not self.contrato.equipamentos.filter(pk=self.equipamento_id).exists():
            raise ValidationError('Equipamento não está coberto por este contrato.')
        if not self.contrato.data_inicial <= self.data_prevista <= self.contrato.data_final:
            raise ValidationError('Preventiva deve ocorrer dentro do contrato.')
        if self.ordem_id and (self.ordem.equipamento_id != self.equipamento_id or self.ordem.tecnico_id != self.tecnico_id):
            raise ValidationError('OS e técnico devem coincidir com o planejamento.')


class CadastroFinanceiro(Validado):
    nome = models.CharField(max_length=100)
    ativo = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ['nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'nome'], name='%(class)s_nome_org')]

    def __str__(self):
        return self.nome


class CategoriaFinanceira(CadastroFinanceiro):
    pass


class CentroCusto(CadastroFinanceiro):
    pass


class FormaPagamento(CadastroFinanceiro):
    pass


class Lancamento(Validado):
    tipo = models.CharField(max_length=8, choices=[('RECEBER', 'Conta a receber / receita'), ('PAGAR', 'Conta a pagar / despesa')])
    descricao = models.CharField('Descrição', max_length=255)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, null=True, blank=True)
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT, null=True, blank=True)
    categoria = models.ForeignKey(CategoriaFinanceira, on_delete=models.PROTECT, null=True, blank=True)
    centro_custo = models.ForeignKey(CentroCusto, on_delete=models.PROTECT, null=True, blank=True)
    forma_pagamento = models.ForeignKey(FormaPagamento, on_delete=models.PROTECT, null=True, blank=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    data_emissao = models.DateField('Data de emissão', default=timezone.localdate)
    vencimento = models.DateField()
    status = models.CharField(max_length=10, choices=[('PENDENTE', 'Pendente'), ('LIQUIDADO', 'Pago / recebido'), ('VENCIDO', 'Vencido'), ('CANCELADO', 'Cancelado')], default='PENDENTE', editable=False)
    data_liquidacao = models.DateField(null=True, blank=True, editable=False)
    observacoes = models.TextField('Observações', blank=True)
    ordem = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, related_name='lancamentos', editable=False)
    orcamento = models.ForeignKey(Orcamento, on_delete=models.PROTECT, null=True, blank=True, related_name='lancamentos', editable=False)
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, null=True, blank=True, related_name='lancamentos', editable=False)
    competencia = models.DateField(null=True, blank=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)

    class Meta:
        ordering = ['vencimento', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'ordem'], condition=models.Q(ordem__isnull=False, tipo='RECEBER'), name='recebivel_os_unique'),
            models.UniqueConstraint(fields=['organization', 'orcamento'], condition=models.Q(orcamento__isnull=False, tipo='RECEBER'), name='recebivel_orcamento_unique'),
            models.UniqueConstraint(fields=['organization', 'contrato', 'competencia'], condition=models.Q(contrato__isnull=False, tipo='RECEBER'), name='recebivel_contrato_comp_unique'),
            models.CheckConstraint(check=models.Q(valor__gt=0), name='lancamento_valor_positivo'),
            models.CheckConstraint(check=(models.Q(status='LIQUIDADO', data_liquidacao__isnull=False) | (~models.Q(status='LIQUIDADO') & models.Q(data_liquidacao__isnull=True))), name='lancamento_liquidacao_coerente'),
        ]

    def __str__(self):
        return self.descricao

    @property
    def situacao(self):
        if self.status in ['LIQUIDADO', 'CANCELADO']:
            return self.status
        return 'VENCIDO' if self.vencimento < timezone.localdate() else 'PENDENTE'

    @property
    def saldo(self):
        if self.status in ['LIQUIDADO', 'CANCELADO']:
            return ZERO
        return self.valor - (self.pagamentos.aggregate(total=Sum('valor'))['total'] or ZERO)

    def clean(self):
        super().clean()
        if sum(bool(getattr(self, field + '_id')) for field in ['ordem', 'orcamento', 'contrato']) > 1:
            raise ValidationError('Um lançamento deve ter somente uma origem.')
        for origin in [self.ordem if self.ordem_id else None, self.orcamento if self.orcamento_id else None, self.contrato if self.contrato_id else None]:
            if origin and origin.cliente_id != self.cliente_id:
                raise ValidationError({'cliente': 'Cliente deve coincidir com a origem.'})

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if not getattr(self, '_service_write', False):
            if self.status != 'PENDENTE' or old and old.status != 'PENDENTE' or self.data_liquidacao:
                raise ValidationError('Use a operação financeira para liquidar/cancelar.')
            if old and (old.ordem_id or old.orcamento_id or old.contrato_id or self.pagamentos.exists() or hasattr(self, 'compra_origem') or hasattr(self, 'venda_origem')):
                frozen = ['tipo', 'descricao', 'cliente_id', 'fornecedor_id', 'valor', 'data_emissao', 'vencimento', 'ordem_id', 'orcamento_id', 'contrato_id', 'competencia', 'criado_por_id']
                if any(getattr(old, field) != getattr(self, field) for field in frozen):
                    raise ValidationError('Condições de lançamento automático são preservadas; apenas classificação e observações podem mudar.')
        return super().save(*args, **kwargs)


class EventoFinanceiro(RegistroImutavel):
    lancamento = models.ForeignKey(Lancamento, on_delete=models.PROTECT, related_name='eventos')
    tipo = models.CharField(max_length=12, choices=[('LIQUIDACAO', 'Liquidação'), ('CANCELAMENTO', 'Cancelamento')])
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    data = models.DateField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observacao = models.TextField('Observação', blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em', 'pk']
