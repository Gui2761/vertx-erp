"""Models multi-tenant do módulo VERTYX Licita (Radar PNCP, Checklist de Edital, Funil de Gestão Comercial)."""
from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from gestao.models import RegistroImutavel, Validado

ZERO = Decimal('0.00')


class RadarFiltroPNCP(Validado):
    """Filtro de busca e monitoramento contínuo de oportunidades na API do PNCP."""
    nome = models.CharField('Nome do Radar', max_length=120)
    palavras_chave = models.TextField(
        'Palavras-chave (separadas por vírgula)',
        help_text='Ex: engenharia clínica, raio-x, monitor multiparamétrico, autoclave, manutenção hospitalar, leito',
    )
    ufs = models.CharField(
        'Estados de Interesse (UFs)',
        max_length=60,
        default='SE, AL, BA',
        help_text='Siglas de UFs separadas por vírgula (ex: SE, AL, BA)',
    )
    modalidades_pncp = models.CharField(
        'Códigos de Modalidade PNCP',
        max_length=60,
        default='6, 8, 4',
        help_text='6 = Pregão Eletrônico, 8 = Dispensa de Licitação, 4 = Concorrência Eletrônica',
    )
    valor_minimo = models.DecimalField('Valor Estimado Mínimo (R$)', max_digits=14, decimal_places=2, default=ZERO)
    valor_maximo = models.DecimalField('Valor Estimado Máximo (R$)', max_digits=14, decimal_places=2, null=True, blank=True)
    ativo = models.BooleanField('Radar Ativo', default=True)
    ultima_sincronizacao = models.DateTimeField('Última Sincronização com PNCP', null=True, blank=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} · UFs: {self.ufs}'

    def lista_palavras_chave(self) -> list[str]:
        return [p.strip().lower() for p in (self.palavras_chave or '').split(',') if p.strip()]

    def lista_ufs(self) -> list[str]:
        return [u.strip().upper() for u in (self.ufs or '').split(',') if u.strip()]

    def lista_modalidades_int(self) -> list[int]:
        res = []
        for m in (self.modalidades_pncp or '').split(','):
            cleaned = m.strip()
            if cleaned.isdigit():
                res.append(int(cleaned))
        return res or [6, 8, 4]


