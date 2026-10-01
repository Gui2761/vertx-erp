"""Detalhamento do estoque existente; Peca/SaldoDeposito continuam agregados oficiais."""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from gestao.models import Validado, RegistroImutavel, ZERO

class LoteEstoque(Validado):
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT, related_name='lotes')
    deposito = models.ForeignKey('operacao.Deposito', on_delete=models.PROTECT, related_name='lotes')
    grupo = models.UUIDField(default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=100)
    fabricacao = models.DateField(null=True, blank=True)
    validade = models.DateField(null=True, blank=True)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO, editable=False)
    fornecedor = models.ForeignKey('gestao.Fornecedor', on_delete=models.PROTECT, null=True, blank=True)
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    entrada_em = models.DateTimeField(default=timezone.now)
    localizacao = models.CharField(max_length=150, blank=True)
    documento_entrada = models.CharField(max_length=180, blank=True)
    item_compra = models.ForeignKey('operacao.ItemCompra', on_delete=models.PROTECT, null=True, blank=True)
    legado = models.BooleanField(default=False, editable=False)
    class Meta:
        ordering = ['validade', 'entrada_em', 'pk']
        constraints = [models.CheckConstraint(check=Q(quantidade__gte=0), name='lote_quantidade_positiva'), models.UniqueConstraint(fields=['organization','grupo','deposito'], name='lote_grupo_deposito')]
    def __str__(self):
        return f'{self.peca.sku} · {self.numero} · {self.deposito}'
    @property
    def classificacao(self):
        if not self.validade:
            return 'SEM VALIDADE'
        days = (self.validade - timezone.localdate()).days
        if days < 0:
            return 'VENCIDO'
        for limit in [7, 15, 30, 60, 90]:
            if days <= limit:
                return f'VENCE EM ATÉ {limit} DIAS'
        return 'VALIDADE NORMAL'
    def clean(self):
        super().clean()
        if self.fabricacao and self.validade and self.fabricacao > self.validade:
            raise ValidationError('Fabricação posterior à validade.')
        if self.item_compra_id and self.item_compra.peca_id != self.peca_id:
            raise ValidationError('Item de compra pertence a outro produto.')
    def save(self, *args, **kwargs):
        if not getattr(self, '_service_write', False):
            raise ValidationError('Lotes e saldos exigem movimentação transacional auditada.')
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValidationError('Histórico de lote deve ser preservado.')

class MovimentacaoLote(RegistroImutavel):
    movimentacao = models.ForeignKey('gestao.Movimentacao', on_delete=models.PROTECT, related_name='lotes_movimentados')
    lote = models.ForeignKey(LoteEstoque, on_delete=models.PROTECT, related_name='movimentos')
    quantidade_anterior = models.DecimalField(max_digits=14, decimal_places=3)
    variacao = models.DecimalField(max_digits=14, decimal_places=3)
    quantidade_posterior = models.DecimalField(max_digits=14, decimal_places=3)

class ReservaEstoque(Validado):
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT, related_name='reservas')
    deposito = models.ForeignKey('operacao.Deposito', on_delete=models.PROTECT)
    ordem = models.ForeignKey('ordens.OrdemServico', on_delete=models.PROTECT, null=True, blank=True, related_name='reservas_estoque')
    venda = models.ForeignKey('operacao.Venda', on_delete=models.PROTECT, null=True, blank=True, related_name='reservas_estoque')
    quantidade = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(ZERO)])
    status = models.CharField(max_length=12, default='ATIVA', choices=[('ATIVA','Ativa'),('CONSUMIDA','Consumida'),('LIBERADA','Liberada')], editable=False)
    motivo = models.CharField(max_length=255)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.CheckConstraint(check=Q(quantidade__gte=0), name='reserva_quantidade_positiva')]
    def save(self, *args, **kwargs):
        if not getattr(self, '_service_write', False):
            raise ValidationError('Reservas exigem serviço auditado.')
        return super().save(*args, **kwargs)

class OcorrenciaEstoque(Validado):
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT)
    lote = models.ForeignKey(LoteEstoque, on_delete=models.PROTECT, null=True, blank=True)
    chave = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20)
    situacao = models.CharField(max_length=100)
    dados = models.JSONField(default=dict)
    aberta_em = models.DateTimeField(default=timezone.now)
    atualizada_em = models.DateTimeField(default=timezone.now)
    resolvida_em = models.DateTimeField(null=True, blank=True, editable=False)
    class Meta:
        ordering = ['-aberta_em']
        constraints = [models.UniqueConstraint(fields=['organization','chave'], condition=Q(resolvida_em__isnull=True), name='ocorrencia_estoque_aberta_unica')]

class RelatorioEstoque(RegistroImutavel):
    semana = models.DateField()
    gerado_em = models.DateTimeField(default=timezone.now)
    automatico = models.BooleanField(default=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    parametros = models.JSONField(default=dict)
    class Meta:
        ordering = ['-gerado_em']
        constraints = [models.UniqueConstraint(fields=['organization','semana'], condition=Q(automatico=True), name='relatorio_estoque_semana_unica')]
    def __str__(self):
        return f'Compras · semana de {self.semana:%d/%m/%Y}'

class ItemRelatorioEstoque(RegistroImutavel):
    relatorio = models.ForeignKey(RelatorioEstoque, on_delete=models.PROTECT, related_name='itens')
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT)
    dados = models.JSONField(default=dict)
    class Meta:
        ordering = ['pk']
        constraints = [models.UniqueConstraint(fields=['relatorio','peca'], name='relatorio_estoque_peca_unica')]
