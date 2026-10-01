"""Complementos do ERP; identidade, estoque e financeiro permanecem nos apps existentes."""
import uuid
from datetime import time
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum, Q
from django.utils import timezone
from gestao.models import Validado, RegistroImutavel, ZERO

PRIORIDADES = [('BAIXA', 'Baixa'), ('NORMAL', 'Normal'), ('ALTA', 'Alta'), ('URGENTE', 'Urgente')]
ENCERRADAS = ['FINALIZADA', 'APROVADA', 'FATURADA', 'CANCELADA']

def dias_alerta_padrao():
    return [90, 60, 30, 15, 7]

def validar_dias_alerta(value):
    if not isinstance(value, list) or not value or len(value) > 12 or any(type(day) is not int or not 1 <= day <= 365 for day in value) or len(set(value)) != len(value):
        raise ValidationError('Informe uma lista de dias distintos entre 1 e 365.')

def privado(instance, filename):
    from pathlib import PurePosixPath
    suffix = PurePosixPath(filename).suffix.lower()
    return f'organizations/{instance.organization.public_id}/assistencia/documentos/{uuid.uuid4().hex}{suffix}'

def checklist_valido(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValidationError('Checklist deve ser lista de até 100 itens.')
    for row in value:
        if not isinstance(row, dict) or set(row) - {'item', 'obrigatorio', 'concluido', 'observacao'} or not isinstance(row.get('item'), str) or not row['item'].strip() or len(row['item']) > 255:
            raise ValidationError('Cada item precisa de descrição; use item, obrigatorio, concluido e observacao.')
        if any(key in row and not isinstance(row[key], bool) for key in ['obrigatorio', 'concluido']) or len(str(row.get('observacao', ''))) > 1000:
            raise ValidationError('Resposta de checklist inválida.')

class Nomeado(Validado):
    nome = models.CharField(max_length=150)
    ativo = models.BooleanField(default=True)
    class Meta:
        abstract = True
        ordering = ['nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'nome'], name='%(class)s_nome_organizacao')]
    def __str__(self):
        return self.nome

BLOCOS_PAINEL = [('indicadores','Indicadores'),('agora','Atividades agora'),('equipe','Equipe'),('timeline','Linha do tempo'),('fila','Fila de espera'),('concluidas','Concluídas hoje'),('preventivas','Preventivas'),('alertas','Alertas')]

def blocos_painel_padrao():
    return [key for key, label in BLOCOS_PAINEL]

def validar_blocos_painel(value):
    if not isinstance(value,list) or not value or any(not isinstance(key,str) for key in value) or len(value)!=len(set(value)) or any(key not in dict(BLOCOS_PAINEL) for key in value):
        raise ValidationError('Escolha blocos válidos, sem duplicação.')

class Configuracao(Validado):
    painel_intervalo = models.PositiveSmallIntegerField(default=30, choices=[(15, '15 segundos'), (30, '30 segundos'), (60, '60 segundos')])
    painel_tema = models.CharField(max_length=8, default='ESCURO', choices=[('ESCURO', 'Escuro'), ('CLARO', 'Claro')])
    painel_blocos = models.JSONField(default=blocos_painel_padrao, validators=[validar_blocos_painel])
    estoque_minimo_padrao = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO, validators=[MinValueValidator(ZERO)])
    estoque_ideal_padrao = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO, validators=[MinValueValidator(ZERO)])
    intervalo_alertas_minutos = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    dias_alerta_validade = models.JSONField(default=dias_alerta_padrao, validators=[validar_dias_alerta])
    relatorio_semanal_ativo = models.BooleanField(default=True)
    relatorio_dia_semana = models.PositiveSmallIntegerField(default=0, choices=[(0,'Segunda'),(1,'Terça'),(2,'Quarta'),(3,'Quinta'),(4,'Sexta'),(5,'Sábado'),(6,'Domingo')])
    relatorio_horario = models.TimeField(default=time(8, 0))
    consumo_historico_dias = models.PositiveSmallIntegerField(default=90, validators=[MinValueValidator(30), MaxValueValidator(365)])
    reposicao_dias = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(1), MaxValueValidator(365)])
    ultima_verificacao_estoque = models.DateTimeField(null=True, blank=True, editable=False)
    endereco = models.TextField('Endereço completo', blank=True)
    prefixo_os = models.CharField(max_length=12, default='OS')
    prefixo_orcamento = models.CharField(max_length=12, default='ORC')
    prefixo_contrato = models.CharField(max_length=12, default='CT')
    digitos_numero = models.PositiveSmallIntegerField(default=6, validators=[MinValueValidator(3), MaxValueValidator(12)])
    prazo_financeiro_dias = models.PositiveSmallIntegerField(default=30)
    juros_mensal_percentual = models.DecimalField(max_digits=6, decimal_places=3, default=ZERO, validators=[MinValueValidator(ZERO)])
    multa_percentual = models.DecimalField(max_digits=6, decimal_places=3, default=ZERO, validators=[MinValueValidator(ZERO)])
    municipio_fiscal = models.CharField('Código do município fiscal', max_length=10, blank=True)
    codigo_servico = models.CharField(max_length=30, blank=True)
    ambiente_fiscal = models.CharField(max_length=10, choices=[('SANDBOX', 'Sandbox'), ('PRODUCAO', 'Produção')], default='SANDBOX')
    provedor_fiscal = models.CharField(max_length=100, blank=True, help_text='Nome do adaptador aprovado; segredos ficam no ambiente.')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization'], name='configuracao_org_unica')]
    def __str__(self):
        return 'Configuração da organização'
    def clean(self):
        super().clean()
        import re
        for field in ['prefixo_os','prefixo_orcamento','prefixo_contrato']:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,12}', getattr(self,field)):
                raise ValidationError({field:'Use apenas letras, números, hífen e sublinhado.'})

