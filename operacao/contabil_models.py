"""Models multi-tenant do módulo VERTYX Contábil (Carteira Fiscal & Operacional)."""
from __future__ import annotations

import re
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from gestao.models import RegistroImutavel, Validado


def only_digits(value: str) -> str:
    return re.sub(r'\D+', '', value or '')


def validar_cnpj_digitos(cnpj_raw: str) -> str:
    """Normaliza e valida os dígitos verificadores oficiais de um CNPJ (14 dígitos)."""
    digits = only_digits(cnpj_raw)
    if len(digits) != 14 or len(set(digits)) == 1:
        raise ValidationError('Informe um CNPJ válido com 14 dígitos.')
    pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma_1 = sum(int(digits[i]) * pesos_1[i] for i in range(12))
    resto_1 = soma_1 % 11
    dv1 = 0 if resto_1 < 2 else 11 - resto_1
    pesos_2 = [6] + pesos_1
    soma_2 = sum(int(digits[i]) * pesos_2[i] for i in range(13))
    resto_2 = soma_2 % 11
    dv2 = 0 if resto_2 < 2 else 11 - resto_2
    if int(digits[12]) != dv1 or int(digits[13]) != dv2:
        raise ValidationError('Dígitos verificadores do CNPJ inválidos.')
    return digits


def formatar_cnpj(digits: str) -> str:
    d = only_digits(digits)
    if len(d) != 14:
        return digits
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}'


class DepartamentoContabil(models.TextChoices):
    FISCAL = 'FISCAL', 'Fiscal'
    PESSOAL = 'PESSOAL', 'Pessoal / DP'
    CONTABIL = 'CONTABIL', 'Contábil'
    LEGALIZACAO = 'LEGALIZACAO', 'Societário / Legalização'


class RegimeTributarioCarteira(models.TextChoices):
    SIMPLES_NACIONAL = 'SIMPLES_NACIONAL', 'Simples Nacional'
    LUCRO_PRESUMIDO = 'LUCRO_PRESUMIDO', 'Lucro Presumido'
    LUCRO_REAL = 'LUCRO_REAL', 'Lucro Real'
    MEI = 'MEI', 'MEI'
    ISENTO_IMUNE = 'ISENTO_IMUNE', 'Isento / Imune'


class EmpresaCarteiraContabil(Validado):
    class SituacaoCadastral(models.TextChoices):
        ATIVA = 'ATIVA', 'Ativa'
        SUSPENSA = 'SUSPENSA', 'Suspensa'
        INAPTA = 'INAPTA', 'Inapta'
        BAIXADA = 'BAIXADA', 'Baixada'

    class SituacaoFiscal(models.TextChoices):
        REGULAR = 'REGULAR', 'Regular'
        ALERTA = 'ALERTA', 'Em Alerta'
        IRREGULAR = 'IRREGULAR', 'Irregular'
        CRITICA = 'CRITICA', 'Crítica'

    class TipoCertificado(models.TextChoices):
        NENHUM = 'NENHUM', 'Sem certificado cadastrado'
        A1 = 'A1', 'e-CNPJ A1 (Arquivo)'
        A3 = 'A3', 'e-CNPJ A3 (Token/Cartão)'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='empresas_carteira_contabil',
    )
    razao_social = models.CharField('Razão social', max_length=255)
    nome_fantasia = models.CharField('Nome fantasia', max_length=255, blank=True)
    cnpj = models.CharField('CNPJ (apenas dígitos)', max_length=14, db_index=True)
    inscricao_estadual = models.CharField(max_length=30, blank=True)
    inscricao_municipal = models.CharField(max_length=30, blank=True)
    regime_tributario = models.CharField(
        max_length=24,
        choices=RegimeTributarioCarteira.choices,
        default=RegimeTributarioCarteira.SIMPLES_NACIONAL,
    )
    situacao_cadastral = models.CharField(
        max_length=16,
        choices=SituacaoCadastral.choices,
        default=SituacaoCadastral.ATIVA,
    )
    situacao_fiscal = models.CharField(
        max_length=16,
        choices=SituacaoFiscal.choices,
        default=SituacaoFiscal.REGULAR,
    )
    responsavel_interno = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='carteira_empresas_responsaveis',
    )
    departamento_padrao = models.CharField(
        max_length=16,
        choices=DepartamentoContabil.choices,
        default=DepartamentoContabil.FISCAL,
    )
    email_contato = models.EmailField(blank=True)
    whatsapp_contato = models.CharField(max_length=25, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField(max_length=2, blank=True)

    certificado_tipo = models.CharField(
        max_length=10,
        choices=TipoCertificado.choices,
        default=TipoCertificado.NENHUM,
    )
    certificado_validade = models.DateField(null=True, blank=True)
    procuracao_ecac_ativa = models.BooleanField(default=False)
    procuracao_validade = models.DateField(null=True, blank=True)
    honorario_mensal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    observacoes = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['razao_social']
        verbose_name = 'Empresa da Carteira Contábil'
        verbose_name_plural = 'Empresas da Carteira Contábil'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'cnpj'],
                name='carteira_contabil_cnpj_por_org',
            )
        ]

    def __str__(self):
        return f'{self.razao_social} ({self.cnpj_formatado})'

    @property
    def cnpj_formatado(self) -> str:
        return formatar_cnpj(self.cnpj)

    @property
    def dias_certificado(self) -> int | None:
        if not self.certificado_validade:
            return None
        return (self.certificado_validade - timezone.localdate()).days

    @property
    def dias_procuracao(self) -> int | None:
        if not self.procuracao_validade:
            return None
        return (self.procuracao_validade - timezone.localdate()).days

    def clean(self):
        super().clean()
        self.cnpj = validar_cnpj_digitos(self.cnpj)
        if self.uf:
            self.uf = self.uf.strip().upper()[:2]
        if self.cliente_id and self.cliente.organization_id != self.organization_id:
            raise ValidationError({'cliente': 'Cliente pertence a outra organização.'})


