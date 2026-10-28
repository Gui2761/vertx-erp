"""Tenant-isolated procurement and contracting records for Gestão Pública.

This layer records procurement workflow data. It deliberately does not encode
legal decision rules, publish notices, post official budget commitments, or
execute payments.
"""
from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .models import MunicipalRecord, RegistroMunicipalImutavel
from .phase_a_models import PublicSectorRecord


MUNICIPAL_PROCUREMENT_MODULES = {
    'compras': 'compras_publicas',
    'licitacoes': 'licitacoes_publicas',
    'atas': 'registro_precos',
    'contratos': 'contratos_publicos',
}


class ContratacaoPublicaRecord(PublicSectorRecord):
    class Meta:
        abstract = True


class ModalidadeContratacaoMunicipal(ContratacaoPublicaRecord):
    """Tenant-configurable modality/foundation catalog; no legal rules inferred."""
    codigo = models.CharField(max_length=40)
    nome = models.CharField(max_length=140)
    fundamento_referencia = models.CharField(max_length=240, blank=True)
    descricao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    class Meta:
        ordering = ['nome']
        constraints = [models.UniqueConstraint(fields=['organization', 'codigo'], name='rhmun_modalidade_codigo_org')]
    def __str__(self):
        return self.nome


class SolicitacaoCompra(ContratacaoPublicaRecord):
    class Prioridade(models.TextChoices):
        BAIXA = 'BAIXA', 'Baixa'
        NORMAL = 'NORMAL', 'Normal'
        ALTA = 'ALTA', 'Alta'
        URGENTE = 'URGENTE', 'Urgente'
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        ENVIADA = 'ENVIADA', 'Enviada'
        EM_ANALISE = 'EM_ANALISE', 'Em análise'
        APROVADA = 'APROVADA', 'Aprovada'
        REJEITADA = 'REJEITADA', 'Rejeitada'
        EM_CONTRATACAO = 'EM_CONTRATACAO', 'Em contratação'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'
        CANCELADA = 'CANCELADA', 'Cancelada'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    numero = models.CharField(max_length=40)
    exercicio = models.PositiveSmallIntegerField()
    secretaria = models.ForeignKey('rh_municipal.Secretaria', on_delete=models.PROTECT, related_name='solicitacoes_compra')
    departamento = models.ForeignKey('rh_municipal.DepartamentoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='solicitacoes_compra')
    setor = models.ForeignKey('rh_municipal.SetorMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='solicitacoes_compra')
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='solicitacoes_compra')
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='solicitacoes_compras_municipais')
    justificativa = models.TextField()
    prioridade = models.CharField(max_length=12, choices=Prioridade.choices, default=Prioridade.NORMAL)
    fonte_recurso = models.ForeignKey('rh_municipal.FonteDestinacaoRecursoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='solicitacoes_compra')
    unidade_orcamentaria = models.ForeignKey('rh_municipal.UnidadeOrcamentariaMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='solicitacoes_compra')
    dotacao = models.ForeignKey('rh_municipal.DotacaoOrcamentariaMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='solicitacoes_compra')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RASCUNHO)
    enviado_em = models.DateTimeField(null=True, blank=True)
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='solicitacoes_compras_decididas')
    decidido_em = models.DateTimeField(null=True, blank=True)
    motivo_decisao = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='solicitacoes_compra_criadas')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-criado_em']
        constraints = [models.UniqueConstraint(fields=['organization', 'exercicio', 'numero'], name='rhmun_solic_compra_num_org')]
    def clean(self):
        super().clean()
        from platform_core.models import OrganizationMembership
        for field_name in ('responsavel', 'decidido_por', 'criado_por'):
            user = getattr(self, field_name, None)
            if user and not OrganizationMembership.objects.filter(
                user=user, organization_id=self.organization_id,
                status=OrganizationMembership.Status.ACTIVE,
            ).exists():
                raise ValidationError({field_name: 'O usuário precisa ter membership ativo nesta Prefeitura.'})
        if self.secretaria_id and self.departamento_id and self.departamento.secretaria_id != self.secretaria_id:
            raise ValidationError({'departamento': 'Departamento não pertence à Secretaria selecionada.'})
        if self.setor_id and self.departamento_id and self.setor.departamento_id != self.departamento_id:
            raise ValidationError({'setor': 'Setor não pertence ao Departamento selecionado.'})
        if self.unidade_id and self.setor_id and self.unidade.setor_id != self.setor_id:
            raise ValidationError({'unidade': 'Unidade não pertence ao Setor selecionado.'})
        if self.unidade_id and self.secretaria_id and self.unidade.setor.departamento.secretaria_id != self.secretaria_id:
            raise ValidationError({'unidade': 'Unidade não pertence à Secretaria selecionada.'})
        if self.dotacao_id and self.unidade_orcamentaria_id and self.dotacao.unidade_orcamentaria_id != self.unidade_orcamentaria_id:
            raise ValidationError({'dotacao': 'A dotação não pertence à unidade orçamentária selecionada.'})
    def __str__(self):
        return f'{self.numero}/{self.exercicio}'


class ItemSolicitacaoCompra(ContratacaoPublicaRecord):
    solicitacao = models.ForeignKey(SolicitacaoCompra, on_delete=models.PROTECT, related_name='itens')
    descricao = models.CharField(max_length=240)
    especificacao = models.TextField(blank=True)
    quantidade = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    unidade_medida = models.CharField(max_length=30)
    estimativa_unitaria = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    criado_em = models.DateTimeField(auto_now_add=True)
    @property
    def estimativa_total(self):
        return (self.quantidade * self.estimativa_unitaria).quantize(Decimal('0.01')) if self.estimativa_unitaria is not None else None


class ProcessoContratacaoMunicipal(ContratacaoPublicaRecord):
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        EM_PLANEJAMENTO = 'EM_PLANEJAMENTO', 'Em planejamento'
        PUBLICADO = 'PUBLICADO', 'Publicado'
        EM_DISPUTA = 'EM_DISPUTA', 'Em disputa'
        EM_JULGAMENTO = 'EM_JULGAMENTO', 'Em julgamento'
        EM_HABILITACAO = 'EM_HABILITACAO', 'Em habilitação'
        EM_RECURSO = 'EM_RECURSO', 'Em recurso'
        ADJUDICADO = 'ADJUDICADO', 'Adjudicado'
        HOMOLOGADO = 'HOMOLOGADO', 'Homologado'
        FRACASSADO = 'FRACASSADO', 'Fracassado'
        REVOGADO = 'REVOGADO', 'Revogado'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'
        CANCELADO = 'CANCELADO', 'Cancelado'
    numero = models.CharField(max_length=40)
    exercicio = models.PositiveSmallIntegerField()
    solicitacao = models.ForeignKey(SolicitacaoCompra, null=True, blank=True, on_delete=models.PROTECT, related_name='processos')
    secretaria = models.ForeignKey('rh_municipal.Secretaria', on_delete=models.PROTECT, related_name='processos_contratacao')
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='processos_contratacao')
    objeto = models.CharField(max_length=400)
    justificativa = models.TextField(blank=True)
    modalidade = models.ForeignKey(ModalidadeContratacaoMunicipal, on_delete=models.PROTECT, related_name='processos')
    fundamento = models.TextField(blank=True, help_text='Referência a ser definida e validada pela Prefeitura; não aplica regra legal automaticamente.')
    unidade_orcamentaria = models.ForeignKey('rh_municipal.UnidadeOrcamentariaMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='processos_contratacao')
    dotacao = models.ForeignKey('rh_municipal.DotacaoOrcamentariaMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='processos_contratacao')
    fonte_recurso = models.ForeignKey('rh_municipal.FonteDestinacaoRecursoMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='processos_contratacao')
    valor_estimado = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0'))])
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='processos_contratacao_responsavel')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RASCUNHO)
    iniciado_em = models.DateField(null=True, blank=True)
    encerrado_em = models.DateField(null=True, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='processos_contratacao_criados')
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-exercicio', '-numero']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'exercicio', 'numero'], name='rhmun_proc_contratacao_num_org'),
            models.UniqueConstraint(fields=['solicitacao'], condition=Q(solicitacao__isnull=False), name='rhmun_proc_solicitacao_unique'),
        ]
    def clean(self):
        super().clean()
        from platform_core.models import OrganizationMembership
        for field_name in ('responsavel', 'criado_por'):
            user = getattr(self, field_name, None)
            if user and not OrganizationMembership.objects.filter(
                user=user, organization_id=self.organization_id,
                status=OrganizationMembership.Status.ACTIVE,
            ).exists():
                raise ValidationError({field_name: 'O usuário precisa ter membership ativo nesta Prefeitura.'})
        if self.solicitacao_id and self.solicitacao.status != SolicitacaoCompra.Status.APROVADA:
            raise ValidationError({'solicitacao': 'Somente uma solicitação aprovada pode originar contratação.'})
        if self.secretaria_id and self.solicitacao_id and self.solicitacao.secretaria_id != self.secretaria_id:
            raise ValidationError({'secretaria': 'A Secretaria deve corresponder à solicitação de origem.'})
        if self.dotacao_id and self.unidade_orcamentaria_id and self.dotacao.unidade_orcamentaria_id != self.unidade_orcamentaria_id:
            raise ValidationError({'dotacao': 'A dotação não pertence à unidade orçamentária selecionada.'})
    def __str__(self):
        return f'{self.numero}/{self.exercicio} · {self.objeto}'


