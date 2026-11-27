"""Models multi-tenant do módulo VERTYX Market & Pricing (Formação de Preço, Hora Técnica e Piso de Lance)."""
from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from gestao.models import RegistroImutavel, Validado

ZERO = Decimal('0.00')
CEM = Decimal('100.00')


class CentroCustoRateio(Validado):
    """Centros de custo operacionais do ERP para rateio de despesas fixas."""
    class CodigoCentro(models.TextChoices):
        LOJA = 'LOJA', 'Loja (Produtos & Balcão)'
        ASSISTENCIA = 'ASSISTENCIA', 'Assistência Técnica (Serviços)'
        COMPARTILHADO = 'COMPARTILHADO', 'Compartilhado (Administrativo / Gestão)'

    codigo = models.CharField(max_length=20, choices=CodigoCentro.choices)
    nome = models.CharField(max_length=100)
    percentual_rateio = models.DecimalField(
        'Percentual de Rateio (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('33.33'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(CEM)],
    )
    custo_fixo_mensal = models.DecimalField(
        'Custo Fixo Mensal (R$)',
        max_digits=14,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    observacoes = models.TextField('Observações e Composição', blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['organization', 'codigo'], name='pricing_cc_org_codigo_unique'),
        ]
        ordering = ['codigo']

    def __str__(self):
        return f'{self.get_codigo_display()} · {self.percentual_rateio}% (R$ {self.custo_fixo_mensal:,.2f})'