class CertidaoFiscalCarteira(Validado):
    class Esfera(models.TextChoices):
        FEDERAL = 'FEDERAL', 'Federal (RFB / PGFN)'
        ESTADUAL = 'ESTADUAL', 'Estadual (SEFAZ)'
        MUNICIPAL = 'MUNICIPAL', 'Municipal (ISS / Prefeitura)'
        TRABALHISTA = 'TRABALHISTA', 'Trabalhista (CNDT)'
        FGTS = 'FGTS', 'Regularidade FGTS (CRF)'

    class Situacao(models.TextChoices):
        REGULAR = 'REGULAR', 'Negativa (Regular)'
        POSITIVA_EFEITO_NEGATIVA = 'POSITIVA_EFEITO_NEGATIVA', 'Positiva com efeito de negativa'
        IRREGULAR = 'IRREGULAR', 'Positiva / Irregular'
        VENCIDA = 'VENCIDA', 'Vencida'
        PENDENTE = 'PENDENTE', 'Verificar pendência'

    empresa = models.ForeignKey(
        EmpresaCarteiraContabil,
        on_delete=models.CASCADE,
        related_name='certidoes',
    )
    esfera = models.CharField(max_length=16, choices=Esfera.choices)
    situacao = models.CharField(
        max_length=28,
        choices=Situacao.choices,
        default=Situacao.REGULAR,
    )
    codigo_controle = models.CharField(max_length=80, blank=True)
    emitida_em = models.DateField(null=True, blank=True)
    validade = models.DateField()
    dias_alerta_antecedencia = models.PositiveIntegerField(default=15)
    fonte_consulta = models.CharField(max_length=100, default='Consulta operacional')
    arquivo = models.ForeignKey(
        'operacao.Documento',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='certidoes_carteira_contabil',
    )
    observacoes = models.TextField(blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['validade', 'esfera']
        verbose_name = 'Certidão Fiscal da Carteira'
        verbose_name_plural = 'Certidões Fiscais da Carteira'

    def __str__(self):
        return f'{self.get_esfera_display()} — {self.empresa.razao_social}'

    @property
    def dias_para_vencer(self) -> int:
        return (self.validade - timezone.localdate()).days

    @property
    def esta_vencida(self) -> bool:
        return self.dias_para_vencer < 0 or self.situacao == self.Situacao.VENCIDA

    @property
    def proxima_vencimento(self) -> bool:
        dias = self.dias_para_vencer
        return 0 <= dias <= int(self.dias_alerta_antecedencia or 15)

    @property
    def regular_vigente(self) -> bool:
        return (
            not self.esta_vencida
            and self.situacao in {self.Situacao.REGULAR, self.Situacao.POSITIVA_EFEITO_NEGATIVA}
        )

    def clean(self):
        super().clean()
        if self.empresa_id and self.empresa.organization_id != self.organization_id:
            raise ValidationError('Empresa pertence a outra organização.')
        if self.emitida_em and self.validade and self.validade < self.emitida_em:
            raise ValidationError({'validade': 'A validade não pode ser anterior à data de emissão.'})


class ObrigacaoFiscalCarteira(Validado):
    class Tipo(models.TextChoices):
        PGDAS = 'PGDAS', 'PGDAS-D'
        DCTFWEB = 'DCTFWEB', 'DCTFWeb'
        DAS = 'DAS', 'Guia DAS (Simples Nacional)'
        DARF = 'DARF', 'Guia DARF'
        PARCELAMENTO = 'PARCELAMENTO', 'Parcelamento Fiscal'
        SPED_FISCAL = 'SPED_FISCAL', 'SPED Fiscal (EFD ICMS/IPI)'
        SPED_CONTRIBUICOES = 'SPED_CONTRIBUICOES', 'EFD Contribuições'
        ECD_ECF = 'ECD_ECF', 'SPED Contábil (ECD / ECF)'
        ESOCIAL_FGTS = 'ESOCIAL_FGTS', 'eSocial / FGTS Digital'
        ISS_MUNICIPAL = 'ISS_MUNICIPAL', 'ISS / Declaração Municipal'

    class Natureza(models.TextChoices):
        DECLARACAO = 'DECLARACAO', 'Declaração / Obrigação Acessória'
        GUIA = 'GUIA', 'Guia de Recolhimento (Tributo)'
        PARCELAMENTO = 'PARCELAMENTO', ' Quota de Parcelamento'

    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        EM_APURACAO = 'EM_APURACAO', 'Em apuração'
        TRANSMITIDA = 'TRANSMITIDA', 'Transmitida / Entregue'
        PAGA = 'PAGA', 'Quitada / Paga'
        ATRASADA = 'ATRASADA', 'Em atraso'
        DISPENSADA = 'DISPENSADA', 'Sem movimento / Dispensada'

    empresa = models.ForeignKey(
        EmpresaCarteiraContabil,
        on_delete=models.CASCADE,
        related_name='obrigacoes',
    )
    tipo = models.CharField(max_length=24, choices=Tipo.choices)
    natureza = models.CharField(
        max_length=16,
        choices=Natureza.choices,
        default=Natureza.DECLARACAO,
    )
    competencia = models.CharField('Competência (MM/AAAA)', max_length=10)
    vencimento = models.DateField()
    valor_guia = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='obrigacoes_contabeis_responsaveis',
    )
    protocolo_recibo = models.CharField(max_length=100, blank=True)
    entregue_em = models.DateTimeField(null=True, blank=True)
    comprovante = models.ForeignKey(
        'operacao.Documento',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='obrigacoes_carteira_contabil',
    )
    observacoes = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['vencimento', 'empresa__razao_social']
        verbose_name = 'Obrigação Fiscal da Carteira'
        verbose_name_plural = 'Obrigações Fiscais da Carteira'

    def __str__(self):
        return f'{self.get_tipo_display()} ({self.competencia}) — {self.empresa.razao_social}'

    @property
    def concluida(self) -> bool:
        return self.status in {self.Status.TRANSMITIDA, self.Status.PAGA, self.Status.DISPENSADA}

    @property
    def esta_atrasada(self) -> bool:
        if self.concluida:
            return False
        return self.vencimento < timezone.localdate() or self.status == self.Status.ATRASADA

    def clean(self):
        super().clean()
        if self.empresa_id and self.empresa.organization_id != self.organization_id:
            raise ValidationError('Empresa pertence a outra organização.')