class LoteContratacaoMunicipal(ContratacaoPublicaRecord):
    processo = models.ForeignKey(ProcessoContratacaoMunicipal, on_delete=models.PROTECT, related_name='lotes')
    numero = models.CharField(max_length=30)
    descricao = models.CharField(max_length=240)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['processo', 'numero'], name='rhmun_lote_proc_num')]
    def __str__(self):
        return f'Lote {self.numero} · {self.descricao}'


class ItemContratacaoMunicipal(ContratacaoPublicaRecord):
    processo = models.ForeignKey(ProcessoContratacaoMunicipal, on_delete=models.PROTECT, related_name='itens')
    solicitacao_item = models.ForeignKey(ItemSolicitacaoCompra, null=True, blank=True, on_delete=models.PROTECT, related_name='itens_contratacao')
    lote = models.ForeignKey(LoteContratacaoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='itens')
    numero = models.PositiveIntegerField()
    descricao = models.CharField(max_length=240)
    especificacao = models.TextField(blank=True)
    quantidade = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    unidade_medida = models.CharField(max_length=30)
    valor_estimado_unitario = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    fornecedor_vencedor = models.ForeignKey('gestao.Fornecedor', null=True, blank=True, on_delete=models.PROTECT, related_name='itens_vencedores_municipais')
    valor_vencedor_unitario = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    situacao = models.CharField(max_length=24, default='ABERTO')
    class Meta:
        ordering = ['numero']
        constraints = [models.UniqueConstraint(fields=['processo', 'numero'], name='rhmun_item_proc_num')]
    def clean(self):
        super().clean()
        if self.lote_id and self.processo_id and self.lote.processo_id != self.processo_id:
            raise ValidationError({'lote': 'O lote pertence a outro processo.'})
        if self.solicitacao_item_id and self.processo_id and self.processo.solicitacao_id != self.solicitacao_item.solicitacao_id:
            raise ValidationError({'solicitacao_item': 'O item não pertence à solicitação de origem do processo.'})