class Deposito(Nomeado):
    endereco = models.CharField(max_length=255, blank=True)

class SaldoDeposito(Validado):
    deposito = models.ForeignKey(Deposito, on_delete=models.PROTECT)
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['deposito', 'peca'], name='saldo_deposito_peca'), models.CheckConstraint(check=Q(quantidade__gte=0), name='saldo_deposito_positivo')]
    def save(self, *args, **kwargs):
        if not getattr(self, '_service_write', False):
            raise ValidationError('Saldo por depósito exige serviço transacional.')
        return super().save(*args, **kwargs)

class CategoriaPeca(Nomeado):
    pass

class Chamado(Validado):
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    unidade = models.ForeignKey('clientes.Unidade', on_delete=models.PROTECT, null=True, blank=True)
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT, null=True, blank=True)
    contrato = models.ForeignKey('gestao.Contrato', on_delete=models.PROTECT, null=True, blank=True)
    titulo = models.CharField('Título', max_length=180)
    descricao = models.TextField('Descrição')
    prioridade = models.CharField(max_length=10, choices=PRIORIDADES, default='NORMAL')
    status = models.CharField(max_length=12, choices=[('ABERTO', 'Aberto'), ('CONVERTIDO', 'Convertido em OS'), ('CANCELADO', 'Cancelado')], default='ABERTO', editable=False)
    ordem = models.OneToOneField('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-criado_em']
    def __str__(self):
        return f'CH-{self.pk:06d} · {self.titulo}' if self.pk else 'Novo chamado'
    def clean(self):
        super().clean()
        from gestao.models import validar_cliente
        validar_cliente(self)
        if self.contrato_id and self.contrato.cliente_id != self.cliente_id:
            raise ValidationError({'contrato': 'Contrato pertence a outro cliente.'})

class ModeloChecklist(Nomeado):
    itens = models.JSONField(default=list, validators=[checklist_valido], help_text='Lista JSON: [{"item":"Inspeção","obrigatorio":true}].')

