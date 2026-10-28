"""Phase H: tenant-scoped municipal education foundations.

Person identity reuses the municipality's citizen and server records. This
module stores education-specific relationships and does not copy health data.
It is not a substitute for a national school/education-system integration.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from .models import UnidadeMunicipal, Servidor
from .phase_f_models import PhaseFRecord
from .phase_g_models import CidadaoSaudeMunicipal
from .phase_d_models import VeiculoMunicipal


EDUCATION_MODULE = 'educacao_municipal'


class EducationRecord(PhaseFRecord):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        school = getattr(self, 'escola', None)
        if school and not self.unidade_id:
            self.unidade = school.unidade
            self.setor = self.unidade.setor
            self.departamento = self.setor.departamento
            self.secretaria = self.departamento.secretaria
        for field in self._meta.fields:
            if not isinstance(field, models.ForeignKey) and not isinstance(field, models.OneToOneField):
                continue
            if field.name == 'organization' or not getattr(self, field.attname, None):
                continue
            related = getattr(self, field.name, None)
            related_org = getattr(related, 'organization_id', None)
            if related_org is not None and related_org != self.organization_id:
                raise ValidationError({field.name: 'O registro relacionado pertence a outra Prefeitura.'})


class EscolaMunicipal(EducationRecord):
    """Education settings over an existing municipal organizational unit."""
    unidade = models.OneToOneField(UnidadeMunicipal, on_delete=models.PROTECT, related_name='configuracao_escolar')
    codigo_inep = models.CharField(max_length=20, blank=True)
    tipo = models.CharField(max_length=24, choices=[
        ('INFANTIL', 'Educação infantil'), ('FUNDAMENTAL', 'Ensino fundamental'),
        ('MEDIO', 'Ensino médio'), ('EJA', 'EJA'), ('OUTRA', 'Outra'),
    ], default='FUNDAMENTAL')
    etapas = models.JSONField(default=list, blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'unidade'], name='rhmun_escola_unidade_org')]


class AnoLetivoMunicipal(EducationRecord):
    nome = models.CharField(max_length=80)
    inicio = models.DateField()
    fim = models.DateField()
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['-inicio']
        constraints = [models.UniqueConstraint(fields=['organization', 'nome'], name='rhmun_ano_letivo_org_nome')]

    def clean(self):
        super().clean()
        if self.fim and self.inicio and self.fim < self.inicio:
            raise ValidationError({'fim': 'O fim do ano letivo não pode anteceder o início.'})


class SalaEscolarMunicipal(EducationRecord):
    escola = models.ForeignKey(EscolaMunicipal, on_delete=models.PROTECT, related_name='salas')
    codigo = models.CharField(max_length=30)
    capacidade = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    infraestrutura = models.JSONField(default=dict, blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'escola', 'codigo'], name='rhmun_sala_escola_codigo')]


class TurmaMunicipal(EducationRecord):
    class Turno(models.TextChoices):
        MANHA = 'MANHA', 'Manhã'
        TARDE = 'TARDE', 'Tarde'
        NOITE = 'NOITE', 'Noite'
        INTEGRAL = 'INTEGRAL', 'Integral'
    escola = models.ForeignKey(EscolaMunicipal, on_delete=models.PROTECT, related_name='turmas')
    ano_letivo = models.ForeignKey(AnoLetivoMunicipal, on_delete=models.PROTECT, related_name='turmas')
    sala = models.ForeignKey(SalaEscolarMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='turmas')
    codigo = models.CharField(max_length=30)
    etapa = models.CharField(max_length=100)
    turno = models.CharField(max_length=10, choices=Turno.choices)
    capacidade = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'escola', 'ano_letivo', 'codigo'], name='rhmun_turma_escola_ano_codigo')]

    def clean(self):
        super().clean()
        if self.ano_letivo_id and self.ano_letivo.organization_id != self.organization_id:
            raise ValidationError({'ano_letivo': 'O ano letivo pertence a outra Prefeitura.'})
        if self.sala_id and self.sala.escola_id != self.escola_id:
            raise ValidationError({'sala': 'A sala não pertence à escola da turma.'})


class MatriculaAlunoMunicipal(EducationRecord):
    class Status(models.TextChoices):
        ATIVA = 'ATIVA', 'Ativa'
        TRANSFERIDA = 'TRANSFERIDA', 'Transferida'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'
        CANCELADA = 'CANCELADA', 'Cancelada'
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cidadao = models.ForeignKey(CidadaoSaudeMunicipal, on_delete=models.PROTECT, related_name='matriculas_escolares')
    escola = models.ForeignKey(EscolaMunicipal, on_delete=models.PROTECT, related_name='matriculas')
    turma = models.ForeignKey(TurmaMunicipal, on_delete=models.PROTECT, related_name='matriculas')
    ano_letivo = models.ForeignKey(AnoLetivoMunicipal, on_delete=models.PROTECT, related_name='matriculas')
    numero = models.CharField(max_length=36)
    data_matricula = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ATIVA)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='matriculas_municipais_criadas')

    class Meta:
        ordering = ['escola__unidade__nome', 'cidadao__nome']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'escola', 'ano_letivo', 'numero'], name='rhmun_matricula_escola_numero'),
            models.UniqueConstraint(fields=['organization', 'cidadao', 'ano_letivo'], name='rhmun_matricula_aluno_ano'),
        ]

    def clean(self):
        super().clean()
        if self.turma_id and (self.turma.escola_id != self.escola_id or self.turma.ano_letivo_id != self.ano_letivo_id):
            raise ValidationError({'turma': 'A turma não pertence à escola e ao ano letivo selecionados.'})


class ResponsavelAlunoMunicipal(EducationRecord):
    aluno = models.ForeignKey(CidadaoSaudeMunicipal, on_delete=models.PROTECT, related_name='responsabilidades_escolares')
    responsavel = models.ForeignKey(CidadaoSaudeMunicipal, on_delete=models.PROTECT, related_name='alunos_responsavel')
    parentesco = models.CharField(max_length=60)
    principal = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'aluno', 'responsavel'], name='rhmun_responsavel_aluno_unico')]

    def clean(self):
        super().clean()
        if self.aluno_id and self.aluno_id == self.responsavel_id:
            raise ValidationError('O aluno não pode ser seu próprio responsável.')


class LotacaoProfessorTurma(EducationRecord):
    servidor = models.ForeignKey(Servidor, on_delete=models.PROTECT, related_name='lotacoes_escolares')
    turma = models.ForeignKey(TurmaMunicipal, on_delete=models.PROTECT, related_name='lotacoes_docentes')
    disciplina = models.CharField(max_length=100)
    carga_horaria_semanal = models.PositiveSmallIntegerField(null=True, blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'servidor', 'turma', 'disciplina'], name='rhmun_lotacao_professor_turma_disc')]


class FrequenciaEscolarMunicipal(EducationRecord):
    class Situacao(models.TextChoices):
        PRESENTE = 'PRESENTE', 'Presente'
        AUSENTE = 'AUSENTE', 'Ausente'
        JUSTIFICADA = 'JUSTIFICADA', 'Falta justificada'
    matricula = models.ForeignKey(MatriculaAlunoMunicipal, on_delete=models.PROTECT, related_name='frequencias')
    data = models.DateField()
    situacao = models.CharField(max_length=12, choices=Situacao.choices)
    observacao = models.CharField(max_length=300, blank=True)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrada_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'matricula', 'data'], name='rhmun_frequencia_matricula_data')]


class AvaliacaoEscolarMunicipal(EducationRecord):
    turma = models.ForeignKey(TurmaMunicipal, on_delete=models.PROTECT, related_name='avaliacoes')
    disciplina = models.CharField(max_length=100)
    descricao = models.CharField(max_length=180)
    realizada_em = models.DateField()
    valor_maximo = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(0.01)])
    criada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class NotaEscolarMunicipal(EducationRecord):
    avaliacao = models.ForeignKey(AvaliacaoEscolarMunicipal, on_delete=models.PROTECT, related_name='notas')
    matricula = models.ForeignKey(MatriculaAlunoMunicipal, on_delete=models.PROTECT, related_name='notas_escolares')
    valor = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(0)])
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrada_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'avaliacao', 'matricula'], name='rhmun_nota_avaliacao_matricula')]

    def clean(self):
        super().clean()
        if self.avaliacao_id and self.matricula_id and self.avaliacao.turma_id != self.matricula.turma_id:
            raise ValidationError({'matricula': 'A matrícula não pertence à turma da avaliação.'})
        if self.avaliacao_id and self.valor is not None and self.valor > self.avaliacao.valor_maximo:
            raise ValidationError({'valor': 'A nota não pode superar o valor máximo da avaliação.'})


class CalendarioEscolarMunicipal(EducationRecord):
    class Tipo(models.TextChoices):
        AULA = 'AULA', 'Período letivo'
        RECESSO = 'RECESSO', 'Recesso'
        FERIADO = 'FERIADO', 'Feriado'
        EVENTO = 'EVENTO', 'Evento escolar'
    escola = models.ForeignKey(EscolaMunicipal, on_delete=models.PROTECT, related_name='calendario')
    ano_letivo = models.ForeignKey(AnoLetivoMunicipal, on_delete=models.PROTECT, related_name='eventos')
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    titulo = models.CharField(max_length=140)
    inicio = models.DateField()
    fim = models.DateField()

    class Meta:
        ordering = ['inicio']

    def clean(self):
        super().clean()
        if self.fim and self.inicio and self.fim < self.inicio:
            raise ValidationError({'fim': 'A data final não pode anteceder a inicial.'})
        if self.escola_id and self.ano_letivo_id and self.escola.organization_id != self.ano_letivo.organization_id:
            raise ValidationError('Escola e ano letivo precisam pertencer à mesma Prefeitura.')


class CardapioAlimentacaoEscolar(EducationRecord):
    escola = models.ForeignKey(EscolaMunicipal, on_delete=models.PROTECT, related_name='cardapios')
    data = models.DateField()
    refeicao = models.CharField(max_length=80)
    descricao = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'escola', 'data', 'refeicao'], name='rhmun_cardapio_escola_data_ref')]


class ItemCardapioEscolar(EducationRecord):
    cardapio = models.ForeignKey(CardapioAlimentacaoEscolar, on_delete=models.PROTECT, related_name='itens')
    item_almoxarifado = models.ForeignKey('rh_municipal.ItemAlmoxarifadoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='cardapios_escolares')
    descricao = models.CharField(max_length=140)
    quantidade_planejada = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])


class TransporteEscolarMunicipal(EducationRecord):
    escola = models.ForeignKey(EscolaMunicipal, on_delete=models.PROTECT, related_name='transportes')
    veiculo = models.ForeignKey(VeiculoMunicipal, on_delete=models.PROTECT, related_name='rotas_escolares')
    codigo_rota = models.CharField(max_length=32)
    descricao = models.CharField(max_length=180)
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo_rota'], name='rhmun_rota_escolar_org_codigo')]


class EventoEducacaoMunicipal(EducationRecord):
    acao = models.CharField(max_length=48)
    entidade = models.CharField(max_length=80)
    entidade_id = models.PositiveBigIntegerField(null=True, blank=True)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('A auditoria da Educação é imutável.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('A auditoria da Educação não pode ser excluída.')