class PendenciaFiscalCarteira(Validado):
    class Prioridade(models.TextChoices):
        BAIXA = 'BAIXA', 'Baixa'
        MEDIA = 'MEDIA', 'Média'
        ALTA = 'ALTA', 'Alta'
        CRITICA = 'CRITICA', 'Crítica'

    class Status(models.TextChoices):
        ABERTO = 'ABERTO', 'Aberto'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        RESOLVIDO = 'RESOLVIDO', 'Resolvido'

    class EtapaFluxo(models.TextChoices):
        DETECTAR = 'DETECTAR', '01 · Detectar (Consulta)'
        DELEGAR = 'DELEGAR', '02 · Delegar (Responsável)'
        EXECUTAR = 'EXECUTAR', '03 · Executar (Tarefa)'
        COMUNICAR = 'COMUNICAR', '04 · Comunicar (Cliente)'
        RESOLVER = 'RESOLVER', '05 · Resolver (Evidência)'
        AUDITAR = 'AUDITAR', '06 · Auditar (Histórico)'

    codigo = models.CharField(max_length=24, db_index=True)
    empresa = models.ForeignKey(
        EmpresaCarteiraContabil,
        on_delete=models.CASCADE,
        related_name='pendencias',
    )
    titulo = models.CharField(max_length=200)
    descricao = models.TextField(blank=True)
    departamento = models.CharField(
        max_length=16,
        choices=DepartamentoContabil.choices,
        default=DepartamentoContabil.FISCAL,
    )
    prioridade = models.CharField(
        max_length=12,
        choices=Prioridade.choices,
        default=Prioridade.MEDIA,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ABERTO,
    )
    etapa_fluxo = models.CharField(
        max_length=16,
        choices=EtapaFluxo.choices,
        default=EtapaFluxo.DETECTAR,
    )
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pendencias_carteira_atribuidas',
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='pendencias_carteira_criadas',
    )
    prazo = models.DateField(null=True, blank=True)
    certidao_origem = models.ForeignKey(
        CertidaoFiscalCarteira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pendencias_geradas',
    )
    obrigacao_origem = models.ForeignKey(
        ObrigacaoFiscalCarteira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pendencias_geradas',
    )
    evidencia_resolucao = models.TextField(blank=True)
    anexo = models.ForeignKey(
        'operacao.Documento',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pendencias_carteira_contabil',
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    resolvido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Pendência Fiscal da Carteira'
        verbose_name_plural = 'Pendências Fiscais da Carteira'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'codigo'],
                name='pendencia_contabil_codigo_por_org',
            )
        ]

    def __str__(self):
        return f'{self.codigo} · {self.titulo}'

    @property
    def atrasada(self) -> bool:
        return bool(
            self.status != self.Status.RESOLVIDO
            and self.prazo
            and self.prazo < timezone.localdate()
        )

    def clean(self):
        super().clean()
        if self.empresa_id and self.empresa.organization_id != self.organization_id:
            raise ValidationError('Empresa pertence a outra organização.')