class PlanoPreventivo(Nomeado):
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    contrato = models.ForeignKey('gestao.Contrato', on_delete=models.PROTECT, null=True, blank=True)
    equipamentos = models.ManyToManyField('equipamentos.Equipamento', through='PlanoEquipamento')
    checklist = models.ForeignKey(ModeloChecklist, on_delete=models.PROTECT, null=True, blank=True)
    tecnico = models.ForeignKey('contas.Tecnico', on_delete=models.PROTECT, null=True, blank=True)
    periodicidade = models.CharField(max_length=15, choices=[('DIARIO', 'Diário'), ('SEMANAL', 'Semanal'), ('QUINZENAL', 'Quinzenal'), ('MENSAL', 'Mensal'), ('BIMESTRAL', 'Bimestral'), ('TRIMESTRAL', 'Trimestral'), ('SEMESTRAL', 'Semestral'), ('ANUAL', 'Anual'), ('PERSONALIZADA', 'Personalizada')], default='MENSAL')
    intervalo_dias = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    inicio = models.DateField(default=timezone.localdate)
    fim = models.DateField()
    ultima_execucao = models.DateField(null=True, blank=True, editable=False)
    observacoes = models.TextField(blank=True)
    def clean(self):
        super().clean()
        if self.inicio and self.fim and self.fim < self.inicio:
            raise ValidationError({'fim': 'Fim anterior ao início.'})
        if self.periodicidade == 'PERSONALIZADA' and not self.intervalo_dias:
            raise ValidationError({'intervalo_dias': 'Informe o intervalo personalizado.'})
        if self.contrato_id and (self.contrato.cliente_id != self.cliente_id or not self.contrato.data_inicial <= self.inicio <= self.fim <= self.contrato.data_final):
            raise ValidationError({'contrato': 'Cliente/vigência devem estar dentro do contrato.'})
        if self.pk and self.ocorrencias.exists():
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, field) != getattr(self, field) for field in ['cliente_id', 'contrato_id', 'inicio', 'fim', 'periodicidade', 'intervalo_dias']):
                raise ValidationError('Plano já gerado preserva cliente/vigência/periodicidade; desative e crie outro.')
    @property
    def proxima_execucao(self):
        if not self.ativo:
            return None
        item = self.ocorrencias.filter(cancelada=False).exclude(ordem__status__in=ENCERRADAS).order_by('data').first()
        return item.data if item else None

class PlanoEquipamento(Validado):
    plano = models.ForeignKey(PlanoPreventivo, on_delete=models.PROTECT)
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['plano', 'equipamento'], name='plano_equipamento_unico')]
    def clean(self):
        super().clean()
        if self.equipamento.cliente_id != self.plano.cliente_id or self.plano.contrato_id and not self.plano.contrato.equipamentos.filter(pk=self.equipamento_id).exists():
            raise ValidationError('Equipamento fora da cobertura do plano/contrato.')

class PreventivaProgramada(Validado):
    plano = models.ForeignKey(PlanoPreventivo, on_delete=models.PROTECT, related_name='ocorrencias')
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT)
    data = models.DateField()
    ordem = models.OneToOneField('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, editable=False)
    cancelada = models.BooleanField(default=False)
    class Meta:
        ordering = ['data', 'pk']
        constraints = [models.UniqueConstraint(fields=['plano', 'equipamento', 'data'], name='preventiva_plano_equip_data')]
    def __str__(self):
        return f'{self.equipamento.nome} · {self.data}'
    @property
    def situacao(self):
        if self.ordem_id and self.ordem.status in ['FINALIZADA', 'APROVADA', 'FATURADA']:
            return 'CONCLUIDA'
        if self.cancelada or not self.plano.ativo or self.ordem_id and self.ordem.status == 'CANCELADA':
            return 'CANCELADA'
        return 'AGENDADA' if self.ordem_id else 'ATRASADA' if self.data < timezone.localdate() else 'PENDENTE'
    def clean(self):
        super().clean()
        if not self.plano.equipamentos.filter(pk=self.equipamento_id).exists() or not self.plano.inicio <= self.data <= self.plano.fim:
            raise ValidationError('Equipamento/data fora do plano.')

class Fluxo(Validado):
    status = models.CharField(max_length=15, default='RASCUNHO', editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    observacoes = models.TextField(blank=True)
    class Meta:
        abstract = True
        ordering = ['-criado_em']
    def save(self, *args, **kwargs):
        if not getattr(self, '_service_write', False):
            old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            if self.status != 'RASCUNHO' or old and old.status != 'RASCUNHO':
                raise ValidationError('Registro fora de rascunho exige serviço transacional.')
        return super().save(*args, **kwargs)
    @property
    def total(self):
        return sum((row.total for row in self.itens.all()), ZERO) if self.pk else ZERO
    def get_status_display(self):
        return {'RASCUNHO':'Rascunho','APROVADA':'Aprovada','PEDIDO':'Pedido','RECEBIDA':'Recebida','CONFIRMADA':'Confirmada','CANCELADA':'Cancelada'}.get(self.status,self.status)

class Compra(Fluxo):
    relatorio_estoque = models.ForeignKey('RelatorioEstoque', on_delete=models.PROTECT, null=True, blank=True, editable=False)
    pedido_relatorio_id = models.UUIDField(null=True, blank=True, editable=False)
    selecao_relatorio = models.JSONField(default=dict, blank=True, editable=False)
    fornecedor = models.ForeignKey('gestao.Fornecedor', on_delete=models.PROTECT, null=True, blank=True)
    deposito = models.ForeignKey(Deposito, on_delete=models.PROTECT)
    necessidade = models.TextField('Motivo da solicitação')
    vencimento = models.DateField()
    conta = models.OneToOneField('gestao.Lancamento', on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name='compra_origem')
    def __str__(self):
        return f'COMP-{self.pk:06d}' if self.pk else 'Nova compra'
    class Meta(Fluxo.Meta):
        constraints = [models.UniqueConstraint(fields=['organization','pedido_relatorio_id'],condition=Q(pedido_relatorio_id__isnull=False),name='compra_relatorio_request_unico')]

class ItemCompra(Validado):
    lote = models.CharField(max_length=100, blank=True)
    fabricacao = models.DateField(null=True, blank=True)
    validade = models.DateField(null=True, blank=True)
    documento_entrada = models.CharField(max_length=180, blank=True)
    relatorio_item = models.ForeignKey('ItemRelatorioEstoque', on_delete=models.PROTECT, null=True, blank=True, editable=False)
    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name='itens')
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal('.001'))])
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)])
    @property
    def total(self):
        return (self.quantidade * self.custo_unitario).quantize(Decimal('.01'))
    def clean(self):
        super().clean()
        if Compra.objects.get(pk=self.compra_id).status != 'RASCUNHO' and not getattr(self, '_receiving_write', False):
            raise ValidationError('Itens somente em solicitação rascunho.')
        if getattr(self, '_receiving_write', False):
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, field) != getattr(self, field) for field in ['compra_id','peca_id','quantidade','custo_unitario','relatorio_item_id']):
                raise ValidationError('Recebimento preserva produto, quantidade e custo aprovados.')
        if self.fabricacao and self.validade and self.fabricacao > self.validade:
            raise ValidationError('Fabricação posterior à validade.')