class OportunidadeLicitacao(Validado):
    """Contratação pública capturada pelo PNCP ou cadastrada diretamente no funil comercial."""
    class EtapaFunil(models.TextChoices):
        ENCONTRADA = 'ENCONTRADA', '1. Encontradas'
        EM_ANALISE = 'EM_ANALISE', '2. Em Análise'
        DOCUMENTACAO = 'DOCUMENTACAO', '3. Documentação'
        PROPOSTA = 'PROPOSTA', '4. Propostas'
        EM_DISPUTA = 'EM_DISPUTA', '5. Em Disputa'
        VENCIDA = 'VENCIDA', '6. Vencidas'
        PERDIDA = 'PERDIDA', 'Perdida'
        DESERTA_CANCELADA = 'DESERTA', 'Cancelada / Deserta'

    numero_controle_pncp = models.CharField(
        'Número de Controle PNCP',
        max_length=120,
        db_index=True,
        help_text='Identificador único universal gerado pela API do PNCP (CNPJ-seq/ano)',
    )
    orgao_nome = models.CharField('Órgão Comprador', max_length=255)
    orgao_cnpj = models.CharField('CNPJ do Órgão', max_length=20, blank=True)
    uf = models.CharField('UF', max_length=2, default='SE')
    municipio = models.CharField('Município', max_length=150, blank=True)
    modalidade_nome = models.CharField('Modalidade', max_length=100, default='Pregão Eletrônico')
    numero_edital = models.CharField('Nº Edital / Processo', max_length=100, blank=True)
    objeto = models.TextField('Objeto da Contratação')
    valor_total_estimado = models.DecimalField(
        'Valor Total Estimado (R$)',
        max_digits=14,
        decimal_places=2,
        default=ZERO,
    )
    data_publicacao_pncp = models.DateField('Data de Publicação', null=True, blank=True)
    data_abertura_proposta = models.DateTimeField('Abertura da Sessão / Proposta', null=True, blank=True)
    link_fonte_pncp = models.URLField('Link Oficial PNCP / Portal de Compras', max_length=500, blank=True)

    etapa = models.CharField(max_length=20, choices=EtapaFunil.choices, default=EtapaFunil.ENCONTRADA)
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='licitacoes_responsavel',
    )
    radar_origem = models.ForeignKey(
        RadarFiltroPNCP,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='oportunidades',
    )

    # Integração nativa com Market & Pricing
    simulacao_pricing = models.OneToOneField(
        'operacao.SimulacaoLanceEdital',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='licitacao_vinculada',
        help_text='Motor de cálculo com piso sustentável de lance',
    )

    # Resultados e Concorrência Homologada
    vencedor_homologado = models.CharField('Vencedor Homologado', max_length=255, blank=True)
    vencedor_cnpj = models.CharField('CNPJ Vencedor', max_length=20, blank=True)
    valor_homologado = models.DecimalField(
        'Valor Homologado Final (R$)',
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    desconto_homologado_pct = models.DecimalField(
        '% Desconto s/ Estimativa',
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    observacoes_estrategicas = models.TextField('Anotações Estratégicas e Diretrizes', blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['organization', 'numero_controle_pncp'], name='licita_pncp_org_unique'),
        ]
        ordering = ['-data_publicacao_pncp', '-criado_em']

    def __str__(self):
        return f'{self.numero_edital or self.numero_controle_pncp} · {self.orgao_nome} ({self.uf}) · R$ {self.valor_total_estimado:,.2f}'

    @property
    def dias_para_abertura(self) -> int | None:
        if not self.data_abertura_proposta:
            return None
        hoje = timezone.now()
        delta = self.data_abertura_proposta - hoje
        return delta.days

    @property
    def total_requisitos(self) -> int:
        return self.requisitos.count()

    @property
    def requisitos_atendidos(self) -> int:
        return self.requisitos.filter(status='CONFORME').count()

    @property
    def requisitos_pendentes(self) -> int:
        return self.requisitos.filter(status='PENDENTE').count()

    @property
    def requisitos_impedimentos(self) -> int:
        return self.requisitos.filter(status='IMPEDIMENTO').count()


class AnaliseEditalRequisito(Validado):
    """Requisito extraído do edital com citação exata de página e trecho original (Checklist Auditável)."""
    class Categoria(models.TextChoices):
        OBJETO = 'OBJETO', 'Objeto & Especificações Técnicas'
        HABILITACAO_JURIDICA = 'HAB_JURIDICA', 'Habilitação Jurídica'
        REGULARIDADE_FISCAL = 'REG_FISCAL', 'Regularidade Fiscal & Trabalhista (CNDs)'
        QUALIFICACAO_TECNICA = 'QUAL_TECNICA', 'Qualificação Técnica & Atestados'
        QUALIFICACAO_FINANCEIRA = 'QUAL_FINANCEIRA', 'Qualificação Econômico-Financeira'
        PRAZOS_CONDICOES = 'PRAZOS', 'Prazos de Entrega & Condições de Pagamento'
        RISCOS_PENALIDADES = 'RISCOS', 'Riscos, Garantias Contratuais & Multas'

    class StatusConformidade(models.TextChoices):
        CONFORME = 'CONFORME', 'Conforme (Atendido)'
        PENDENTE = 'PENDENTE', 'Pendente de Providência'
        IMPEDIMENTO = 'IMPEDIMENTO', 'Impedimento Crítico'
        NAO_APLICAVEL = 'NA', 'Não Aplicável'

    oportunidade = models.ForeignKey(
        OportunidadeLicitacao,
        on_delete=models.CASCADE,
        related_name='requisitos',
    )
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.REGULARIDADE_FISCAL)
    titulo = models.CharField('Título do Requisito / Exigência', max_length=200)
    descricao_detalhada = models.TextField('Descrição da Exigência')

    # Rastreabilidade Rígida: Citação obrigatória do Edital
    pagina_edital = models.PositiveIntegerField('Página do Edital', default=1)
    trecho_citado = models.TextField('Trecho Original do Edital (Citação Direta)')

    # Vínculo com documento ou certidão disponível no ERP
    documento_erp = models.ForeignKey(
        'operacao.Documento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='Documento ou certidão comprobatória existente no repositório do ERP',
    )

    status = models.CharField(max_length=20, choices=StatusConformidade.choices, default=StatusConformidade.PENDENTE)
    conferido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='Revisão humana obrigatória',
    )
    conferido_em = models.DateTimeField('Data da Conferência', null=True, blank=True)
    parecer_conferencia = models.TextField('Parecer do Revisor', blank=True)

    class Meta:
        ordering = ['categoria', 'pagina_edital', 'pk']

    def __str__(self):
        return f'pág. {self.pagina_edital} · [{self.get_categoria_display()}] {self.titulo}: {self.get_status_display()}'


class HistoricoLicitacaoEvento(RegistroImutavel):
    """Trilha imutável de eventos das licitações (mudanças de etapa, conferências e simulações)."""
    oportunidade = models.ForeignKey(
        OportunidadeLicitacao,
        on_delete=models.CASCADE,
        related_name='historico_eventos',
    )
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tipo_evento = models.CharField(max_length=50)
    etapa_anterior = models.CharField(max_length=20, blank=True)
    etapa_nova = models.CharField(max_length=20, blank=True)
    descricao = models.CharField(max_length=255)
    dados_adicionais = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'[{self.criado_em:%d/%m/%Y %H:%M}] {self.oportunidade.numero_edital}: {self.descricao}'
