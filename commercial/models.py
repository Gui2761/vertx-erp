import uuid
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from .catalog import FEATURES, FUTURE_FEATURES, RESOURCE_STATES


class PlanoComercial(models.Model):
    """Global marketing catalog. Does not grant access or enforce tenant quotas."""
    slug = models.SlugField(unique=True)
    nome = models.CharField(max_length=80)
    preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    periodicidade = models.CharField(max_length=8, choices=[('MENSAL','Mensal'),('ANUAL','Anual')], default='MENSAL')
    preco_anual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    desconto_anual = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0),MaxValueValidator(Decimal('99.99'))])
    descricao = models.CharField(max_length=240)
    limite_usuarios = models.PositiveIntegerField(null=True, blank=True)
    limite_tecnicos = models.PositiveIntegerField(null=True, blank=True)
    recursos = models.JSONField(default=dict, blank=True)
    destaque = models.BooleanField(default=False)
    ordem = models.PositiveIntegerField(default=0)
    ativo = models.BooleanField(default=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ordem','pk']
        verbose_name = 'plano comercial'
        verbose_name_plural = 'planos comerciais'

    def __str__(self):
        return self.nome

    def clean(self):
        if not isinstance(self.recursos,dict) or any(key not in FEATURES.keys() | FUTURE_FEATURES or value not in RESOURCE_STATES for key,value in self.recursos.items()):
            raise ValidationError({'recursos':'Use recursos conhecidos com INCLUIDO, CONSULTA ou FUTURO.'})
        if self.periodicidade=='ANUAL' and self.desconto_anual is not None:
            raise ValidationError({'desconto_anual':'O desconto anual é calculado a partir de um preço mensal.'})

    def save(self,*args,**kwargs):
        self.full_clean()
        return super().save(*args,**kwargs)

    @property
    def valor_anual(self):
        if self.preco_anual is not None:
            return self.preco_anual
        if self.periodicidade=='ANUAL':
            return self.preco
        if self.preco is not None and self.desconto_anual is not None:
            return (self.preco*12*(1-self.desconto_anual/100)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        return None


class InteresseComercial(models.Model):
    """A request for human follow-up; never a subscription, tenant or invoice."""
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    plano = models.ForeignKey(PlanoComercial,on_delete=models.PROTECT,null=True,blank=True)
    periodicidade = models.CharField(max_length=8,choices=[('MENSAL','Mensal'),('ANUAL','Anual')],default='MENSAL')
    oferta = models.JSONField(default=dict,editable=False)
    nome = models.CharField(max_length=120)
    empresa = models.CharField(max_length=160)
    email = models.EmailField()
    telefone = models.CharField(max_length=30,blank=True)
    objetivo = models.CharField(max_length=20,choices=[('ASSISTENCIA','Assistência técnica'),('COMERCIO','Vendas e comércio'),('INTEGRADA','Gestão integrada'),('SUPORTE','Informações e suporte'),('PRIVACIDADE','Contato sobre privacidade')],default='INTEGRADA')
    mensagem = models.TextField(blank=True,max_length=2000)
    consentimento = models.BooleanField(default=False)
    versao_privacidade = models.CharField(max_length=20,default='2026-10-06',editable=False)
    status = models.CharField(max_length=12,choices=[('NOVO','Novo'),('CONTATADO','Contatado'),('ENCERRADO','Encerrado')],default='NOVO')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'interesse comercial'
        verbose_name_plural = 'interesses comerciais'

    def __str__(self):
        return f'{self.empresa} · {self.get_status_display()}'