class PesquisaPrecoMunicipal(ContratacaoPublicaRecord):
    solicitacao = models.ForeignKey(SolicitacaoCompra, null=True, blank=True, on_delete=models.PROTECT, related_name='pesquisas_preco')
    processo = models.ForeignKey(ProcessoContratacaoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='pesquisas_preco')
    data_referencia = models.DateField(default=timezone.localdate)
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pesquisas_preco_municipais')
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-data_referencia', '-pk']
    def clean(self):
        super().clean()
        if bool(self.solicitacao_id) == bool(self.processo_id):
            raise ValidationError('A pesquisa precisa estar vinculada a uma solicitação ou processo, somente um deles.')


class CotacaoFornecedorMunicipal(ContratacaoPublicaRecord):
    pesquisa = models.ForeignKey(PesquisaPrecoMunicipal, on_delete=models.PROTECT, related_name='cotacoes')
    fornecedor = models.ForeignKey('gestao.Fornecedor', on_delete=models.PROTECT, related_name='cotacoes_publicas')
    data = models.DateField(default=timezone.localdate)
    fonte = models.CharField(max_length=180, blank=True)
    documento_referencia = models.CharField(max_length=240, blank=True)
    observacao = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['pesquisa', 'fornecedor'], name='rhmun_cotacao_pesq_fornec')]


