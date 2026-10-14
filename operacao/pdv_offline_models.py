import uuid
from django.conf import settings
from django.db import models
from gestao.models import RegistroImutavel


class SincronizacaoPDV(RegistroImutavel):
    request_id=models.UUIDField(default=uuid.uuid4,editable=False)
    dispositivo=models.UUIDField(editable=False)
    operador=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,editable=False)
    venda=models.OneToOneField('operacao.Venda',on_delete=models.PROTECT,editable=False)
    payload_hash=models.CharField(max_length=64,editable=False)
    criado_em=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','request_id'],name='pdv_sync_org_request_unico')]