class CotacaoCompra(Validado):
    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name='cotacoes')
    fornecedor = models.ForeignKey('gestao.Fornecedor', on_delete=models.PROTECT)
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    validade = models.DateField()
    prazo = models.CharField(max_length=100, blank=True)
    observacoes = models.TextField(blank=True)
    def __str__(self):
        return f'{self.fornecedor} · R$ {self.valor}'
    def clean(self):
        super().clean()
        if Compra.objects.get(pk=self.compra_id).status != 'RASCUNHO':
            raise ValidationError('Cotação exige compra em rascunho.')

class Venda(Fluxo):
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='vendas')
    deposito = models.ForeignKey(Deposito, on_delete=models.PROTECT)
    vencimento = models.DateField()
    conta = models.OneToOneField('gestao.Lancamento', on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name='venda_origem')
    def __str__(self):
        return f'VENDA-{self.pk:06d}' if self.pk else 'Nova venda'
    def clean(self):
        super().clean()
        if self.vendedor_id and not self.vendedor.memberships.filter(organization=self.organization, status='ATIVO').exists():
            raise ValidationError({'vendedor': 'Vendedor precisa de vínculo ativo na organização.'})

class ItemVenda(Validado):
    venda = models.ForeignKey(Venda, on_delete=models.PROTECT, related_name='itens')
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal('.001'))])
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)])
    desconto = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO, editable=False)
    @property
    def total(self):
        return (self.quantidade * self.valor_unitario).quantize(Decimal('.01')) - self.desconto
    @property
    def margem(self):
        return self.total - (self.quantidade * self.custo_unitario).quantize(Decimal('.01'))
    def clean(self):
        super().clean()
        if Venda.objects.get(pk=self.venda_id).status != 'RASCUNHO':
            raise ValidationError('Itens somente em venda rascunho.')
        if self.quantidade is not None and self.valor_unitario is not None and self.desconto is not None and self.total < 0:
            raise ValidationError({'desconto': 'Desconto excede o valor do item.'})