class ItemPesquisaPrecoMunicipal(ContratacaoPublicaRecord):
    cotacao = models.ForeignKey(CotacaoFornecedorMunicipal, on_delete=models.PROTECT, related_name='itens')
    descricao = models.CharField(max_length=240)
    quantidade = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    unidade_medida = models.CharField(max_length=30)
    preco_unitario = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    observacao = models.TextField(blank=True)
    @property
    def preco_total(self):
        return (self.quantidade * self.preco_unitario).quantize(Decimal('0.01'))


class LicitacaoMunicipal(ContratacaoPublicaRecord):
    processo = models.OneToOneField(ProcessoContratacaoMunicipal, on_delete=models.PROTECT, related_name='licitacao')
    numero_edital = models.CharField(max_length=60, blank=True)
    data_publicacao = models.DateField(null=True, blank=True)
    meio_publicacao = models.CharField(max_length=180, blank=True)
    prazo_propostas = models.DateTimeField(null=True, blank=True)
    resultado_resumo = models.TextField(blank=True)
    class Meta:
        ordering = ['-data_publicacao', '-pk']


class FornecedorProcessoMunicipal(ContratacaoPublicaRecord):
    class Status(models.TextChoices):
        INSCRITO = 'INSCRITO', 'Inscrito'
        HABILITADO = 'HABILITADO', 'Habilitado'
        INABILITADO = 'INABILITADO', 'Inabilitado'
        DESISTENTE = 'DESISTENTE', 'Desistente'
    processo = models.ForeignKey(ProcessoContratacaoMunicipal, on_delete=models.PROTECT, related_name='fornecedores')
    fornecedor = models.ForeignKey('gestao.Fornecedor', on_delete=models.PROTECT, related_name='participacoes_publicas')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INSCRITO)
    observacoes = models.TextField(blank=True)
    registrado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['processo', 'fornecedor'], name='rhmun_proc_fornec_unique')]


class PropostaMunicipal(ContratacaoPublicaRecord):
    fornecedor_processo = models.ForeignKey(FornecedorProcessoMunicipal, on_delete=models.PROTECT, related_name='propostas')
    numero = models.CharField(max_length=60)
    data_envio = models.DateTimeField(null=True, blank=True)
    observacoes = models.TextField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['fornecedor_processo', 'numero'], name='rhmun_proposta_fornec_num')]