class ComunicacaoClienteContabil(Validado):
    class Canal(models.TextChoices):
        WHATSAPP = 'WHATSAPP', 'WhatsApp'
        EMAIL = 'EMAIL', 'E-mail'
        PORTAL = 'PORTAL', 'Portal do Empresário'

    class Tipo(models.TextChoices):
        AVISO_FISCAL = 'AVISO_FISCAL', 'Aviso de vencimento / guia'
        SOLICITACAO_DOC = 'SOLICITACAO_DOC', 'Solicitação de documentos'
        ALERTA_PENDENCIA = 'ALERTA_PENDENCIA', 'Alerta de pendência / certidão'
        CONFIRMACAO_ENTREGA = 'CONFIRMACAO_ENTREGA', 'Comprovante de entrega'

    empresa = models.ForeignKey(
        EmpresaCarteiraContabil,
        on_delete=models.CASCADE,
        related_name='comunicacoes',
    )
    pendencia = models.ForeignKey(
        PendenciaFiscalCarteira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comunicacoes',
    )
    canal = models.CharField(max_length=12, choices=Canal.choices, default=Canal.WHATSAPP)
    tipo = models.CharField(max_length=24, choices=Tipo.choices, default=Tipo.SOLICITACAO_DOC)
    destinatario = models.CharField(max_length=180)
    assunto = models.CharField(max_length=200)
    documento_solicitado = models.CharField(max_length=200, blank=True)
    mensagem = models.TextField()
    token_confirmacao = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='comunicacoes_contabeis_enviadas',
    )
    enviado_em = models.DateTimeField(auto_now_add=True)
    confirmado_recebimento = models.BooleanField(default=False)
    confirmado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-enviado_em']
        verbose_name = 'Comunicação Contábil com Cliente'
        verbose_name_plural = 'Comunicações Contábeis com Clientes'

    def __str__(self):
        return f'{self.get_canal_display()} → {self.empresa.razao_social}: {self.assunto}'

    @property
    def whatsapp_link(self) -> str:
        from urllib.parse import quote
        phone = only_digits(self.destinatario or self.empresa.whatsapp_contato)
        if phone and not phone.startswith('55') and len(phone) in {10, 11}:
            phone = f'55{phone}'
        texto = f'*{self.assunto}*\nEmpresa: {self.empresa.razao_social} ({self.empresa.cnpj_formatado})\n\n{self.mensagem}'
        if self.documento_solicitado:
            texto += f'\n\n📎 Documento solicitado: {self.documento_solicitado}'
        return f'https://wa.me/{phone}?text={quote(texto)}' if phone else f'https://wa.me/?text={quote(texto)}'


