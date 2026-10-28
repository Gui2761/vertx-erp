"""Municipal HR, timekeeping and payroll foundations for Phase C.

These are tenant-owned configuration and audit records. They do not calculate
statutory payroll, tax, pension or labor-law results.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .models import JornadaMunicipal, MunicipalRecord, RegistroMunicipalImutavel, Servidor


def _validate_tenant_relations(record):
    if not record.organization_id:
        return
    for field in record._meta.fields:
        if not field.is_relation or not (field.many_to_one or field.one_to_one):
            continue
        if field.name == 'organization' or not getattr(record, field.attname, None):
            continue
        related = getattr(record, field.name)
        related_org = getattr(related, 'organization_id', None)
        if related_org is not None and related_org != record.organization_id:
            raise ValidationError({field.name: 'O registro relacionado pertence a outra Prefeitura.'})
        if related_org is None and hasattr(related, 'memberships') and not related.memberships.filter(
            organization_id=record.organization_id, status='ATIVO',
        ).exists():
            raise ValidationError({field.name: 'O usuário relacionado precisa de membership ativo nesta Prefeitura.'})


class RHMunicipalRecord(MunicipalRecord):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        _validate_tenant_relations(self)


class RHMunicipalImmutableRecord(RegistroMunicipalImutavel):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        _validate_tenant_relations(self)


class HorarioJornadaMunicipal(RHMunicipalRecord):
    """Weekly schedule details; tolerance is configurable and not a legal rule."""
    jornada = models.ForeignKey(JornadaMunicipal, on_delete=models.PROTECT, related_name='horarios_detalhados')
    dia_semana = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(6)])
    inicio = models.TimeField()
    fim = models.TimeField()
    intervalo_inicio = models.TimeField(null=True, blank=True)
    intervalo_fim = models.TimeField(null=True, blank=True)
    carga_minutos = models.PositiveSmallIntegerField(default=0)
    tolerancia_entrada_minutos = models.PositiveSmallIntegerField(default=0)
    tolerancia_saida_minutos = models.PositiveSmallIntegerField(default=0)
    turno = models.CharField(max_length=50, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['dia_semana', 'inicio']
        constraints = [models.UniqueConstraint(fields=['organization', 'jornada', 'dia_semana', 'turno'], name='rhmun_horario_jornada_dia_turno')]

    def clean(self):
        super().clean()
        if self.jornada_id and self.jornada.organization_id != self.organization_id:
            raise ValidationError({'jornada': 'A jornada pertence a outra Prefeitura.'})
        if self.fim and self.inicio and self.fim <= self.inicio:
            raise ValidationError({'fim': 'O horário final deve ser posterior ao início no mesmo dia.'})
        if bool(self.intervalo_inicio) != bool(self.intervalo_fim):
            raise ValidationError('Informe início e fim do intervalo juntos.')
        if self.intervalo_inicio and not (self.inicio < self.intervalo_inicio < self.intervalo_fim < self.fim):
            raise ValidationError('O intervalo deve ficar dentro da jornada e ter duração positiva.')


class EscalaMunicipal(RHMunicipalRecord):
    nome = models.CharField(max_length=100)
    descricao = models.CharField(max_length=240, blank=True)
    ciclo_dias = models.PositiveSmallIntegerField(default=7, validators=[MinValueValidator(1), MaxValueValidator(366)])
    dias_trabalho = models.JSONField(default=list, help_text='Dias/configuração da escala definidos pela Prefeitura.')
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'nome'], name='rhmun_escala_nome_org')]
        ordering = ['nome']

    def clean(self):
        super().clean()
        if not isinstance(self.dias_trabalho, list):
            raise ValidationError({'dias_trabalho': 'A composição da escala deve ser uma lista configurável.'})


class GrupoJornadaMunicipal(RHMunicipalRecord):
    nome = models.CharField(max_length=120)
    secretaria = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT)
    departamento = models.ForeignKey('rh_municipal.DepartamentoMunicipal', null=True, blank=True, on_delete=models.PROTECT)
    setor = models.ForeignKey('rh_municipal.SetorMunicipal', null=True, blank=True, on_delete=models.PROTECT)
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT)
    jornada = models.ForeignKey(JornadaMunicipal, on_delete=models.PROTECT, related_name='grupos')
    escala = models.ForeignKey(EscalaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='grupos')
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'nome'], name='rhmun_grupo_jornada_nome_org')]
        ordering = ['nome']


class AtribuicaoJornadaMunicipal(RHMunicipalRecord):
    servidor = models.ForeignKey(Servidor, null=True, blank=True, on_delete=models.PROTECT, related_name='atribuicoes_jornada')
    grupo = models.ForeignKey(GrupoJornadaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='atribuicoes')
    jornada = models.ForeignKey(JornadaMunicipal, on_delete=models.PROTECT, related_name='atribuicoes')
    escala = models.ForeignKey(EscalaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='atribuicoes')
    inicio_vigencia = models.DateField()
    fim_vigencia = models.DateField(null=True, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-inicio_vigencia']
        constraints = [models.CheckConstraint(condition=(Q(servidor__isnull=False, grupo__isnull=True) | Q(servidor__isnull=True, grupo__isnull=False)), name='rhmun_atribuicao_alvo_exclusivo')]

    def clean(self):
        super().clean()
        if bool(self.servidor_id) == bool(self.grupo_id):
            raise ValidationError('Selecione exatamente um destino: servidor ou grupo.')
        if self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({'fim_vigencia': 'O fim da vigência não pode anteceder o início.'})
        if self.criado_por_id and not self.criado_por.memberships.filter(organization_id=self.organization_id, status='ATIVO').exists():
            raise ValidationError({'criado_por': 'O responsável precisa de membership ativo nesta Prefeitura.'})


class FeriadoMunicipal(RHMunicipalRecord):
    data = models.DateField()
    nome = models.CharField(max_length=140)
    abrangencia = models.CharField(max_length=16, choices=[('MUNICIPAL','Municipal'),('SECRETARIA','Secretaria'),('UNIDADE','Unidade')], default='MUNICIPAL')
    secretaria = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT)
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT)
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'data', 'nome'], name='rhmun_feriado_data_nome')]

    def clean(self):
        super().clean()
        if self.abrangencia == 'SECRETARIA' and not self.secretaria_id:
            raise ValidationError({'secretaria': 'Selecione a Secretaria deste feriado.'})
        if self.abrangencia == 'UNIDADE' and not self.unidade_id:
            raise ValidationError({'unidade': 'Selecione a Unidade deste feriado.'})


class FolgaMunicipal(RHMunicipalRecord):
    servidor = models.ForeignKey(Servidor, null=True, blank=True, on_delete=models.PROTECT, related_name='folgas')
    grupo = models.ForeignKey(GrupoJornadaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='folgas')
    data = models.DateField()
    motivo = models.CharField(max_length=180)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(servidor__isnull=False, grupo__isnull=True) | Q(servidor__isnull=True, grupo__isnull=False)), name='rhmun_folga_alvo_exclusivo')]

    def clean(self):
        super().clean()
        if bool(self.servidor_id) == bool(self.grupo_id):
            raise ValidationError('Selecione exatamente um destino: servidor ou grupo.')


class HistoricoLotacaoServidor(RHMunicipalImmutableRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='historico_lotacoes')
    secretaria_anterior = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    departamento_anterior = models.ForeignKey('rh_municipal.DepartamentoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    setor_anterior = models.ForeignKey('rh_municipal.SetorMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    unidade_anterior = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    secretaria_nova = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    departamento_novo = models.ForeignKey('rh_municipal.DepartamentoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    setor_novo = models.ForeignKey('rh_municipal.SetorMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    unidade_nova = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    vigencia = models.DateField()
    motivo = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)


class DependenteServidorMunicipal(RHMunicipalRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='dependentes')
    nome = models.CharField(max_length=180)
    parentesco = models.CharField(max_length=60)
    data_nascimento = models.DateField(null=True, blank=True)
    documento = models.CharField(max_length=20, blank=True)
    ativo = models.BooleanField(default=True)


class BeneficioServidorMunicipal(RHMunicipalRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='beneficios_municipais')
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=120)
    inicio = models.DateField()
    fim = models.DateField(null=True, blank=True)
    valor_informativo = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    observacao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.fim and self.inicio and self.fim < self.inicio:
            raise ValidationError({'fim': 'O fim do benefício não pode anteceder o início.'})


class RemuneracaoBaseServidorMunicipal(RHMunicipalRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='remuneracoes_base')
    valor_base = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    inicio_vigencia = models.DateField()
    fim_vigencia = models.DateField(null=True, blank=True)
    referencia_legal = models.CharField(max_length=180, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-inicio_vigencia']

    def clean(self):
        super().clean()
        if self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({'fim_vigencia': 'O fim da vigência não pode anteceder o início.'})


class PeriodoPontoMunicipal(RHMunicipalRecord):
    class Status(models.TextChoices):
        ABERTO = 'ABERTO', 'Aberto'
        EM_CONFERENCIA = 'EM_CONFERENCIA', 'Em conferência'
        AGUARDANDO_APROVACAO = 'AGUARDANDO_APROVACAO', 'Aguardando aprovação'
        APROVADO = 'APROVADO', 'Aprovado'
        FECHADO = 'FECHADO', 'Fechado'

    ano = models.PositiveSmallIntegerField(validators=[MinValueValidator(1900), MaxValueValidator(2200)])
    mes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ABERTO)
    aberto_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='periodos_ponto_abertos')
    atualizado_em = models.DateTimeField(auto_now=True)
    fechado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'ano', 'mes'], name='rhmun_periodo_ponto_org_mes')]
        ordering = ['-ano', '-mes']


class SnapshotFechamentoPontoMunicipal(RHMunicipalImmutableRecord):
    periodo = models.ForeignKey(PeriodoPontoMunicipal, on_delete=models.PROTECT, related_name='versoes')
    versao = models.PositiveSmallIntegerField()
    estado = models.CharField(max_length=24)
    dados = models.JSONField(default=dict)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField(blank=True)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'periodo', 'versao'], name='rhmun_fechamento_ponto_versao')]


class SolicitacaoHoraExtraMunicipal(RHMunicipalRecord):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        APROVADA = 'APROVADA', 'Aprovada'
        REJEITADA = 'REJEITADA', 'Rejeitada'
        CANCELADA = 'CANCELADA', 'Cancelada'

    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='solicitacoes_hora_extra')
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    quantidade_minutos = models.PositiveIntegerField()
    justificativa = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDENTE)
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='horas_extras_municipais_solicitadas')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def clean(self):
        super().clean()
        if self.fim and self.inicio and self.fim <= self.inicio:
            raise ValidationError({'fim': 'O horário final deve ser posterior ao inicial.'})


class JustificativaPontoMunicipal(RHMunicipalRecord):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        APROVADA = 'APROVADA', 'Aprovada'
        REJEITADA = 'REJEITADA', 'Rejeitada'

    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='justificativas_ponto')
    inicio = models.DateTimeField()
    fim = models.DateTimeField(null=True, blank=True)
    motivo = models.CharField(max_length=80)
    descricao = models.TextField()
    documento_key = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDENTE)
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='justificativas_ponto_solicitadas')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def clean(self):
        super().clean()
        if self.fim and self.inicio and self.fim < self.inicio:
            raise ValidationError({'fim': 'O fim do período não pode anteceder o início.'})
        if self.documento_key and ('..' in self.documento_key.split('/') or '\\' in self.documento_key):
            raise ValidationError({'documento_key': 'A chave do documento não pode conter caminho relativo.'})


class DecisaoPontoMunicipal(RHMunicipalImmutableRecord):
    solicitacao_hora_extra = models.ForeignKey(SolicitacaoHoraExtraMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='decisoes')
    justificativa = models.ForeignKey(JustificativaPontoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='decisoes')
    aprovada = models.BooleanField()
    motivo = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(solicitacao_hora_extra__isnull=False, justificativa__isnull=True) | Q(solicitacao_hora_extra__isnull=True, justificativa__isnull=False)), name='rhmun_decisao_ponto_alvo_exclusivo')]

    def clean(self):
        super().clean()
        if bool(self.solicitacao_hora_extra_id) == bool(self.justificativa_id):
            raise ValidationError('A decisão deve apontar para exatamente uma solicitação.')


class MovimentacaoBancoHorasMunicipal(RHMunicipalImmutableRecord):
    class Tipo(models.TextChoices):
        CREDITO = 'CREDITO', 'Crédito'
        DEBITO = 'DEBITO', 'Débito'
        COMPENSACAO = 'COMPENSACAO', 'Compensação'

    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='movimentacoes_banco_horas')
    tipo = models.CharField(max_length=14, choices=Tipo.choices)
    minutos = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    origem = models.CharField(max_length=40)
    referencia = models.CharField(max_length=120, blank=True)
    justificativa = models.TextField()
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)


class EventoPontoDigital(RHMunicipalImmutableRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='eventos_ponto_digital')
    acao = models.CharField(max_length=40)
    entidade = models.CharField(max_length=50)
    entidade_id = models.PositiveBigIntegerField(null=True, blank=True)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    motivo = models.TextField(blank=True)
    ator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)


class CompetenciaFolhaMunicipal(RHMunicipalRecord):
    class Status(models.TextChoices):
        PREPARACAO = 'PREPARACAO', 'Em preparação'
        CONFERENCIA = 'CONFERENCIA', 'Em conferência'
        ENCERRADA = 'ENCERRADA', 'Encerrada'

    ano = models.PositiveSmallIntegerField(validators=[MinValueValidator(1900), MaxValueValidator(2200)])
    mes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.PREPARACAO)
    descricao = models.CharField(max_length=180, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'ano', 'mes'], name='rhmun_comp_folha_org_mes')]


class EventoFolhaMunicipal(RHMunicipalRecord):
    class Natureza(models.TextChoices):
        PROVENTO = 'PROVENTO', 'Provento informativo'
        DESCONTO = 'DESCONTO', 'Desconto informativo'
        BENEFICIO = 'BENEFICIO', 'Benefício informativo'

    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=140)
    natureza = models.CharField(max_length=12, choices=Natureza.choices)
    referencia = models.CharField(max_length=100, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_evento_folha_codigo_org')]


class LancamentoFolhaMunicipal(RHMunicipalRecord):
    competencia = models.ForeignKey(CompetenciaFolhaMunicipal, on_delete=models.PROTECT, related_name='lancamentos')
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='lancamentos_folha')
    evento = models.ForeignKey(EventoFolhaMunicipal, on_delete=models.PROTECT, related_name='lancamentos')
    valor_informativo = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    referencia = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=14, choices=[('RASCUNHO','Rascunho'),('CONFERIDO','Conferido'),('CANCELADO','Cancelado')], default='RASCUNHO')
    observacao = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.competencia_id and self.competencia.organization_id != self.organization_id:
            raise ValidationError({'competencia': 'A competência pertence a outra Prefeitura.'})
        if self.servidor_id and self.servidor.organization_id != self.organization_id:
            raise ValidationError({'servidor': 'O servidor pertence a outra Prefeitura.'})
        if self.evento_id and self.evento.organization_id != self.organization_id:
            raise ValidationError({'evento': 'O evento pertence a outra Prefeitura.'})
        if self.competencia_id and self.competencia.status == CompetenciaFolhaMunicipal.Status.ENCERRADA:
            raise ValidationError('Não é possível incluir registro em competência encerrada.')