class CalculadoraPrecoProduto(Validado):
    """Motor de cálculo dinâmico de Preço-Alvo, Preço de Equilíbrio e Margem Reversa."""
    nome_produto = models.CharField('Nome / Descrição do Produto', max_length=200)
    peca = models.ForeignKey(
        'gestao.Peca',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='calculos_pricing',
        help_text='Vínculo opcional ao catálogo de peças/produtos do ERP',
    )
    sku_referencia = models.CharField('SKU / Código Referência', max_length=80, blank=True)
    marca = models.CharField('Marca / Fabricante', max_length=100, blank=True)
    modelo = models.CharField('Modelo', max_length=100, blank=True)

    # Custos Diretos
    custo_aquisicao = models.DecimalField(
        'Custo de Aquisição (R$)',
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(ZERO)],
    )
    custo_frete_seguro = models.DecimalField(
        'Frete & Seguro na Compra (R$)',
        max_digits=14,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )

    # Percentuais sobre a Venda
    percentual_despesas_fixas = models.DecimalField(
        'Despesas Fixas (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )
    percentual_tributos = models.DecimalField(
        'Tributos sobre Venda (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('8.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )
    percentual_outras_variaveis = models.DecimalField(
        'Outras Taxas Variáveis / Comissões (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )
    percentual_margem_desejada = models.DecimalField(
        'Margem de Lucro Desejada (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )

    observacoes = models.TextField('Memória de Cálculo & Estratégia', blank=True)

    class Meta:
        ordering = ['nome_produto']

    def __str__(self):
        return f'{self.nome_produto} · Alvo: R$ {self.preco_alvo:,.2f}'

    @property
    def custo_base(self) -> Decimal:
        return (self.custo_aquisicao or ZERO) + (self.custo_frete_seguro or ZERO)

    @property
    def soma_deducoes_equilibrio_pct(self) -> Decimal:
        return (self.percentual_despesas_fixas or ZERO) + (self.percentual_tributos or ZERO) + (self.percentual_outras_variaveis or ZERO)

    @property
    def soma_deducoes_alvo_pct(self) -> Decimal:
        return self.soma_deducoes_equilibrio_pct + (self.percentual_margem_desejada or ZERO)

    @property
    def preco_equilibrio(self) -> Decimal:
        """Break-even: Preço mínimo para não ter prejuízo (Margem = 0%)."""
        divisor = Decimal('1.00') - (self.soma_deducoes_equilibrio_pct / CEM)
        if divisor <= ZERO:
            return ZERO
        return (self.custo_base / divisor).quantize(Decimal('0.01'))

    @property
    def preco_alvo(self) -> Decimal:
        """Preço de venda com a margem desejada."""
        divisor = Decimal('1.00') - (self.soma_deducoes_alvo_pct / CEM)
        if divisor <= ZERO:
            return ZERO
        return (self.custo_base / divisor).quantize(Decimal('0.01'))

    def calcular_margem_cenario(self, preco_mercado: Decimal) -> Decimal:
        """Calcula a margem real de lucro obtida em um preço arbitrário de mercado."""
        if not preco_mercado or preco_mercado <= ZERO:
            return ZERO
        custo_relativo = (self.custo_base / preco_mercado) * CEM
        margem_pct = CEM - custo_relativo - self.soma_deducoes_equilibrio_pct
        return margem_pct.quantize(Decimal('0.01'))

    def clean(self):
        super().clean()
        if self.soma_deducoes_alvo_pct >= CEM:
            raise ValidationError('A soma de despesas fixas, tributos, variáveis e margem deve ser estritamente inferior a 100%.')
        if self.soma_deducoes_equilibrio_pct >= CEM:
            raise ValidationError('A soma de despesas fixas, tributos e variáveis deve ser inferior a 100%.')


class CalculadoraHoraTecnica(Validado):
    """Calculadora da hora técnica faturável por especialidade da assistência técnica."""
    especialidade = models.CharField('Especialidade / Segmento Técnico', max_length=150)
    num_tecnicos = models.PositiveIntegerField('Número de Técnicos Dedicados', default=2)
    dias_uteis_mes = models.PositiveIntegerField('Dias Úteis no Mês', default=22)
    horas_dia = models.DecimalField('Horas por Dia', max_digits=4, decimal_places=2, default=Decimal('8.00'))
    percentual_ocupacao_faturavel = models.DecimalField(
        '% Ocupação Faturável',
        max_digits=5,
        decimal_places=2,
        default=Decimal('65.00'),
        validators=[MinValueValidator(Decimal('1.00')), MaxValueValidator(CEM)],
        help_text='Percentual do tempo efetivamente faturável (ex: 65% faturável, 35% deslocamento/relatórios)',
    )
    custo_mensal_centro = models.DecimalField(
        'Custo Mensal do Centro Técnico (R$)',
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(ZERO)],
        help_text='Folha, encargos, RT, galpão, ferramentas, calibração e veículos dedicados',
    )
    percentual_tributos = models.DecimalField(
        'Tributos sobre Serviços (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('12.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )
    percentual_margem = models.DecimalField(
        'Margem de Lucro Desejada (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('25.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )

    class Meta:
        ordering = ['especialidade']

    def __str__(self):
        return f'{self.especialidade} · Custo/h: R$ {self.custo_por_hora:,.2f} · Sugerido: R$ {self.hora_sugerida:,.2f}'

    @property
    def horas_faturaveis_mes(self) -> Decimal:
        base = Decimal(self.num_tecnicos) * Decimal(self.dias_uteis_mes) * (self.horas_dia or ZERO)
        return (base * (self.percentual_ocupacao_faturavel / CEM)).quantize(Decimal('0.01'))

    @property
    def custo_por_hora(self) -> Decimal:
        hf = self.horas_faturaveis_mes
        if hf <= ZERO:
            return ZERO
        return ((self.custo_mensal_centro or ZERO) / hf).quantize(Decimal('0.01'))

    @property
    def hora_sugerida(self) -> Decimal:
        divisor = Decimal('1.00') - ((self.percentual_tributos + self.percentual_margem) / CEM)
        if divisor <= ZERO:
            return ZERO
        return (self.custo_por_hora / divisor).quantize(Decimal('0.01'))

    def clean(self):
        super().clean()
        if (self.percentual_tributos + self.percentual_margem) >= CEM:
            raise ValidationError('A soma de tributos e margem da hora técnica deve ser menor que 100%.')


class PesquisaPrecoConcorrente(Validado):
    """Registro de preços praticados no mercado regional (varejo, atacado ou atas/contratos públicos)."""
    class CanalPreco(models.TextChoices):
        VAREJO = 'VAREJO', 'Varejo / Loja Local'
        ATACADO = 'ATACADO', 'Distribuidor / Atacado'
        CONTRATO_PUBLICO = 'CONTRATO_PUBLICO', 'Homologação / Contrato Público'
        INTERNET = 'INTERNET', 'E-commerce / Web'

    produto_calculo = models.ForeignKey(
        CalculadoraPrecoProduto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesquisas_concorrentes',
    )
    descricao_item = models.CharField('Item / Equipamento Pesquisado', max_length=200)
    concorrente_fornecedor = models.CharField('Concorrente / Loja / Órgão', max_length=150)
    municipio = models.CharField('Município', max_length=100, default='Aracaju')
    uf = models.CharField('UF', max_length=2, default='SE')
    canal = models.CharField(max_length=20, choices=CanalPreco.choices, default=CanalPreco.VAREJO)
    preco_identificado = models.DecimalField(
        'Preço Coletado (R$)',
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    data_coleta = models.DateField('Data da Coleta', default=timezone.localdate)
    link_fonte = models.URLField('Fonte / Link / Ata', blank=True, max_length=400)
    observacoes = models.TextField('Detalhes do anúncio ou contrato', blank=True)

    @property
    def margem_cenario(self) -> Decimal | None:
        if not self.produto_calculo:
            return None
        return self.produto_calculo.calcular_margem_cenario(self.preco_identificado)

    class Meta:
        ordering = ['-data_coleta', 'preco_identificado']

    def __str__(self):
        return f'{self.descricao_item} · {self.concorrente_fornecedor} ({self.municipio}/{self.uf}): R$ {self.preco_identificado:,.2f}'


class SimulacaoLanceEdital(Validado):
    """Simulador de Lances para Licitações com Trava de Piso Sustentável e Alerta de Prejuízo."""
    titulo_edital = models.CharField('Identificador / Edital', max_length=150)
    orgao_comprador = models.CharField('Órgão / Prefeitura Compradora', max_length=180)
    objeto_resumo = models.TextField('Objeto / Lote')

    # Custos Diretos Compostos
    custos_pecas_equipamentos = models.DecimalField(
        'Custos com Peças & Equipamentos (R$)',
        max_digits=14,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    horas_tecnicas_estimadas = models.DecimalField(
        'Horas Técnicas Estimadas',
        max_digits=8,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    calculadora_hora = models.ForeignKey(
        CalculadoraHoraTecnica,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='Calculadora de hora técnica de referência',
    )
    custo_hora_aplicado = models.DecimalField(
        'Custo por Hora Aplicado (R$)',
        max_digits=10,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    custos_deslocamento_logistica = models.DecimalField(
        'Deslocamento & Diárias (R$)',
        max_digits=14,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    outras_despesas_diretas = models.DecimalField(
        'Outras Despesas Diretas (R$)',
        max_digits=14,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    percentual_taxa_risco = models.DecimalField(
        'Taxa de Risco / Imprevistos (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('5.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('50.00'))],
    )

    # Margens e Impostos
    percentual_tributos = models.DecimalField(
        'Tributos sobre Faturamento (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('8.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )
    percentual_margem_minima = models.DecimalField(
        'Margem de Lucro Desejada (%)',
        max_digits=5,
        decimal_places=2,
        default=Decimal('15.00'),
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('99.00'))],
    )

    # Lance Atualmente Simulado na Disputa
    lance_simulado_disputa = models.DecimalField(
        'Lance Simulado na Disputa (R$)',
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(ZERO)],
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'{self.titulo_edital} · Piso: R$ {self.piso_sem_lucro:,.2f} · Lance: R$ {(self.lance_simulado_disputa or ZERO):,.2f}'

    @property
    def custo_horas_total(self) -> Decimal:
        custo_h = self.custo_hora_aplicado
        if (not custo_h or custo_h <= ZERO) and self.calculadora_hora:
            custo_h = self.calculadora_hora.custo_por_hora
        return ((self.horas_tecnicas_estimadas or ZERO) * (custo_h or ZERO)).quantize(Decimal('0.01'))

    @property
    def subtotal_custos_diretos(self) -> Decimal:
        return (
            (self.custos_pecas_equipamentos or ZERO)
            + self.custo_horas_total
            + (self.custos_deslocamento_logistica or ZERO)
            + (self.outras_despesas_diretas or ZERO)
        )

    @property
    def valor_taxa_risco(self) -> Decimal:
        return (self.subtotal_custos_diretos * ((self.percentual_taxa_risco or ZERO) / CEM)).quantize(Decimal('0.01'))

    @property
    def custo_total_composto(self) -> Decimal:
        return self.subtotal_custos_diretos + self.valor_taxa_risco

    @property
    def piso_sem_lucro(self) -> Decimal:
        """Piso sustentável mínimo: Não gerar prejuízo operacional."""
        divisor = Decimal('1.00') - ((self.percentual_tributos or ZERO) / CEM)
        if divisor <= ZERO:
            return ZERO
        return (self.custo_total_composto / divisor).quantize(Decimal('0.01'))

    @property
    def lance_com_margem(self) -> Decimal:
        """Preço ideal de lance com a margem desejada."""
        deducao = (self.percentual_tributos or ZERO) + (self.percentual_margem_minima or ZERO)
        divisor = Decimal('1.00') - (deducao / CEM)
        if divisor <= ZERO:
            return ZERO
        return (self.custo_total_composto / divisor).quantize(Decimal('0.01'))

    def calcular_lucro_lance(self, lance: Decimal | None = None) -> Decimal:
        valor_lance = lance if lance is not None else self.lance_simulado_disputa
        if not valor_lance or valor_lance <= ZERO:
            return ZERO
        receita_liquida = valor_lance * (Decimal('1.00') - ((self.percentual_tributos or ZERO) / CEM))
        return (receita_liquida - self.custo_total_composto).quantize(Decimal('0.01'))

    @property
    def lucro_lance_com_margem(self) -> Decimal:
        return self.calcular_lucro_lance(self.lance_com_margem)

    @property
    def lance_abaixo_do_piso(self) -> bool:
        """Guardrail: Detecta se o lance simulado gerará prejuízo financeiro."""
        if not self.lance_simulado_disputa or self.lance_simulado_disputa <= ZERO:
            return False
        return self.lance_simulado_disputa < self.piso_sem_lucro


class HistoricoCalculoPreco(RegistroImutavel):
    """Trilha imutável de auditoria de precificações, revisões e simulações de lances."""
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tipo_registro = models.CharField(max_length=50)
    descricao = models.CharField(max_length=255)
    detalhes_json = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'[{self.criado_em:%d/%m/%Y %H:%M}] {self.tipo_registro} por {self.usuario}: {self.descricao}'