class ItemPropostaMunicipal(ContratacaoPublicaRecord):
    proposta = models.ForeignKey(PropostaMunicipal, on_delete=models.PROTECT, related_name='itens')
    item_processo = models.ForeignKey(ItemContratacaoMunicipal, on_delete=models.PROTECT, related_name='propostas')
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    quantidade = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    classificacao = models.PositiveSmallIntegerField(null=True, blank=True)
    vencedor = models.BooleanField(default=False)
    observacao = models.TextField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['proposta', 'item_processo'], name='rhmun_prop_item_unique')]
    def clean(self):
        super().clean()
        if self.proposta_id and self.item_processo_id and self.proposta.fornecedor_processo.processo_id != self.item_processo.processo_id:
            raise ValidationError({'item_processo': 'A proposta e o item devem pertencer ao mesmo processo.'})
        if self.vencedor and self.item_processo_id and self.item_processo.processo.status not in {
            ProcessoContratacaoMunicipal.Status.EM_JULGAMENTO,
            ProcessoContratacaoMunicipal.Status.EM_HABILITACAO,
        }:
            raise ValidationError({'vencedor': 'O julgamento de propostas só pode ser registrado na etapa de julgamento/habilitação.'})
        if self.vencedor and self.item_processo_id and ItemPropostaMunicipal.objects.filter(
            item_processo_id=self.item_processo_id, vencedor=True,
        ).exclude(pk=self.pk).exists():
            raise ValidationError({'vencedor': 'O item já possui proposta vencedora; registre recurso ou reabra o julgamento por fluxo auditado.'})


class AtaRegistroPrecosMunicipal(ContratacaoPublicaRecord):
    class Status(models.TextChoices):
        VIGENTE = 'VIGENTE', 'Vigente'
        SUSPENSA = 'SUSPENSA', 'Suspensa'
        ENCERRADA = 'ENCERRADA', 'Encerrada'
    numero = models.CharField(max_length=60)
    exercicio = models.PositiveSmallIntegerField()
    processo = models.ForeignKey(ProcessoContratacaoMunicipal, on_delete=models.PROTECT, related_name='atas')
    fornecedor = models.ForeignKey('gestao.Fornecedor', on_delete=models.PROTECT, related_name='atas_publicas')
    inicio_vigencia = models.DateField()
    fim_vigencia = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VIGENTE)
    documento_referencia = models.CharField(max_length=240, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='atas_registro_precos_criadas')
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'exercicio', 'numero'], name='rhmun_ata_num_org')]
    def clean(self):
        super().clean()
        if self.processo_id and self.processo.status != ProcessoContratacaoMunicipal.Status.HOMOLOGADO:
            raise ValidationError({'processo': 'A Ata exige processo homologado.'})
        if self.inicio_vigencia and self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({'fim_vigencia': 'Fim da vigência não pode anteceder início.'})


class ItemAtaRegistroPrecosMunicipal(ContratacaoPublicaRecord):
    ata = models.ForeignKey(AtaRegistroPrecosMunicipal, on_delete=models.PROTECT, related_name='itens')
    item_processo = models.ForeignKey(ItemContratacaoMunicipal, on_delete=models.PROTECT, related_name='itens_ata')
    quantidade_registrada = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    quantidade_utilizada = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    @property
    def saldo(self):
        return self.quantidade_registrada - self.quantidade_utilizada
    def clean(self):
        super().clean()
        if self.ata_id and self.item_processo_id and self.ata.processo_id != self.item_processo.processo_id:
            raise ValidationError({'item_processo': 'O item precisa pertencer ao processo de origem da Ata.'})
        if self.quantidade_utilizada > self.quantidade_registrada:
            raise ValidationError({'quantidade_utilizada': 'Utilização não pode exceder o saldo registrado.'})


class UtilizacaoAtaPrecosMunicipal(RegistroMunicipalImutavel):
    item_ata = models.ForeignKey(ItemAtaRegistroPrecosMunicipal, on_delete=models.PROTECT, related_name='utilizacoes')
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='utilizacoes_atas')
    quantidade = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    valor_total = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    referencia = models.CharField(max_length=120, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='utilizacoes_atas_criadas')
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'referencia'], condition=~Q(referencia=''), name='rhmun_ata_uso_ref_org')]