class ContaBancaria(Nomeado):
    banco = models.CharField(max_length=100, blank=True)
    agencia = models.CharField(max_length=30, blank=True)
    numero = models.CharField(max_length=40, blank=True)
    tipo = models.CharField(max_length=10, choices=[('BANCO', 'Banco'), ('CAIXA', 'Caixa'), ('CARTAO', 'Cartão')], default='BANCO')
    saldo_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    permite_saldo_negativo = models.BooleanField(default=False)
    @property
    def saldo(self):
        amounts = self.movimentos.aggregate(entrada=Sum('valor', filter=Q(tipo='ENTRADA')), saida=Sum('valor', filter=Q(tipo='SAIDA')))
        return self.saldo_inicial + (amounts['entrada'] or ZERO) - (amounts['saida'] or ZERO)
    def clean(self):
        super().clean()
        if self.pk and self.movimentos.exists() and type(self).objects.get(pk=self.pk).saldo_inicial != self.saldo_inicial:
            raise ValidationError({'saldo_inicial': 'Saldo de abertura já movimentado é preservado.'})

class MovimentoCaixa(RegistroImutavel):
    conta = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, related_name='movimentos')
    tipo = models.CharField(max_length=7, choices=[('ENTRADA', 'Entrada'), ('SAIDA', 'Saída')])
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    data = models.DateField(default=timezone.localdate)
    descricao = models.CharField(max_length=255)
    referencia = models.UUIDField(default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    class Meta:
        ordering = ['-data', '-pk']
        constraints = [models.UniqueConstraint(fields=['conta', 'referencia'], name='movimento_caixa_referencia')]

class Pagamento(RegistroImutavel):
    lancamento = models.ForeignKey('gestao.Lancamento', on_delete=models.PROTECT, related_name='pagamentos')
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    data = models.DateField()
    conta = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, null=True, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observacoes = models.TextField(blank=True)
    request_id = models.UUIDField(default=uuid.uuid4, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'request_id'], name='pagamento_request_org')]

class Parcela(Validado):
    origem = models.ForeignKey('gestao.Lancamento', on_delete=models.PROTECT, related_name='parcelas')
    lancamento = models.OneToOneField('gestao.Lancamento', on_delete=models.PROTECT, related_name='parcela_origem')
    numero = models.PositiveIntegerField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['origem', 'numero'], name='parcela_origem_numero')]

class ExtratoBancario(Validado):
    conta = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT)
    identificador = models.CharField('Identificador externo do extrato', max_length=150)
    data = models.DateField()
    valor = models.DecimalField('Valor assinado: entrada + / saída -', max_digits=14, decimal_places=2)
    descricao = models.CharField(max_length=255)
    movimento = models.OneToOneField(MovimentoCaixa, on_delete=models.PROTECT, null=True, blank=True, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['conta', 'identificador'], name='extrato_conta_id_unico')]
    def __str__(self):
        return f'{self.data} · {self.descricao}'

class DocumentoFiscal(Validado):
    tipo = models.CharField(max_length=5, choices=[('NFSE', 'NFS-e'), ('NFE', 'NF-e'), ('NFCE', 'NFC-e')])
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    lancamento = models.ForeignKey('gestao.Lancamento', on_delete=models.PROTECT, null=True, blank=True)
    ordem = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True)
    venda = models.ForeignKey(Venda, on_delete=models.PROTECT, null=True, blank=True)
    numero = models.CharField(max_length=30, blank=True, editable=False)
    serie = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=15, default='RASCUNHO', editable=False)
    protocolo = models.CharField(max_length=150, blank=True, editable=False)
    ambiente = models.CharField(max_length=10, choices=[('SANDBOX', 'Sandbox'), ('PRODUCAO', 'Produção')], default='SANDBOX')
    municipio = models.CharField(max_length=10, blank=True)
    codigo_servico = models.CharField(max_length=30, blank=True)
    impostos = models.JSONField(default=dict, blank=True, help_text='Valores/classificações fornecidos pelo contador; nenhuma regra fiscal presumida.')
    retencoes = models.JSONField(default=dict, blank=True)
    descricao = models.TextField('Descrição fiscal')
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f'{self.get_tipo_display()} · {self.numero or "Rascunho"} #{self.pk}'
    def get_status_display(self):
        return {'RASCUNHO':'Rascunho','ENVIADA':'Enviada','AUTORIZADA':'Autorizada','REJEITADA':'Rejeitada','CANCELADA':'Cancelada'}.get(self.status,self.status)
    def clean(self):
        super().clean()
        for origin in [self.lancamento if self.lancamento_id else None, self.ordem if self.ordem_id else None, self.venda if self.venda_id else None]:
            if origin and origin.cliente_id != self.cliente_id:
                raise ValidationError('Cliente fiscal deve coincidir com a origem.')
        for data in [self.impostos, self.retencoes]:
            if not isinstance(data, dict) or len(data) > 30 or any(any(word in str(key).lower() for word in ['senha', 'token', 'secret', 'certificado', 'password']) for key in data):
                raise ValidationError('Use somente classificações/valores fiscais, nunca segredos.')
    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if (self.status != 'RASCUNHO' or old and old.status != 'RASCUNHO') and not getattr(self, '_service_write', False):
            raise ValidationError('Estado fiscal só pode mudar pelo provedor validado.')
        return super().save(*args, **kwargs)

