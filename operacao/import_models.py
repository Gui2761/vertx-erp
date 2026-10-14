"""Import history only. Domain records remain in their existing modules."""
import uuid
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from gestao.models import Validado
from ordens.storage import private_storage

def import_file(instance,name):
    suffix='.xlsx' if name.lower().endswith('.xlsx') else '.csv'
    return f'organizations/{instance.organization.public_id}/integracoes/importacoes/{instance.public_id}/original{suffix}'

class LoteImportacao(Validado):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    tipo=models.CharField(max_length=20)
    usuario=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    nome_arquivo=models.CharField(max_length=180)
    sha256=models.CharField(max_length=64)
    arquivo=models.FileField(storage=private_storage,upload_to=import_file,max_length=500)
    colunas=models.JSONField(default=list)
    mapeamento=models.JSONField(default=dict,blank=True)
    status=models.CharField(max_length=15,default='MAPEAR')
    criado_em=models.DateTimeField(auto_now_add=True)
    concluido_em=models.DateTimeField(null=True,blank=True)
    iniciado_por=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='importacoes_confirmadas')
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','tipo','sha256'],name='importacao_arquivo_org_tipo')]
    def save(self,*args,**kwargs):
        if not getattr(self,'_service_write',False):raise ValidationError('Use o assistente para registrar a importação.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValidationError('O histórico de importação deve ser preservado.')

class LinhaImportacao(Validado):
    lote=models.ForeignKey(LoteImportacao,on_delete=models.PROTECT,related_name='linhas')
    numero=models.PositiveIntegerField()
    original=models.JSONField(default=list)
    correcoes=models.JSONField(default=dict,blank=True)
    dados=models.JSONField(default=dict,blank=True)
    problemas=models.JSONField(default=list,blank=True)
    avisos=models.JSONField(default=list,blank=True)
    estado=models.CharField(max_length=15,default='PENDENTE')
    acao=models.CharField(max_length=12,default='CRIAR')
    alvo=models.PositiveBigIntegerField(null=True,blank=True)
    alvo_hash=models.CharField(max_length=64,blank=True)
    registro=models.CharField(max_length=100,blank=True)
    class Meta:
        ordering=['numero']
        constraints=[models.UniqueConstraint(fields=['lote','numero'],name='importacao_linha_unica')]
    def save(self,*args,**kwargs):
        if not getattr(self,'_service_write',False):raise ValidationError('Use o assistente para revisar a linha.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValidationError('O histórico de importação deve ser preservado.')