class ContratoPublicoMunicipal(ContratacaoPublicaRecord):
    class Status(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        VIGENTE = 'VIGENTE', 'Vigente'
        SUSPENSO = 'SUSPENSO', 'Suspenso'
        ENCERRADO = 'ENCERRADO', 'Encerrado'
        RESCINDIDO = 'RESCINDIDO', 'Rescindido'
    numero = models.CharField(max_length=60)
    exercicio = models.PositiveSmallIntegerField()
    processo = models.ForeignKey(ProcessoContratacaoMunicipal, on_delete=models.PROTECT, related_name='contratos')
    ata = models.ForeignKey(AtaRegistroPrecosMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='contratos')
    fornecedor = models.ForeignKey('gestao.Fornecedor', on_delete=models.PROTECT, related_name='contratos_publicos')
    secretaria = models.ForeignKey('rh_municipal.Secretaria', on_delete=models.PROTECT, related_name='contratos_publicos')
    unidade = models.ForeignKey('rh_municipal.UnidadeMunicipal', null=True, blank=True, on_delete=models.PROTECT, related_name='contratos_publicos')
    objeto = models.CharField(max_length=400)
    valor = models.DecimalField(max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    assinado_em = models.DateField(null=True, blank=True)
    inicio_vigencia = models.DateField(null=True, blank=True)
    fim_vigencia = models.DateField(null=True, blank=True)
    gestor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='contratos_publicos_gestor')
    fiscal = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='contratos_publicos_fiscal')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RASCUNHO)
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='contratos_publicos_criados')
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-exercicio', '-numero']
        constraints = [models.UniqueConstraint(fields=['organization', 'exercicio', 'numero'], name='rhmun_contrato_num_org')]
    def clean(self):
        super().clean()
        if self.processo_id and self.processo.status != ProcessoContratacaoMunicipal.Status.HOMOLOGADO:
            raise ValidationError({'processo': 'O contrato exige processo homologado.'})
        if self.ata_id and self.ata.fornecedor_id != self.fornecedor_id:
            raise ValidationError({'fornecedor': 'O fornecedor deve corresponder à Ata selecionada.'})
        if self.ata_id and self.ata.processo_id != self.processo_id:
            raise ValidationError({'ata': 'A Ata deve ter origem no processo selecionado.'})
        if self.inicio_vigencia and self.fim_vigencia and self.fim_vigencia < self.inicio_vigencia:
            raise ValidationError({'fim_vigencia': 'Fim da vigência não pode anteceder início.'})


class ItemContratoPublicoMunicipal(ContratacaoPublicaRecord):
    contrato = models.ForeignKey(ContratoPublicoMunicipal, on_delete=models.PROTECT, related_name='itens')
    item_processo = models.ForeignKey(ItemContratacaoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='itens_contrato')
    descricao = models.CharField(max_length=240)
    quantidade_contratada = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(Decimal('0.0001'))])
    quantidade_utilizada = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal('0'))])
    @property
    def saldo_quantidade(self):
        return self.quantidade_contratada - self.quantidade_utilizada
    def clean(self):
        super().clean()
        if self.quantidade_utilizada > self.quantidade_contratada:
            raise ValidationError({'quantidade_utilizada': 'Utilização não pode exceder a quantidade contratada.'})
        if self.item_processo_id and self.contrato_id and self.contrato.processo_id != self.item_processo.processo_id:
            raise ValidationError({'item_processo': 'O item não pertence ao processo do contrato.'})


class AditivoContratoPublico(RegistroMunicipalImutavel):
    class Tipo(models.TextChoices):
        ADITIVO = 'ADITIVO', 'Aditivo'
        APOSTILAMENTO = 'APOSTILAMENTO', 'Apostilamento'
        REAJUSTE = 'REAJUSTE', 'Reajuste'
        REPACTUACAO = 'REPACTUACAO', 'Repactuação'
        PRORROGACAO = 'PRORROGACAO', 'Prorrogação'
        ENCERRAMENTO = 'ENCERRAMENTO', 'Encerramento'
        RESCISAO = 'RESCISAO', 'Rescisão'
    contrato = models.ForeignKey(ContratoPublicoMunicipal, on_delete=models.PROTECT, related_name='aditivos')
    tipo = models.CharField(max_length=16, choices=Tipo.choices)
    numero = models.CharField(max_length=40)
    valor_anterior = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valor_novo = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    fim_vigencia_anterior = models.DateField(null=True, blank=True)
    fim_vigencia_novo = models.DateField(null=True, blank=True)
    fundamento = models.TextField(blank=True)
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='aditivos_contratos_publicos_criados')
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['contrato', 'numero'], name='rhmun_aditivo_contrato_num')]


