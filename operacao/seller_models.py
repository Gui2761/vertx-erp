"""Small additions to the existing commercial workflow; no second sales ledger."""
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from gestao.models import Validado


class MetaVendedor(Validado):
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    competencia = models.DateField(help_text='Primeiro dia do mês da meta.')
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    # No commission rule is assumed. Administrators can define one later.
    configuracao_comissao = models.JSONField(default=dict, blank=True, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'vendedor', 'competencia'], name='meta_vendedor_mes_org')]
    def clean(self):
        super().clean()
        if self.competencia and self.competencia.day != 1:
            raise ValidationError('A competência deve ser o primeiro dia do mês.')
        if self.vendedor_id and not self.vendedor.memberships.filter(organization=self.organization, status='ATIVO', role__in=['VENDEDOR','PDV']).exists():
            raise ValidationError('A meta exige membership comercial ativo nesta organização.')


class SolicitacaoDescontoPDV(Validado):
    venda = models.ForeignKey('operacao.Venda', on_delete=models.PROTECT, related_name='solicitacoes_desconto')
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    motivo = models.TextField()
    carrinho_hash = models.CharField(max_length=64, editable=False)
    status = models.CharField(max_length=12, default='PENDENTE', editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+', editable=False)
    decidido_em = models.DateTimeField(null=True, blank=True, editable=False)
    decisao_motivo = models.TextField(blank=True, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['venda'], condition=models.Q(status='PENDENTE'), name='desconto_pdv_pendente_unico')]
    def save(self, *args, **kwargs):
        if not getattr(self, '_service_write', False):
            raise ValidationError('Desconto exige solicitação e decisão auditadas.')
        return super().save(*args, **kwargs)
