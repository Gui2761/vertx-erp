"""Phase D: tenant-scoped municipal property, warehouse and fleet records.

This module deliberately reuses the municipal hierarchy, employees, suppliers,
and public procurement records. It does not post public-accounting entries.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .models import MunicipalRecord, RegistroMunicipalImutavel


def _validate_relations(row):
    if not row.organization_id:
        return
    for field in row._meta.fields:
        if not field.is_relation or not (field.many_to_one or field.one_to_one):
            continue
        if field.name == 'organization' or not getattr(row, field.attname, None):
            continue
        related = getattr(row, field.name)
        related_org = getattr(related, 'organization_id', None)
        if related_org is not None and related_org != row.organization_id:
            raise ValidationError({field.name: 'O registro relacionado pertence a outra Prefeitura.'})
        if related_org is None and hasattr(related, 'memberships') and not related.memberships.filter(
            organization_id=row.organization_id, status='ATIVO',
        ).exists():
            raise ValidationError({field.name: 'O usuário precisa de membership ativo nesta Prefeitura.'})


class FaseDRecord(MunicipalRecord):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        _validate_relations(self)


class FaseDImmutable(RegistroMunicipalImutavel):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        _validate_relations(self)


class BemPatrimonial(FaseDRecord):
    class Situacao(models.TextChoices):
        ATIVO = 'ATIVO', 'Ativo'
        MANUTENCAO = 'MANUTENCAO', 'Em manutenção'
        CEDIDO = 'CEDIDO', 'Cedido'
        TRANSFERIDO = 'TRANSFERIDO', 'Transferido'
        BAIXADO = 'BAIXADO', 'Baixado'
        EXTRAVIADO = 'EXTRAVIADO', 'Extraviado'
        INVENTARIO = 'INVENTARIO', 'Em inventário'

    class Conservacao(models.TextChoices):
        NOVO = 'NOVO', 'Novo'
        BOM = 'BOM', 'Bom'
        REGULAR = 'REGULAR', 'Regular'
        RUIM = 'RUIM', 'Ruim'
        INSERVIVEL = 'INSERVIVEL', 'Inservível'

    tombamento = models.CharField(max_length=40)
    descricao = models.CharField(max_length=240)
    categoria = models.CharField(max_length=100)
    grupo = models.CharField(max_length=100, blank=True)
    marca = models.CharField(max_length=100, blank=True)
    modelo = models.CharField(max_length=120, blank=True)
    numero_serie = models.CharField(max_length=100, blank=True)
    fabricante = models.CharField(max_length=150, blank=True)
    fornecedor = models.ForeignKey('gestao.Fornecedor', null=True, blank=True, on_delete=models.PROTECT, related_name='bens_patrimoniais')
    nota_fiscal = models.CharField(max_length=80, blank=True)
    data_aquisicao = models.DateField(null=True, blank=True)
    valor_aquisicao = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    valor_atual = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    vida_util_meses = models.PositiveSmallIntegerField(null=True, blank=True)
    localizacao = models.CharField(max_length=180, blank=True)
    secretaria = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT, related_name='bens_patrimoniais')
    departamento = models.ForeignKey('rh_municipal.DepartamentoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='bens_patrimoniais')
    setor = models.ForeignKey('rh_municipal.SetorMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='bens_patrimoniais')
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='bens_patrimoniais')
    responsavel = models.ForeignKey('rh_municipal.Servidor', null=True, blank=True, on_delete=models.PROTECT, related_name='bens_sob_responsabilidade')
    situacao = models.CharField(max_length=16, choices=Situacao.choices, default=Situacao.ATIVO)
    conservacao = models.CharField(max_length=14, choices=Conservacao.choices, default=Conservacao.BOM)
    documento_key = models.CharField(max_length=500, blank=True)
    fotografia_key = models.CharField(max_length=500, blank=True)
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='bens_municipais_criados')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tombamento']
        constraints = [models.UniqueConstraint(fields=['organization', 'tombamento'], name='rhmun_bem_tombamento_org')]

    def clean(self):
        super().clean()
        if self.unidade_id:
            unit = self.unidade
            ancestors = {
                'secretaria_id': unit.setor.departamento.secretaria_id,
                'departamento_id': unit.setor.departamento_id,
                'setor_id': unit.setor_id,
            }
            for key, expected in ancestors.items():
                if getattr(self, key) and getattr(self, key) != expected:
                    raise ValidationError({key[:-3]: 'A localização não respeita a hierarquia municipal.'})
        elif self.setor_id:
            ancestors = {'departamento_id': self.setor.departamento_id,
                         'secretaria_id': self.setor.departamento.secretaria_id}
            for key, expected in ancestors.items():
                if getattr(self, key) and getattr(self, key) != expected:
                    raise ValidationError({key[:-3]: 'A localização não respeita a hierarquia municipal.'})
        elif self.departamento_id and self.secretaria_id and self.departamento.secretaria_id != self.secretaria_id:
            raise ValidationError({'secretaria': 'O departamento não pertence à Secretaria selecionada.'})
        if self.responsavel_id and any(getattr(self, field) and getattr(self, field) != getattr(self.responsavel, field) for field in ('secretaria_id', 'departamento_id', 'setor_id', 'unidade_id')):
            raise ValidationError({'responsavel': 'O responsável deve estar lotado na unidade de localização do bem.'})

    def __str__(self):
        return f'{self.tombamento} · {self.descricao}'


class MovimentacaoPatrimonial(FaseDImmutable):
    class Tipo(models.TextChoices):
        TRANSFERENCIA = 'TRANSFERENCIA', 'Transferência'
        CESSAO = 'CESSAO', 'Cessão'
        RECOLHIMENTO = 'RECOLHIMENTO', 'Recolhimento'
        DEVOLUCAO = 'DEVOLUCAO', 'Devolução'
        MANUTENCAO = 'MANUTENCAO', 'Manutenção'
        BAIXA = 'BAIXA', 'Baixa'
        INVENTARIO = 'INVENTARIO', 'Inventário'

    bem = models.ForeignKey(BemPatrimonial, on_delete=models.PROTECT, related_name='movimentacoes')
    tipo = models.CharField(max_length=16, choices=Tipo.choices)
    origem = models.JSONField(default=dict, blank=True)
    destino = models.JSONField(default=dict, blank=True)
    responsavel_anterior = models.ForeignKey('rh_municipal.Servidor', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    responsavel_novo = models.ForeignKey('rh_municipal.Servidor', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    ocorrido_em = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField()
    documento_key = models.CharField(max_length=500, blank=True)
    observacao = models.TextField(blank=True)


class InventarioPatrimonial(FaseDRecord):
    class Status(models.TextChoices):
        ABERTO = 'ABERTO', 'Aberto'
        CONFERENCIA = 'CONFERENCIA', 'Em conferência'
        ENCERRADO = 'ENCERRADO', 'Encerrado'

    exercicio = models.PositiveSmallIntegerField()
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='inventarios_patrimoniais')
    responsavel = models.ForeignKey('rh_municipal.Servidor', null=True, blank=True, on_delete=models.PROTECT, related_name='inventarios_patrimoniais_responsavel')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ABERTO)
    iniciado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='inventarios_patrimoniais_iniciados')
    iniciado_em = models.DateTimeField(auto_now_add=True)
    encerrado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'exercicio', 'unidade'], name='rhmun_invpat_exercicio_unidade')]


class ItemInventarioPatrimonial(FaseDRecord):
    class Resultado(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        ENCONTRADO = 'ENCONTRADO', 'Encontrado'
        NAO_ENCONTRADO = 'NAO_ENCONTRADO', 'Não encontrado'
        EXCEDENTE = 'EXCEDENTE', 'Excedente'
        DIVERGENTE = 'DIVERGENTE', 'Divergente'

    inventario = models.ForeignKey(InventarioPatrimonial, on_delete=models.PROTECT, related_name='itens')
    bem = models.ForeignKey(BemPatrimonial, null=True, blank=True, on_delete=models.PROTECT, related_name='conferencias')
    tombamento_informado = models.CharField(max_length=40, blank=True)
    encontrado = models.BooleanField(null=True, blank=True)
    fotografia_key = models.CharField(max_length=500, blank=True)
    localizacao_informada = models.CharField(max_length=180, blank=True)
    conservacao_informada = models.CharField(max_length=14, choices=BemPatrimonial.Conservacao.choices, blank=True)
    observacao = models.TextField(blank=True)
    resultado = models.CharField(max_length=16, choices=Resultado.choices, default=Resultado.PENDENTE)
    conferido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    conferido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'inventario', 'bem'], condition=Q(bem__isnull=False), name='rhmun_invpat_bem_unico')]


class EventoPatrimonioMunicipal(FaseDImmutable):
    bem = models.ForeignKey(BemPatrimonial, on_delete=models.PROTECT, related_name='eventos')
    acao = models.CharField(max_length=40)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField(blank=True)
    ocorrido_em = models.DateTimeField(default=timezone.now, editable=False)


class DepreciacaoPatrimonial(FaseDImmutable):
    class Metodo(models.TextChoices):
        NAO_DEFINIDO = 'NAO_DEFINIDO', 'Não definido'
        LINEAR_INFORMATIVO = 'LINEAR_INFORMATIVO', 'Linear informativo'
        OUTRO = 'OUTRO', 'Outro método informativo'

    bem = models.ForeignKey(BemPatrimonial, on_delete=models.PROTECT, related_name='depreciacoes')
    competencia = models.DateField()
    metodo = models.CharField(max_length=24, choices=Metodo.choices, default=Metodo.NAO_DEFINIDO)
    valor_depreciado = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    acumulado_informativo = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    valor_contabil_informativo = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    regra_referencia = models.CharField(max_length=180, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'bem', 'competencia'], name='rhmun_deprec_bem_comp_org')]


class DepositoAlmoxarifadoMunicipal(FaseDRecord):
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=140)
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='depositos_municipais')
    endereco = models.CharField(max_length=240, blank=True)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_deposito_codigo_org')]


class ItemAlmoxarifadoMunicipal(FaseDRecord):
    codigo = models.CharField(max_length=60)
    nome = models.CharField(max_length=180)
    descricao = models.TextField(blank=True)
    categoria = models.CharField(max_length=100, blank=True)
    unidade_medida = models.CharField(max_length=24, default='UN')
    estoque_minimo = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_item_almox_codigo_org')]


class SaldoAlmoxarifadoMunicipal(FaseDRecord):
    deposito = models.ForeignKey(DepositoAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='saldos')
    item = models.ForeignKey(ItemAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='saldos')
    quantidade = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'deposito', 'item'], name='rhmun_saldo_deposito_item_org'), models.CheckConstraint(condition=Q(quantidade__gte=0), name='rhmun_saldo_almox_nao_negativo')]

    def clean(self):
        super().clean()
        if self.deposito_id and self.item_id and self.deposito.organization_id != self.item.organization_id:
            raise ValidationError('Depósito e item precisam pertencer à mesma Prefeitura.')


class LoteAlmoxarifadoMunicipal(FaseDRecord):
    item = models.ForeignKey(ItemAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='lotes')
    deposito = models.ForeignKey(DepositoAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='lotes')
    codigo = models.CharField(max_length=80)
    validade = models.DateField(null=True, blank=True)
    quantidade = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'deposito', 'item', 'codigo'], name='rhmun_lote_almox_org')]

    def clean(self):
        super().clean()
        if self.deposito_id and self.item_id and self.deposito.organization_id != self.item.organization_id:
            raise ValidationError('Depósito e item do lote precisam pertencer à mesma Prefeitura.')


class SolicitacaoMaterialMunicipal(FaseDRecord):
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        PENDENTE = 'PENDENTE', 'Aguardando aprovação'
        APROVADA = 'APROVADA', 'Aprovada'
        REJEITADA = 'REJEITADA', 'Rejeitada'
        SEPARACAO = 'SEPARACAO', 'Em separação'
        ENTREGUE = 'ENTREGUE', 'Entregue'
        CANCELADA = 'CANCELADA', 'Cancelada'

    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', on_delete=models.PROTECT, related_name='solicitacoes_materiais')
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='solicitacoes_materiais_municipais')
    prioridade = models.CharField(max_length=12, choices=[('BAIXA','Baixa'),('NORMAL','Normal'),('ALTA','Alta'),('URGENTE','Urgente')], default='NORMAL')
    justificativa = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDENTE)
    aprovada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    separada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    entregue_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)


class ItemSolicitacaoMaterialMunicipal(FaseDRecord):
    solicitacao = models.ForeignKey(SolicitacaoMaterialMunicipal, on_delete=models.PROTECT, related_name='itens')
    item = models.ForeignKey(ItemAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='solicitacoes')
    quantidade_solicitada = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    quantidade_separada = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])
    quantidade_entregue = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])


class RequisicaoMaterialAuditada(FaseDImmutable):
    solicitacao = models.ForeignKey(SolicitacaoMaterialMunicipal, on_delete=models.PROTECT, related_name='historico')
    acao = models.CharField(max_length=30)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField(blank=True)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)


class RecebimentoAlmoxarifadoMunicipal(FaseDImmutable):
    deposito = models.ForeignKey(DepositoAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='recebimentos')
    fornecedor = models.ForeignKey('gestao.Fornecedor', null=True, blank=True, on_delete=models.PROTECT, related_name='recebimentos_municipais')
    processo = models.ForeignKey('rh_municipal.ProcessoContratacaoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='recebimentos_almoxarifado')
    contrato = models.ForeignKey('rh_municipal.ContratoPublicoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='recebimentos_almoxarifado')
    nota_fiscal = models.CharField(max_length=80, blank=True)
    recebido_em = models.DateTimeField(default=timezone.now)
    documento_key = models.CharField(max_length=500, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observacao = models.TextField(blank=True)

    def clean(self):
        super().clean()
        if self.contrato_id:
            if self.processo_id and self.contrato.processo_id != self.processo_id:
                raise ValidationError({'contrato': 'O contrato selecionado não pertence ao processo informado.'})
            if self.fornecedor_id and self.contrato.fornecedor_id != self.fornecedor_id:
                raise ValidationError({'fornecedor': 'O fornecedor não corresponde ao contrato informado.'})


class MovimentoAlmoxarifadoMunicipal(FaseDImmutable):
    class Tipo(models.TextChoices):
        ENTRADA = 'ENTRADA', 'Entrada'
        SAIDA = 'SAIDA', 'Saída'
        TRANSFERENCIA_ENTRADA = 'TRANSFERENCIA_ENTRADA', 'Transferência recebida'
        TRANSFERENCIA_SAIDA = 'TRANSFERENCIA_SAIDA', 'Transferência enviada'
        ENTREGA_REQUISICAO = 'ENTREGA_REQUISICAO', 'Entrega de requisição'
        AJUSTE = 'AJUSTE', 'Ajuste aprovado'

    item = models.ForeignKey(ItemAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='movimentacoes')
    deposito = models.ForeignKey(DepositoAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='movimentacoes')
    lote = models.ForeignKey(LoteAlmoxarifadoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='movimentacoes')
    recebimento = models.ForeignKey(RecebimentoAlmoxarifadoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='movimentacoes')
    solicitacao = models.ForeignKey(SolicitacaoMaterialMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='movimentacoes')
    transferencia_id = models.UUIDField(null=True, blank=True, db_index=True)
    tipo = models.CharField(max_length=24, choices=Tipo.choices)
    quantidade = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    saldo_apos = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    motivo = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        super().clean()
        if self.deposito_id and self.item_id and self.deposito.organization_id != self.item.organization_id:
            raise ValidationError('Depósito e item precisam pertencer à mesma Prefeitura.')
        if self.lote_id and (self.lote.deposito_id != self.deposito_id or self.lote.item_id != self.item_id):
            raise ValidationError({'lote': 'O lote não corresponde ao item e depósito desta movimentação.'})
        if self.recebimento_id and self.recebimento.deposito_id != self.deposito_id:
            raise ValidationError({'recebimento': 'O recebimento pertence a outro depósito.'})


class InventarioAlmoxarifadoMunicipal(FaseDRecord):
    class Status(models.TextChoices):
        ABERTO = 'ABERTO', 'Aberto'
        CONFERENCIA = 'CONFERENCIA', 'Em conferência'
        ENCERRADO = 'ENCERRADO', 'Encerrado'

    deposito = models.ForeignKey(DepositoAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='inventarios')
    exercicio = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ABERTO)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    encerrado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'deposito', 'exercicio'], name='rhmun_invalm_deposito_exercicio_org')]


class ItemInventarioAlmoxarifadoMunicipal(FaseDRecord):
    inventario = models.ForeignKey(InventarioAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='itens')
    item = models.ForeignKey(ItemAlmoxarifadoMunicipal, on_delete=models.PROTECT, related_name='inventarios')
    quantidade_sistema = models.DecimalField(max_digits=18, decimal_places=4)
    quantidade_contada = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    divergencia = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    observacao = models.TextField(blank=True)
    conferido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    conferido_em = models.DateTimeField(null=True, blank=True)


class EventoAlmoxarifadoMunicipal(FaseDImmutable):
    acao = models.CharField(max_length=40)
    entidade = models.CharField(max_length=60)
    entidade_id = models.PositiveBigIntegerField(null=True, blank=True)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField(blank=True)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)


class VeiculoMunicipal(FaseDRecord):
    class Situacao(models.TextChoices):
        ATIVO = 'ATIVO', 'Ativo'
        DISPONIVEL = 'DISPONIVEL', 'Disponível'
        EM_USO = 'EM_USO', 'Em uso'
        MANUTENCAO = 'MANUTENCAO', 'Em manutenção'
        PARADO = 'PARADO', 'Parado'
        BAIXADO = 'BAIXADO', 'Baixado'

    placa = models.CharField(max_length=10)
    renavam = models.CharField(max_length=20, blank=True)
    chassi = models.CharField(max_length=40, blank=True)
    marca = models.CharField(max_length=80)
    modelo = models.CharField(max_length=100)
    ano = models.PositiveSmallIntegerField(null=True, blank=True)
    combustivel = models.CharField(max_length=30, blank=True)
    capacidade = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    secretaria = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT, related_name='frota')
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='frota')
    responsavel = models.ForeignKey('rh_municipal.Servidor', null=True, blank=True, on_delete=models.PROTECT, related_name='veiculos_responsavel')
    situacao = models.CharField(max_length=14, choices=Situacao.choices, default=Situacao.DISPONIVEL)
    quilometragem_atual = models.PositiveBigIntegerField(default=0)
    limite_variacao_consumo_alerta = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))], help_text='Limite percentual opcional definido pela Prefeitura; vazio desativa alertas automáticos de consumo.')
    documento_key = models.CharField(max_length=500, blank=True)
    seguro = models.CharField(max_length=120, blank=True)
    observacoes = models.TextField(blank=True)

    class Meta:
        ordering = ['placa']
        constraints = [models.UniqueConstraint(fields=['organization', 'placa'], name='rhmun_veiculo_placa_org')]

    def clean(self):
        super().clean()
        if self.unidade_id and self.secretaria_id and self.unidade.setor.departamento.secretaria_id != self.secretaria_id:
            raise ValidationError({'unidade': 'A unidade não pertence à Secretaria selecionada.'})
        if self.responsavel_id and self.responsavel.organization_id != self.organization_id:
            raise ValidationError({'responsavel': 'O responsável pertence a outra Prefeitura.'})


class CondutorMunicipal(FaseDRecord):
    servidor = models.OneToOneField('rh_municipal.Servidor', on_delete=models.PROTECT, related_name='habilitacao_condutor')
    numero_cnh = models.CharField(max_length=30)
    categoria = models.CharField(max_length=8)
    validade = models.DateField()
    situacao = models.CharField(max_length=14, choices=[('ATIVO','Ativo'),('SUSPENSO','Suspenso'),('VENCIDO','Vencido')], default='ATIVO')
    autorizado = models.BooleanField(default=True)
    observacao = models.TextField(blank=True)


class ViagemMunicipal(FaseDRecord):
    class Status(models.TextChoices):
        EM_USO = 'EM_USO', 'Em uso'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'
        CANCELADA = 'CANCELADA', 'Cancelada'

    veiculo = models.ForeignKey(VeiculoMunicipal, on_delete=models.PROTECT, related_name='viagens')
    condutor = models.ForeignKey(CondutorMunicipal, on_delete=models.PROTECT, related_name='viagens')
    origem = models.CharField(max_length=180)
    destino = models.CharField(max_length=180)
    finalidade = models.TextField()
    saida_em = models.DateTimeField(default=timezone.now)
    retorno_em = models.DateTimeField(null=True, blank=True)
    quilometragem_inicial = models.PositiveBigIntegerField()
    quilometragem_final = models.PositiveBigIntegerField(null=True, blank=True)
    passageiros = models.PositiveSmallIntegerField(default=0)
    observacoes = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.EM_USO)
    iniciado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='viagens_municipais_iniciadas')
    encerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='viagens_municipais_encerradas')

    @property
    def km_percorridos(self):
        return self.quilometragem_final - self.quilometragem_inicial if self.quilometragem_final is not None else None

    def clean(self):
        super().clean()
        if self.quilometragem_final is not None and self.quilometragem_final < self.quilometragem_inicial:
            raise ValidationError({'quilometragem_final': 'A quilometragem final não pode ser menor que a inicial.'})
        if self.condutor_id and self.condutor.servidor.organization_id != self.organization_id:
            raise ValidationError({'condutor': 'O condutor pertence a outra Prefeitura.'})
        if self.condutor_id and self.condutor.servidor.unidade_id and self.veiculo_id and self.veiculo.unidade_id:
            if self.condutor.servidor.unidade_id != self.veiculo.unidade_id:
                raise ValidationError({'condutor': 'O condutor não está lotado na unidade responsável pelo veículo.'})


class AbastecimentoMunicipal(FaseDRecord):
    veiculo = models.ForeignKey(VeiculoMunicipal, on_delete=models.PROTECT, related_name='abastecimentos')
    data = models.DateTimeField(default=timezone.now)
    combustivel = models.CharField(max_length=30)
    quantidade_litros = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    tanque_completo = models.BooleanField(default=False)
    valor_unitario = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    quilometragem = models.PositiveBigIntegerField()
    fornecedor = models.ForeignKey('gestao.Fornecedor', null=True, blank=True, on_delete=models.PROTECT, related_name='abastecimentos_municipais')
    posto = models.CharField(max_length=160, blank=True)
    documento = models.CharField(max_length=120, blank=True)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    alerta_consumo_anomalo = models.BooleanField(default=False, editable=False)
    media_km_l = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True, editable=False)

    @property
    def valor_total(self):
        return (self.quantidade_litros * self.valor_unitario).quantize(Decimal('0.01'))

    def clean(self):
        super().clean()
        if self.veiculo_id and self.veiculo.organization_id != self.organization_id:
            raise ValidationError({'veiculo': 'O veículo pertence a outra Prefeitura.'})
        if self.quilometragem and self.veiculo_id and self.quilometragem < self.veiculo.quilometragem_atual:
            raise ValidationError({'quilometragem': 'A quilometragem deve ser igual ou superior ao último registro.'})


class ManutencaoVeiculoMunicipal(FaseDRecord):
    class Tipo(models.TextChoices):
        PREVENTIVA = 'PREVENTIVA', 'Preventiva'
        CORRETIVA = 'CORRETIVA', 'Corretiva'

    class Status(models.TextChoices):
        ABERTA = 'ABERTA', 'Aberta'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'
        CANCELADA = 'CANCELADA', 'Cancelada'

    veiculo = models.ForeignKey(VeiculoMunicipal, on_delete=models.PROTECT, related_name='manutencoes')
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    oficina = models.CharField(max_length=160, blank=True)
    fornecedor = models.ForeignKey('gestao.Fornecedor', null=True, blank=True, on_delete=models.PROTECT, related_name='manutencoes_frota_municipal')
    ordem = models.CharField(max_length=80, blank=True)
    descricao = models.TextField()
    pecas = models.TextField(blank=True)
    mao_de_obra = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    valor = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    quilometragem = models.PositiveBigIntegerField(null=True, blank=True)
    iniciada_em = models.DateField()
    previsao = models.DateField(null=True, blank=True)
    concluida_em = models.DateField(null=True, blank=True)
    documento_key = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.ABERTA)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def clean(self):
        super().clean()
        if self.previsao and self.previsao < self.iniciada_em:
            raise ValidationError({'previsao': 'A previsão não pode anteceder o início.'})
        if self.concluida_em and self.concluida_em < self.iniciada_em:
            raise ValidationError({'concluida_em': 'A conclusão não pode anteceder o início.'})


class DocumentoFrotaMunicipal(FaseDRecord):
    class Tipo(models.TextChoices):
        LICENCIAMENTO = 'LICENCIAMENTO', 'Licenciamento'
        SEGURO = 'SEGURO', 'Seguro'
        IPVA = 'IPVA', 'IPVA'
        MULTA = 'MULTA', 'Multa'
        OUTRO = 'OUTRO', 'Outro documento'

    veiculo = models.ForeignKey(VeiculoMunicipal, on_delete=models.PROTECT, related_name='documentos')
    tipo = models.CharField(max_length=16, choices=Tipo.choices)
    numero = models.CharField(max_length=100, blank=True)
    vence_em = models.DateField(null=True, blank=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    documento_key = models.CharField(max_length=500, blank=True)
    observacao = models.TextField(blank=True)


class EventoFrotaMunicipal(FaseDImmutable):
    veiculo = models.ForeignKey(VeiculoMunicipal, on_delete=models.PROTECT, related_name='eventos')
    acao = models.CharField(max_length=40)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField(blank=True)
    ocorrido_em = models.DateTimeField(default=timezone.now, editable=False)