class ExecucaoContratoPublico(RegistroMunicipalImutavel):
    class Tipo(models.TextChoices):
        ENTREGA = 'ENTREGA', 'Entrega'
        MEDICAO = 'MEDICAO', 'Medição'
        OCORRENCIA = 'OCORRENCIA', 'Ocorrência'
        FISCALIZACAO = 'FISCALIZACAO', 'Fiscalização'
    contrato = models.ForeignKey(ContratoPublicoMunicipal, on_delete=models.PROTECT, related_name='execucoes')
    item_contrato = models.ForeignKey(ItemContratoPublicoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='execucoes')
    tipo = models.CharField(max_length=16, choices=Tipo.choices)
    referencia = models.CharField(max_length=80, blank=True)
    data_referencia = models.DateField(default=timezone.localdate)
    quantidade = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    valor = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    descricao = models.TextField()
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='execucoes_contratuais_publicas_criadas')
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    def clean(self):
        super().clean()
        if self.item_contrato_id and self.contrato_id and self.item_contrato.contrato_id != self.contrato_id:
            raise ValidationError({'item_contrato': 'O item pertence a outro contrato.'})


class DocumentoContratacaoMunicipal(ContratacaoPublicaRecord):
    class Categoria(models.TextChoices):
        SOLICITACAO = 'SOLICITACAO', 'Solicitação'
        COTACAO = 'COTACAO', 'Cotação'
        EDITAL = 'EDITAL', 'Edital'
        PROPOSTA = 'PROPOSTA', 'Proposta'
        HABILITACAO = 'HABILITACAO', 'Habilitação'
        ATA = 'ATA', 'Ata'
        CONTRATO = 'CONTRATO', 'Contrato'
        ADITIVO = 'ADITIVO', 'Aditivo'
        CERTIDAO = 'CERTIDAO', 'Certidão'
        PARECER = 'PARECER', 'Parecer'
        HOMOLOGACAO = 'HOMOLOGACAO', 'Homologação'
        FISCALIZACAO = 'FISCALIZACAO', 'Fiscalização'
        OUTRO = 'OUTRO', 'Outro'
    solicitacao = models.ForeignKey(SolicitacaoCompra, null=True, blank=True, on_delete=models.PROTECT, related_name='documentos')
    processo = models.ForeignKey(ProcessoContratacaoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='documentos')
    contrato = models.ForeignKey(ContratoPublicoMunicipal, null=True, blank=True, on_delete=models.PROTECT, related_name='documentos')
    documento = models.ForeignKey('operacao.Documento', on_delete=models.PROTECT, related_name='vinculos_contratacao_publica')
    categoria = models.CharField(max_length=20, choices=Categoria.choices)
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.CheckConstraint(
            condition=(
                (Q(solicitacao__isnull=False) & Q(processo__isnull=True) & Q(contrato__isnull=True)) |
                (Q(solicitacao__isnull=True) & Q(processo__isnull=False) & Q(contrato__isnull=True)) |
                (Q(solicitacao__isnull=True) & Q(processo__isnull=True) & Q(contrato__isnull=False))
            ), name='rhmun_documento_contratacao_alvo'
        )]
    def clean(self):
        super().clean()
        if self.documento_id and self.documento.organization_id != self.organization_id:
            raise ValidationError({'documento': 'O arquivo pertence a outra organização.'})


class HistoricoContratacaoPublica(RegistroMunicipalImutavel):
    entidade = models.CharField(max_length=80)
    registro_id = models.PositiveBigIntegerField()
    evento = models.CharField(max_length=60)
    antes = models.JSONField(default=dict, blank=True)
    depois = models.JSONField(default=dict, blank=True)
    justificativa = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='historicos_contratacao_publica')
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        ordering = ['-criado_em', '-pk']

