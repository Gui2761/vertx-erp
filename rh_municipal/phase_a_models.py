"""Foundational municipal planning, budget, accounting and treasury models.

These records are tenant-owned and intentionally separate from the commercial
ERP's Finance and inventory ledgers. They provide configurable structures for
later public-sector workflows; they do not calculate legal/accounting rules or
post official financial events.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .models import MunicipalRecord


MUNICIPAL_MODULES = {
    'planning': 'planejamento_publico',
    'budget': 'orcamento_publico',
    'accounting': 'contabilidade_pub',
    'treasury': 'tesouraria_publica',
}


class PublicSectorRecord(MunicipalRecord):
    """Shared validations for records in the public-sector foundations."""

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if not self.organization_id:
            return
        for field in self._meta.fields:
            if not field.is_relation or not (field.many_to_one or field.one_to_one):
                continue
            if field.name == 'organization' or not getattr(self, field.attname, None):
                continue
            related = getattr(self, field.name)
            related_org_id = getattr(related, 'organization_id', None)
            if related_org_id is not None and related_org_id != self.organization_id:
                raise ValidationError({field.name: 'O registro vinculado pertence a outra Prefeitura.'})
            if field.name in {'criado_por', 'iniciado_por', 'revisado_por'} and related is not None:
                from platform_core.models import OrganizationMembership
                if not OrganizationMembership.objects.filter(
                    user=related, organization_id=self.organization_id,
                    status=OrganizationMembership.Status.ACTIVE,
                ).exists():
                    raise ValidationError({field.name: 'O responsável precisa ter membership ativo nesta Prefeitura.'})


class ExercicioMunicipal(PublicSectorRecord):
    class Status(models.TextChoices):
        PLANEJAMENTO = 'PLANEJAMENTO', 'Em planejamento'
        ATIVO = 'ATIVO', 'Ativo'
        ENCERRADO = 'ENCERRADO', 'Encerrado'

    ano = models.PositiveSmallIntegerField(validators=[MinValueValidator(1900), MaxValueValidator(2200)])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANEJAMENTO)
    descricao = models.CharField(max_length=180, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='exercicios_municipais_criados')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-ano']
        constraints = [models.UniqueConstraint(fields=['organization', 'ano'], name='rhmun_exercicio_ano_org')]

    def __str__(self):
        return str(self.ano)


class InstrumentoPlanejamentoMunicipal(PublicSectorRecord):
    class Tipo(models.TextChoices):
        PPA = 'PPA', 'Plano Plurianual (PPA)'
        LDO = 'LDO', 'Lei de Diretrizes Orçamentárias (LDO)'
        LOA = 'LOA', 'Lei Orçamentária Anual (LOA)'

    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        EM_REVISAO = 'EM_REVISAO', 'Em revisão'
        APROVADO = 'APROVADO', 'Aprovado'
        ENCERRADO = 'ENCERRADO', 'Encerrado'

    exercicio = models.ForeignKey(ExercicioMunicipal, on_delete=models.PROTECT, related_name='instrumentos')
    tipo = models.CharField(max_length=4, choices=Tipo.choices)
    versao = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    nome = models.CharField(max_length=180)
    descricao = models.TextField(blank=True)
    inicio_vigencia = models.DateField(null=True, blank=True)
    fim_vigencia = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RASCUNHO)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='instrumentos_municipais_criados')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['exercicio__ano', 'tipo', 'versao']
        constraints = [models.UniqueConstraint(fields=['organization', 'exercicio', 'tipo', 'versao'], name='rhmun_instrumento_versao_org')]

    def clean(self):
        super().clean()
        if self.inicio_vigencia and self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({'fim_vigencia': 'O fim da vigência não pode anteceder o início.'})


class OrgaoOrcamentarioMunicipal(PublicSectorRecord):
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=180)
    secretaria = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT, related_name='orgaos_orcamentarios')
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_orgao_orc_codigo')]


class UnidadeOrcamentariaMunicipal(PublicSectorRecord):
    orgao = models.ForeignKey(OrgaoOrcamentarioMunicipal, on_delete=models.PROTECT, related_name='unidades')
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=180)
    secretaria = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT, related_name='unidades_orcamentarias')
    unidade_municipal = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='unidades_orcamentarias')
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_unidade_orc_codigo')]

    def clean(self):
        super().clean()
        if self.unidade_municipal_id and self.secretaria_id and self.unidade_municipal.setor.departamento.secretaria_id != self.secretaria_id:
            raise ValidationError({'unidade_municipal': 'A unidade municipal não pertence à Secretaria informada.'})
        if self.orgao_id and self.secretaria_id and self.orgao.secretaria_id and self.orgao.secretaria_id != self.secretaria_id:
            raise ValidationError({'secretaria': 'A unidade orçamentária deve seguir o órgão informado.'})


class FuncaoOrcamentariaMunicipal(PublicSectorRecord):
    codigo = models.CharField(max_length=20)
    nome = models.CharField(max_length=180)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_funcao_orc_codigo')]


class SubfuncaoOrcamentariaMunicipal(PublicSectorRecord):
    funcao = models.ForeignKey(FuncaoOrcamentariaMunicipal, on_delete=models.PROTECT, related_name='subfuncoes')
    codigo = models.CharField(max_length=20)
    nome = models.CharField(max_length=180)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['funcao__codigo', 'codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_subfuncao_orc_codigo')]


class ProgramaPlanejamentoMunicipal(PublicSectorRecord):
    exercicio = models.ForeignKey(ExercicioMunicipal, on_delete=models.PROTECT, related_name='programas')
    instrumento = models.ForeignKey(InstrumentoPlanejamentoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='programas')
    secretaria = models.ForeignKey('rh_municipal.Secretaria', null=True, blank=True, on_delete=models.PROTECT, related_name='programas_planejamento')
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=180)
    objetivo = models.TextField(blank=True)
    publico_alvo = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=InstrumentoPlanejamentoMunicipal.Status.choices, default=InstrumentoPlanejamentoMunicipal.Status.RASCUNHO)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='programas_municipais_criados')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'exercicio', 'codigo'], name='rhmun_programa_codigo_exercicio')]


class IndicadorPlanejamentoMunicipal(PublicSectorRecord):
    programa = models.ForeignKey(ProgramaPlanejamentoMunicipal, on_delete=models.PROTECT, related_name='indicadores')
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=180)
    unidade_medida = models.CharField(max_length=60, blank=True)
    linha_base = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    meta = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    periodicidade = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ['programa__codigo', 'codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'programa', 'codigo'], name='rhmun_indicador_programa_codigo')]


class AcaoPlanejamentoMunicipal(PublicSectorRecord):
    class Tipo(models.TextChoices):
        PROJETO = 'PROJETO', 'Projeto'
        ATIVIDADE = 'ATIVIDADE', 'Atividade'
        OPERACAO_ESPECIAL = 'OPERACAO_ESPECIAL', 'Operação especial'

    programa = models.ForeignKey(ProgramaPlanejamentoMunicipal, on_delete=models.PROTECT, related_name='acoes')
    indicador = models.ForeignKey(IndicadorPlanejamentoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='acoes')
    codigo = models.CharField(max_length=30)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    nome = models.CharField(max_length=180)
    descricao = models.TextField(blank=True)
    meta_fisica = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unidade_medida = models.CharField(max_length=60, blank=True)
    inicio_previsto = models.DateField(null=True, blank=True)
    fim_previsto = models.DateField(null=True, blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['programa__codigo', 'codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'programa', 'codigo'], name='rhmun_acao_programa_codigo')]

    def clean(self):
        super().clean()
        if self.inicio_previsto and self.fim_previsto and self.fim_previsto < self.inicio_previsto:
            raise ValidationError({'fim_previsto': 'O fim previsto não pode anteceder o início.'})
        if self.indicador_id and self.programa_id and self.indicador.programa_id != self.programa_id:
            raise ValidationError({'indicador': 'O indicador deve pertencer ao mesmo programa da ação.'})


class NaturezaDespesaMunicipal(PublicSectorRecord):
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=180)
    descricao = models.TextField(blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_natureza_desp_codigo')]


class ElementoDespesaMunicipal(PublicSectorRecord):
    natureza = models.ForeignKey(NaturezaDespesaMunicipal, on_delete=models.PROTECT, related_name='elementos')
    codigo = models.CharField(max_length=30)
    nome = models.CharField(max_length=180)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['natureza__codigo', 'codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_elemento_desp_codigo')]


class FonteDestinacaoRecursoMunicipal(PublicSectorRecord):
    codigo = models.CharField(max_length=40)
    nome = models.CharField(max_length=180)
    descricao = models.TextField(blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_fonte_recurso_codigo')]


class DotacaoOrcamentariaMunicipal(PublicSectorRecord):
    exercicio = models.ForeignKey(ExercicioMunicipal, on_delete=models.PROTECT, related_name='dotacoes')
    unidade_orcamentaria = models.ForeignKey(UnidadeOrcamentariaMunicipal, on_delete=models.PROTECT, related_name='dotacoes')
    funcao = models.ForeignKey(FuncaoOrcamentariaMunicipal, on_delete=models.PROTECT, related_name='dotacoes')
    subfuncao = models.ForeignKey(SubfuncaoOrcamentariaMunicipal, on_delete=models.PROTECT, related_name='dotacoes')
    programa = models.ForeignKey(ProgramaPlanejamentoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='dotacoes')
    acao = models.ForeignKey(AcaoPlanejamentoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='dotacoes')
    natureza_despesa = models.ForeignKey(NaturezaDespesaMunicipal, on_delete=models.PROTECT, related_name='dotacoes')
    elemento_despesa = models.ForeignKey(ElementoDespesaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='dotacoes')
    fonte_recurso = models.ForeignKey(FonteDestinacaoRecursoMunicipal, on_delete=models.PROTECT, related_name='dotacoes')
    codigo_qdd = models.CharField(max_length=80, blank=True)
    descricao = models.CharField(max_length=240, blank=True)
    valor_inicial = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    creditos_adicionais = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    anulacoes = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    ativa = models.BooleanField(default=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='dotacoes_municipais_criadas')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['exercicio__ano', 'codigo_qdd', 'pk']

    @property
    def saldo_programado(self):
        return self.valor_inicial + self.creditos_adicionais - self.anulacoes

    def clean(self):
        super().clean()
        if self.subfuncao_id and self.funcao_id and self.subfuncao.funcao_id != self.funcao_id:
            raise ValidationError({'subfuncao': 'A subfunção não pertence à função informada.'})
        if self.acao_id and self.programa_id and self.acao.programa_id != self.programa_id:
            raise ValidationError({'acao': 'A ação não pertence ao programa informado.'})
        if self.programa_id and self.programa.exercicio_id != self.exercicio_id:
            raise ValidationError({'programa': 'O programa precisa pertencer ao mesmo exercício.'})


class CreditoAdicionalMunicipal(PublicSectorRecord):
    class Tipo(models.TextChoices):
        SUPLEMENTAR = 'SUPLEMENTAR', 'Suplementar'
        ESPECIAL = 'ESPECIAL', 'Especial'
        EXTRAORDINARIO = 'EXTRAORDINARIO', 'Extraordinário'

    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        EM_ANALISE = 'EM_ANALISE', 'Em análise'
        APROVADO = 'APROVADO', 'Aprovado'
        RECUSADO = 'RECUSADO', 'Recusado'

    exercicio = models.ForeignKey(ExercicioMunicipal, on_delete=models.PROTECT, related_name='creditos_adicionais')
    dotacao_destino = models.ForeignKey(DotacaoOrcamentariaMunicipal, on_delete=models.PROTECT, related_name='creditos_destino')
    dotacao_origem = models.ForeignKey(DotacaoOrcamentariaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='creditos_origem')
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    fundamento = models.TextField(blank=True)
    documento_referencia = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RASCUNHO)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='creditos_adicionais_criados')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def clean(self):
        super().clean()
        if self.dotacao_destino_id and self.dotacao_destino.exercicio_id != self.exercicio_id:
            raise ValidationError({'dotacao_destino': 'A dotação de destino deve pertencer ao exercício.'})
        if self.dotacao_origem_id and self.dotacao_origem.exercicio_id != self.exercicio_id:
            raise ValidationError({'dotacao_origem': 'A dotação de origem deve pertencer ao exercício.'})


class PlanoContasMunicipal(PublicSectorRecord):
    codigo = models.CharField(max_length=40)
    nome = models.CharField(max_length=180)
    versao = models.CharField(max_length=40, blank=True)
    referencia_normativa = models.CharField(max_length=240, blank=True)
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_ate = models.DateField(null=True, blank=True)
    ativo = models.BooleanField(default=True)
    parametrizacao = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['codigo', 'versao']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo', 'versao'], name='rhmun_plano_contas_versao')]

    def clean(self):
        super().clean()
        if self.vigente_desde and self.vigente_ate and self.vigente_ate < self.vigente_desde:
            raise ValidationError({'vigente_ate': 'O fim da vigência não pode anteceder o início.'})


class ContaContabilMunicipal(PublicSectorRecord):
    class Classificacao(models.TextChoices):
        ATIVO = 'ATIVO', 'Ativo'
        PASSIVO = 'PASSIVO', 'Passivo'
        PATRIMONIO_LIQUIDO = 'PATRIMONIO_LIQUIDO', 'Patrimônio líquido'
        VARIACAO_PATRIMONIAL_AUMENTATIVA = 'VPA', 'Variação patrimonial aumentativa'
        VARIACAO_PATRIMONIAL_DIMINUTIVA = 'VPD', 'Variação patrimonial diminutiva'
        CONTROLES = 'CONTROLES', 'Controles'
        PERSONALIZADA = 'PERSONALIZADA', 'Parametrização própria'

    plano = models.ForeignKey(PlanoContasMunicipal, on_delete=models.PROTECT, related_name='contas')
    codigo = models.CharField(max_length=80)
    nome = models.CharField(max_length=240)
    classificacao = models.CharField(max_length=32, choices=Classificacao.choices, default=Classificacao.PERSONALIZADA)
    natureza_saldo = models.CharField(max_length=30, blank=True, help_text='Parametrizada pela Prefeitura conforme norma aplicável.')
    nivel = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    conta_pai = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='contas_filhas')
    aceita_lancamento = models.BooleanField(default=False)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['plano__codigo', 'codigo']
        constraints = [models.UniqueConstraint(fields=['organization', 'plano', 'codigo'], name='rhmun_conta_contabil_codigo')]

    def clean(self):
        super().clean()
        if self.conta_pai_id and self.conta_pai.plano_id != self.plano_id:
            raise ValidationError({'conta_pai': 'A conta superior deve pertencer ao mesmo plano de contas.'})
        if self.conta_pai_id and self.conta_pai_id == self.pk:
            raise ValidationError({'conta_pai': 'Uma conta não pode ser superior a si mesma.'})


class PeriodoContabilMunicipal(PublicSectorRecord):
    class Status(models.TextChoices):
        ABERTO = 'ABERTO', 'Aberto'
        EM_FECHAMENTO = 'EM_FECHAMENTO', 'Em fechamento'
        FECHADO = 'FECHADO', 'Fechado'

    exercicio = models.ForeignKey(ExercicioMunicipal, on_delete=models.PROTECT, related_name='periodos_contabeis')
    mes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ABERTO)
    aberto_em = models.DateTimeField(default=timezone.now)
    fechado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['exercicio__ano', 'mes']
        constraints = [models.UniqueConstraint(fields=['organization', 'exercicio', 'mes'], name='rhmun_periodo_contabil_org')]


class LancamentoContabilMunicipal(PublicSectorRecord):
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        PENDENTE_INTEGRACAO = 'PENDENTE_INTEGRACAO', 'Pendente de integração'
        CANCELADO = 'CANCELADO', 'Cancelado'

    exercicio = models.ForeignKey(ExercicioMunicipal, on_delete=models.PROTECT, related_name='lancamentos_contabeis')
    periodo = models.ForeignKey(PeriodoContabilMunicipal, on_delete=models.PROTECT, related_name='lancamentos')
    data_referencia = models.DateField()
    origem = models.CharField(max_length=40, blank=True, help_text='Origem futura: orçamento, tesouraria ou outro módulo.')
    referencia_externa = models.CharField(max_length=120, blank=True)
    historico = models.TextField()
    status = models.CharField(max_length=22, choices=Status.choices, default=Status.RASCUNHO)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='lancamentos_contabeis_municipais_criados')
    request_id = models.UUIDField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_referencia', '-pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'request_id'], condition=models.Q(request_id__isnull=False), name='rhmun_lancamento_request_org')]

    def clean(self):
        super().clean()
        if self.periodo_id and self.exercicio_id and self.periodo.exercicio_id != self.exercicio_id:
            raise ValidationError({'periodo': 'O período deve pertencer ao exercício do lançamento.'})


class PartidaContabilMunicipal(PublicSectorRecord):
    class Lado(models.TextChoices):
        DEBITO = 'DEBITO', 'Débito'
        CREDITO = 'CREDITO', 'Crédito'

    lancamento = models.ForeignKey(LancamentoContabilMunicipal, on_delete=models.PROTECT, related_name='partidas')
    conta = models.ForeignKey(ContaContabilMunicipal, on_delete=models.PROTECT, related_name='partidas')
    lado = models.CharField(max_length=8, choices=Lado.choices)
    valor = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    historico = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['pk']

    def clean(self):
        super().clean()
        if self.conta_id and self.lancamento_id and self.conta.plano.organization_id != self.lancamento.organization_id:
            raise ValidationError({'conta': 'A conta deve pertencer a um plano da mesma Prefeitura.'})


class DocumentoContabilMunicipal(PublicSectorRecord):
    lancamento = models.ForeignKey(LancamentoContabilMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='documentos')
    titulo = models.CharField(max_length=180)
    tipo = models.CharField(max_length=50, blank=True)
    identificador = models.CharField(max_length=120, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    storage_key = models.CharField(max_length=500, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='documentos_contabeis_municipais_criados')
    criado_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.storage_key and ('..' in self.storage_key.split('/') or '\\' in self.storage_key):
            raise ValidationError({'storage_key': 'A chave do documento não pode conter caminhos relativos.'})


class FechamentoContabilMunicipal(PublicSectorRecord):
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        EM_REVISAO = 'EM_REVISAO', 'Em revisão'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'

    periodo = models.OneToOneField(PeriodoContabilMunicipal, on_delete=models.PROTECT, related_name='fechamento')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RASCUNHO)
    observacoes = models.TextField(blank=True)
    iniciado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='fechamentos_municipais_iniciados')
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='fechamentos_municipais_revisados')
    criado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)


class BancoMunicipal(PublicSectorRecord):
    codigo = models.CharField(max_length=30, blank=True)
    nome = models.CharField(max_length=180)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], condition=~models.Q(codigo=''), name='rhmun_banco_codigo_org')]


class ContaBancariaMunicipal(PublicSectorRecord):
    class Status(models.TextChoices):
        ATIVA = 'ATIVA', 'Ativa'
        INATIVA = 'INATIVA', 'Inativa'
        EM_CONCILIACAO = 'EM_CONCILIACAO', 'Em conciliação'

    banco = models.ForeignKey(BancoMunicipal, on_delete=models.PROTECT, related_name='contas')
    unidade_orcamentaria = models.ForeignKey(UnidadeOrcamentariaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='contas_bancarias')
    descricao = models.CharField(max_length=180)
    agencia = models.CharField(max_length=30, blank=True)
    numero_conta = models.CharField(max_length=50, blank=True)
    digito = models.CharField(max_length=8, blank=True)
    saldo_inicial_informativo = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    data_saldo_inicial = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ATIVA)
    observacoes = models.TextField(blank=True)

    class Meta:
        ordering = ['banco__nome', 'descricao']


class MovimentacaoTesourariaMunicipal(PublicSectorRecord):
    class Tipo(models.TextChoices):
        RECEITA = 'RECEITA', 'Receita informativa'
        PAGAMENTO = 'PAGAMENTO', 'Pagamento informativo'
        TRANSFERENCIA = 'TRANSFERENCIA', 'Transferência informativa'
        AJUSTE = 'AJUSTE', 'Referência de ajuste'

    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        PENDENTE_CONCILIACAO = 'PENDENTE_CONCILIACAO', 'Pendente de conciliação'
        CONCILIADA = 'CONCILIADA', 'Conciliada'
        CANCELADA = 'CANCELADA', 'Cancelada'

    conta_origem = models.ForeignKey(ContaBancariaMunicipal, on_delete=models.PROTECT, related_name='movimentacoes_origem')
    conta_destino = models.ForeignKey(ContaBancariaMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='movimentacoes_destino')
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    data_referencia = models.DateField()
    valor = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    descricao = models.CharField(max_length=240)
    documento_referencia = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=22, choices=Status.choices, default=Status.RASCUNHO)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='movimentacoes_tesouraria_municipais_criadas')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_referencia', '-pk']

    def clean(self):
        super().clean()
        if self.tipo == self.Tipo.TRANSFERENCIA and not self.conta_destino_id:
            raise ValidationError({'conta_destino': 'Informe a conta de destino da referência de transferência.'})
        if self.conta_destino_id and self.conta_destino_id == self.conta_origem_id:
            raise ValidationError({'conta_destino': 'A origem e o destino não podem ser a mesma conta.'})


class ConciliacaoBancariaMunicipal(PublicSectorRecord):
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        EM_REVISAO = 'EM_REVISAO', 'Em revisão'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'

    conta = models.ForeignKey(ContaBancariaMunicipal, on_delete=models.PROTECT, related_name='conciliacoes')
    periodo_inicio = models.DateField()
    periodo_fim = models.DateField()
    saldo_extrato_informativo = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    referencia_extrato = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RASCUNHO)
    observacoes = models.TextField(blank=True)
    iniciado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='conciliacoes_municipais_iniciadas')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-periodo_fim', '-pk']

    def clean(self):
        super().clean()
        if self.periodo_inicio and self.periodo_fim and self.periodo_fim < self.periodo_inicio:
            raise ValidationError({'periodo_fim': 'O fim do período não pode anteceder o início.'})