class EventoHistoricoContabil(RegistroImutavel):
    class TipoEvento(models.TextChoices):
        CADASTRO = 'CADASTRO', 'Cadastro / Atualização Cadastral'
        OCORRENCIA = 'OCORRENCIA', 'Ocorrência Registrada'
        PENDENCIA_DETECTADA = 'PENDENCIA_DETECTADA', '01 · Pendência Detectada'
        PENDENCIA_DELEGADA = 'PENDENCIA_DELEGADA', '02 · Responsável Delegado'
        TAREFA_EXECUCAO = 'TAREFA_EXECUCAO', '03 · Tarefa em Execução'
        COMUNICACAO_CLIENTE = 'COMUNICACAO_CLIENTE', '04 · Comunicação ao Cliente'
        RECEBIMENTO_CONFIRMADO = 'RECEBIMENTO_CONFIRMADO', '04b · Recebimento Confirmado'
        PENDENCIA_RESOLVIDA = 'PENDENCIA_RESOLVIDA', '05 · Pendência Resolvida'
        AUDITORIA_CONCLUIDA = 'AUDITORIA_CONCLUIDA', '06 · Auditoria Consolidada'
        COMENTARIO = 'COMENTARIO', 'Comentário / Anexo'
        CERTIDAO = 'CERTIDAO', 'Certidão Registrada / Atualizada'
        OBRIGACAO = 'OBRIGACAO', 'Obrigação / Guia Atualizada'

    empresa = models.ForeignKey(
        EmpresaCarteiraContabil,
        on_delete=models.PROTECT,
        related_name='historico',
    )
    pendencia = models.ForeignKey(
        PendenciaFiscalCarteira,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='historico',
    )
    tipo_evento = models.CharField(max_length=28, choices=TipoEvento.choices)
    descricao = models.TextField()
    anexo = models.ForeignKey(
        'operacao.Documento',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='eventos_historico_contabil',
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='eventos_contabeis_registrados',
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em', '-id']
        verbose_name = 'Evento de Histórico Contábil'
        verbose_name_plural = 'Eventos de Histórico Contábil'

    def __str__(self):
        return f'{self.get_tipo_evento_display()} — {self.empresa.razao_social}'


class PreAnaliseComercialCNPJ(Validado):
    class Oportunidade(models.TextChoices):
        ALTA = 'ALTA', 'Alta oportunidade comercial'
        MEDIA = 'MEDIA', 'Média oportunidade'
        BAIXA = 'BAIXA', 'Baixa / Monitoramento'

    cnpj = models.CharField(max_length=14, db_index=True)
    razao_social_identificada = models.CharField(max_length=255)
    regime_estimado = models.CharField(
        max_length=24,
        choices=RegimeTributarioCarteira.choices,
        default=RegimeTributarioCarteira.SIMPLES_NACIONAL,
    )
    uf = models.CharField(max_length=2, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    pendencias_conhecidas = models.TextField(blank=True)
    diagnostico_inicial = models.TextField()
    nivel_oportunidade = models.CharField(
        max_length=10,
        choices=Oportunidade.choices,
        default=Oportunidade.ALTA,
    )
    convertido_empresa = models.ForeignKey(
        EmpresaCarteiraContabil,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pre_analises_origem',
    )
    consultado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='pre_analises_contabeis',
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Pré-Análise Comercial de CNPJ'
        verbose_name_plural = 'Pré-Análises Comerciais de CNPJ'

    @property
    def cnpj_formatado(self) -> str:
        return formatar_cnpj(self.cnpj)

    def clean(self):
        super().clean()
        self.cnpj = validar_cnpj_digitos(self.cnpj)