class Documento(Validado):
    from ordens.storage import private_storage
    titulo = models.CharField('Título', max_length=180)
    tipo = models.CharField(max_length=15, choices=[('PDF', 'PDF'), ('IMAGEM', 'Imagem'), ('CONTRATO', 'Contrato'), ('LAUDO', 'Laudo'), ('CERTIFICADO', 'Certificado'), ('MANUAL', 'Manual'), ('FISCAL_XML', 'XML fiscal'), ('FISCAL_PDF', 'PDF fiscal'), ('VIDEO', 'Vídeo')], default='PDF')
    arquivo = models.FileField(upload_to=privado, storage=private_storage, max_length=500)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT, null=True, blank=True)
    equipamento = models.ForeignKey('equipamentos.Equipamento', on_delete=models.PROTECT, null=True, blank=True)
    ordem = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True)
    contrato = models.ForeignKey('gestao.Contrato', on_delete=models.PROTECT, null=True, blank=True)
    orcamento = models.ForeignKey('gestao.Orcamento', on_delete=models.PROTECT, null=True, blank=True)
    fiscal = models.ForeignKey(DocumentoFiscal, on_delete=models.PROTECT, null=True, blank=True)
    disponivel_portal = models.BooleanField('Disponível no portal do cliente', default=False)
    sha256 = models.CharField(max_length=64, editable=False)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-criado_em']
    def __str__(self):
        return self.titulo
    def clean(self):
        super().clean()
        for name in ['equipamento', 'ordem', 'contrato', 'orcamento', 'fiscal']:
            origin = getattr(self, name) if getattr(self, name + '_id') else None
            if origin:
                if self.cliente_id and self.cliente_id != origin.cliente_id:
                    raise ValidationError({'cliente': 'Vínculos do documento pertencem a clientes diferentes.'})
                self.cliente = origin.cliente
        if self.ordem_id and self.equipamento_id and self.ordem.equipamento_id != self.equipamento_id:
            raise ValidationError('Documento vinculado a equipamentos diferentes.')
        if self.disponivel_portal and not self.cliente_id:
            raise ValidationError('Compartilhamento exige cliente identificado.')

class PortalCliente(Validado):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    cliente = models.ForeignKey('clientes.Cliente', on_delete=models.PROTECT)
    ativo = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'usuario', 'cliente'], name='portal_usuario_cliente_org')]
    def __str__(self):
        return f'{self.usuario} · {self.cliente}'
    def clean(self):
        super().clean()
        if not self.usuario.memberships.filter(organization=self.organization, role='CLIENTE', status='ATIVO').exists():
            raise ValidationError({'usuario': 'Portal exige membership CLIENTE ativo na organização.'})

class Notificacao(Validado):
    ocorrencia_estoque = models.ForeignKey('OcorrenciaEstoque', on_delete=models.PROTECT, null=True, blank=True)
    resolvida_em = models.DateTimeField(null=True, blank=True, editable=False)
    titulo = models.CharField(max_length=180)
    mensagem = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    chave = models.CharField(max_length=150)
    link = models.CharField(max_length=255, blank=True)
    lida_em = models.DateTimeField(null=True, blank=True, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-criado_em']
        constraints = [models.UniqueConstraint(fields=['organization', 'usuario', 'chave'], name='notificacao_destino_chave')]

class SaidaNotificacao(Validado):
    notificacao = models.OneToOneField(Notificacao, on_delete=models.PROTECT)
    canal = models.CharField(max_length=10, choices=[('EMAIL', 'E-mail'), ('WHATSAPP', 'WhatsApp')])
    status = models.CharField(max_length=15, default='NAO_CONFIGURADO', editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)

from .stock_models import LoteEstoque, MovimentacaoLote, ReservaEstoque, OcorrenciaEstoque, RelatorioEstoque, ItemRelatorioEstoque  # noqa: E402,F401
