"""Commercial workflow records linked to official stock and finance."""
import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from gestao.models import Validado, RegistroImutavel

class ConfiguracaoPDV(Validado):
    limite_desconto_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0),MaxValueValidator(100)])
    reservar_rascunho = models.BooleanField(default=False)
    reservar_orcamento = models.BooleanField(default=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization'],name='config_pdv_organization')]

class SessaoCaixa(Validado):
    public_id = models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    conta = models.ForeignKey('operacao.ContaBancaria',on_delete=models.PROTECT)
    operador = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='sessoes_caixa')
    abertura_id = models.UUIDField(editable=False)
    aberto_em = models.DateTimeField(auto_now_add=True)
    fechado_em = models.DateTimeField(null=True,blank=True,editable=False)
    saldo_abertura = models.DecimalField(max_digits=14,decimal_places=2,validators=[MinValueValidator(0)])
    esperado = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,editable=False)
    contado = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,editable=False)
    diferenca = models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True,editable=False)
    justificativa = models.TextField(blank=True,editable=False)
    fechado_por = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','abertura_id'],name='caixa_abertura_org'),models.UniqueConstraint(fields=['conta'],condition=models.Q(fechado_em__isnull=True),name='caixa_conta_sessao_aberta')]
    def save(self,*args,**kwargs):
        if not getattr(self,'_service_write',False):
            raise ValidationError('Caixa é alterado somente pelas operações auditadas.')
        return super().save(*args,**kwargs)

class EventoCaixa(RegistroImutavel):
    sessao = models.ForeignKey(SessaoCaixa,on_delete=models.PROTECT,related_name='eventos')
    movimento = models.OneToOneField('operacao.MovimentoCaixa',on_delete=models.PROTECT)
    tipo = models.CharField(max_length=15,choices=[('VENDA','Venda'),('SUPRIMENTO','Suprimento'),('SANGRIA','Sangria'),('RETIRADA','Retirada'),('AJUSTE','Ajuste autorizado'),('DEVOLUCAO','Devolução')])

class PagamentoVenda(RegistroImutavel):
    venda = models.ForeignKey('operacao.Venda',on_delete=models.PROTECT,related_name='pagamentos_pdv')
    forma = models.ForeignKey('gestao.FormaPagamento',on_delete=models.PROTECT)
    pagamento = models.OneToOneField('operacao.Pagamento',on_delete=models.PROTECT,null=True,blank=True)
    valor = models.DecimalField(max_digits=14,decimal_places=2,validators=[MinValueValidator(Decimal('.01'))])
    recebido = models.DecimalField(max_digits=14,decimal_places=2)
    troco = models.DecimalField(max_digits=14,decimal_places=2,default=0)
    parcelas = models.PositiveSmallIntegerField(default=1,validators=[MinValueValidator(1),MaxValueValidator(12)])
    class Meta:
        constraints=[models.CheckConstraint(condition=models.Q(parcelas__gte=1,parcelas__lte=12),name='pagamento_venda_parcelas_1_12')]

class DevolucaoVenda(RegistroImutavel):
    dados = models.JSONField(default=dict,editable=False)
    public_id = models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    venda = models.ForeignKey('operacao.Venda',on_delete=models.PROTECT,related_name='devolucoes')
    request_id = models.UUIDField(editable=False)
    motivo = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)
    valor = models.DecimalField(max_digits=14,decimal_places=2)
    reembolso = models.OneToOneField('gestao.Lancamento',on_delete=models.PROTECT,null=True,blank=True,related_name='devolucao_origem')
    def __str__(self): return f'Devolução {self.venda}'
    troca_por = models.ForeignKey('operacao.Venda',on_delete=models.PROTECT,null=True,blank=True,related_name='trocas_recebidas')
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','request_id'],name='devolucao_venda_request_org')]

class ItemDevolucaoVenda(RegistroImutavel):
    devolucao = models.ForeignKey(DevolucaoVenda,on_delete=models.PROTECT,related_name='itens')
    item = models.ForeignKey('operacao.ItemVenda',on_delete=models.PROTECT,related_name='devolucoes')
    quantidade = models.DecimalField(max_digits=14,decimal_places=3)
    valor = models.DecimalField(max_digits=14,decimal_places=2)
    movimento = models.OneToOneField('gestao.Movimentacao',on_delete=models.PROTECT)
