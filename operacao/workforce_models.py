"""Personnel and internal timekeeping, distinct from OS execution timestamps."""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from gestao.models import Validado, RegistroImutavel

class Departamento(Validado):
    nome=models.CharField(max_length=100)
    filial=models.ForeignKey('platform_core.FilialEmpresa',on_delete=models.PROTECT,null=True,blank=True)
    centro_custo=models.ForeignKey('gestao.CentroCusto',on_delete=models.PROTECT,null=True,blank=True)
    ativo=models.BooleanField(default=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','nome'],name='departamento_nome_org')]
    def __str__(self): return self.nome

class JornadaTrabalho(Validado):
    nome=models.CharField(max_length=100)
    semana=models.JSONField(default=dict,help_text='Dias 0 (segunda) a 6: entrada, saida e inicio_intervalo/fim_intervalo opcionais, HH:MM.')
    virada_dia=models.BooleanField(default=False)
    tolerancia_atraso_minutos=models.PositiveSmallIntegerField(default=0)
    banco_horas_habilitado=models.BooleanField(default=False)
    compensar_deficit=models.BooleanField(default=False)
    ativo=models.BooleanField(default=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','nome'],name='jornada_nome_org')]
    def __str__(self): return self.nome
    def clean(self):
        super().clean()
        from .workforce import validate_schedule
        validate_schedule(self.semana,self.virada_dia)

class Funcionario(Validado):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    usuario=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    tecnico=models.ForeignKey('contas.Tecnico',on_delete=models.PROTECT,null=True,blank=True)
    matricula=models.CharField(max_length=30)
    nome=models.CharField(max_length=150)
    departamento=models.ForeignKey(Departamento,on_delete=models.PROTECT,null=True,blank=True)
    gestor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='funcionarios_supervisionados')
    cargo=models.CharField(max_length=100,blank=True)
    vinculo=models.CharField(max_length=100,blank=True)
    admissao=models.DateField(null=True,blank=True)
    desligamento=models.DateField(null=True,blank=True)
    jornada=models.ForeignKey(JornadaTrabalho,on_delete=models.PROTECT,null=True,blank=True)
    autoriza_geolocalizacao=models.BooleanField(default=False)
    ativo=models.BooleanField(default=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','usuario'],name='funcionario_usuario_org'),models.UniqueConstraint(fields=['organization','matricula'],name='funcionario_matricula_org')]
    def __str__(self): return self.nome
    def clean(self):
        super().clean()
        for user in (self.usuario,self.gestor if self.gestor_id else None):
            if user and not user.memberships.filter(organization_id=self.organization_id,status='ATIVO').exists(): raise ValidationError('Usuário/gestor precisa de vínculo ativo na organização.')
        if self.tecnico_id and self.tecnico.usuario_id!=self.usuario_id: raise ValidationError('Técnico deve estar ligado ao mesmo usuário.')
        if self.admissao and self.desligamento and self.desligamento<self.admissao: raise ValidationError('Desligamento anterior à admissão.')

class EscalaFuncionario(Validado):
    funcionario=models.ForeignKey(Funcionario,on_delete=models.PROTECT,related_name='escala')
    data=models.DateField()
    tipo=models.CharField(max_length=12,choices=[('FOLGA','Folga'),('FERIAS','Férias'),('AFASTAMENTO','Afastamento'),('ESCALA','Jornada específica')])
    jornada=models.ForeignKey(JornadaTrabalho,on_delete=models.PROTECT,null=True,blank=True)
    motivo=models.TextField()
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','funcionario','data'],name='escala_funcionario_data_org')]
    def clean(self):
        super().clean()
        if self.tipo=='ESCALA' and not self.jornada_id: raise ValidationError('Escala específica exige jornada.')

KINDS=[('ENTRADA','Entrada'),('SAIDA_INTERVALO','Saída para intervalo'),('RETORNO_INTERVALO','Retorno do intervalo'),('SAIDA','Saída')]

class MarcacaoPonto(RegistroImutavel):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    funcionario=models.ForeignKey(Funcionario,on_delete=models.PROTECT,related_name='marcacoes')
    tipo=models.CharField(max_length=20,choices=KINDS)
    data_hora=models.DateTimeField(editable=False)
    request_id=models.UUIDField(editable=False)
    origem=models.CharField(max_length=10,choices=[('WEB','Web'),('MOBILE','Mobile')])
    dispositivo=models.CharField(max_length=160,blank=True)
    sessao_hash=models.CharField(max_length=64,blank=True,editable=False)
    ip=models.GenericIPAddressField(null=True,blank=True)
    latitude=models.DecimalField(max_digits=9,decimal_places=6,null=True,blank=True)
    longitude=models.DecimalField(max_digits=9,decimal_places=6,null=True,blank=True)
    geo_consentimento=models.BooleanField(default=False)
    hash_anterior=models.CharField(max_length=64,blank=True,editable=False)
    sha256=models.CharField(max_length=64,editable=False)
    class Meta:
        ordering=['data_hora','pk']
        indexes=[models.Index(fields=['organization','funcionario','data_hora'],name='ponto_func_data_idx')]
        constraints=[models.UniqueConstraint(fields=['organization','request_id'],name='ponto_request_org')]

class SolicitacaoAjustePonto(Validado):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    funcionario=models.ForeignKey(Funcionario,on_delete=models.PROTECT,related_name='solicitacoes_ponto')
    marcacao=models.ForeignKey(MarcacaoPonto,on_delete=models.PROTECT,null=True,blank=True)
    tipo=models.CharField(max_length=20,choices=KINDS)
    data_hora=models.DateTimeField()
    motivo=models.TextField()
    status=models.CharField(max_length=12,default='PENDENTE',editable=False)
    criado_em=models.DateTimeField(auto_now_add=True)
    def clean(self):
        super().clean()
        if self.marcacao_id and self.marcacao.funcionario_id!=self.funcionario_id: raise ValidationError('Marcação não pertence ao funcionário.')
    def save(self,*args,**kwargs):
        if not getattr(self,'_service_write',False): raise ValidationError('Ajuste exige solicitação auditada.')
        return super().save(*args,**kwargs)

class DecisaoAjustePonto(RegistroImutavel):
    solicitacao=models.OneToOneField(SolicitacaoAjustePonto,on_delete=models.PROTECT,related_name='decisao')
    aprovado=models.BooleanField()
    usuario=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    motivo=models.TextField()
    criado_em=models.DateTimeField(auto_now_add=True)
    antes=models.JSONField(default=dict,blank=True)
    depois=models.JSONField(default=dict,blank=True)

class FechamentoPonto(RegistroImutavel):
    funcionario=models.ForeignKey(Funcionario,on_delete=models.PROTECT,related_name='fechamentos_ponto')
    ano=models.PositiveSmallIntegerField()
    mes=models.PositiveSmallIntegerField()
    snapshot=models.JSONField(default=dict,editable=False)
    saldo_anterior_minutos=models.IntegerField(default=0)
    variacao_minutos=models.IntegerField()
    saldo_final_minutos=models.IntegerField()
    usuario=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    criado_em=models.DateTimeField(auto_now_add=True)
    sha256=models.CharField(max_length=64,editable=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','funcionario','ano','mes'],name='fechamento_ponto_competencia_org'),models.CheckConstraint(condition=models.Q(mes__gte=1,mes__lte=12),name='fechamento_ponto_mes_valido')]
