import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from gestao.models import Validado, RegistroImutavel

class Inventario(Validado):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    deposito=models.ForeignKey('operacao.Deposito',on_delete=models.PROTECT)
    status=models.CharField(max_length=12,default='ABERTO',editable=False)
    motivo=models.TextField()
    criado_por=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    aprovado_por=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    criado_em=models.DateTimeField(auto_now_add=True)
    aprovado_em=models.DateTimeField(null=True,blank=True,editable=False)
    def save(self,*args,**kwargs):
        if not getattr(self,'_service_write',False): raise ValidationError('Inventário exige operação auditada.')
        return super().save(*args,**kwargs)

class ItemInventario(RegistroImutavel):
    inventario=models.ForeignKey(Inventario,on_delete=models.PROTECT,related_name='itens')
    lote=models.ForeignKey('operacao.LoteEstoque',on_delete=models.PROTECT)
    esperado=models.DecimalField(max_digits=14,decimal_places=3)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['inventario','lote'],name='inventario_lote_unico')]

class ContagemInventario(RegistroImutavel):
    item=models.ForeignKey(ItemInventario,on_delete=models.PROTECT,related_name='contagens')
    quantidade=models.DecimalField(max_digits=14,decimal_places=3)
    saldo_no_momento=models.DecimalField(max_digits=14,decimal_places=3)
    ultimo_movimento=models.PositiveBigIntegerField(default=0)
    usuario=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    criado_em=models.DateTimeField(auto_now_add=True)
    request_id=models.UUIDField(editable=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','request_id'],name='inventario_contagem_request_org')]

class AjusteInventario(RegistroImutavel):
    item=models.OneToOneField(ItemInventario,on_delete=models.PROTECT)
    contagem=models.OneToOneField(ContagemInventario,on_delete=models.PROTECT)
    movimento=models.OneToOneField('gestao.Movimentacao',on_delete=models.PROTECT,null=True,blank=True)

class TransferenciaEstoque(Validado):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    origem=models.ForeignKey('operacao.Deposito',on_delete=models.PROTECT,related_name='+')
    destino=models.ForeignKey('operacao.Deposito',on_delete=models.PROTECT,related_name='+')
    transito=models.ForeignKey('operacao.Deposito',on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    peca=models.ForeignKey('gestao.Peca',on_delete=models.PROTECT)
    quantidade=models.DecimalField(max_digits=14,decimal_places=3)
    motivo=models.TextField()
    status=models.CharField(max_length=12,default='SOLICITADA',editable=False)
    request_id=models.UUIDField(editable=False)
    criado_por=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    criado_em=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','request_id'],name='transferencia_request_org')]
    def save(self,*args,**kwargs):
        if not getattr(self,'_service_write',False): raise ValidationError('Transferência exige serviço auditado.')
        return super().save(*args,**kwargs)
    def clean(self):
        super().clean()
        if self.origem_id==self.destino_id or self.transito_id in (self.origem_id,self.destino_id): raise ValidationError('Depósitos de origem/destino/trânsito devem ser distintos.')

class EtapaTransferencia(RegistroImutavel):
    transferencia=models.ForeignKey(TransferenciaEstoque,on_delete=models.PROTECT,related_name='etapas')
    etapa=models.CharField(max_length=12,choices=[('ENVIADA','Enviada'),('RECEBIDA','Recebida'),('DIRETA','Direta')])
    movimento=models.OneToOneField('gestao.Movimentacao',on_delete=models.PROTECT)
