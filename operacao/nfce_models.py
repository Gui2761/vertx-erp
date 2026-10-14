"""NFC-e-only extensions of the existing fiscal graph. No secret columns."""
import re
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from gestao.models import RegistroImutavel
from .fiscal_models import CadastroFiscal


def parametros_nfce(value):
    allowed = {'icms_codigo', 'icms_modalidade_bc', 'icms_aliquota', 'pis_codigo',
               'pis_aliquota', 'cofins_codigo', 'cofins_aliquota', 'gtin_ausente',
               'cest_aplicavel', 'rtc_aplicavel', 'rtc_fundamento', 'base_tributaria',
               'ibs_cst', 'ibs_classificacao', 'ibs_uf_aliquota', 'ibs_mun_aliquota', 'cbs_aliquota'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValidationError('Somente parâmetros tributários públicos declarados são aceitos.')
    for key, item in value.items():
        if not isinstance(item, (str, bool)) or len(str(item)) > 200:
            raise ValidationError('Parâmetro tributário inválido.')
        if isinstance(item, str) and re.search(r'PRIVATE KEY|CERTIFICATE|senha|password|token|secret|cofre://', item, re.I):
            raise ValidationError('Material sensível não é permitido na regra tributária.')
        if key.endswith('aliquota'):
            try:
                amount = Decimal(item)
                assert amount.is_finite() and 0 <= amount <= 100 and amount.as_tuple().exponent >= -4
            except (ArithmeticError, AssertionError, TypeError):
                raise ValidationError('Alíquota explícita deve estar entre 0 e 100, com até quatro casas.')


class ConfiguracaoNFCe(CadastroFiscal):
    configuracao = models.OneToOneField('operacao.ConfiguracaoFiscal', on_delete=models.PROTECT, related_name='nfce')
    municipio_nome = models.CharField(max_length=60)
    natureza_operacao = models.CharField(max_length=60)
    qr_versao = models.CharField(max_length=1, choices=[('3', 'QR Code v3 online; sem contingência')])
    qr_url = models.URLField(max_length=250, blank=True)
    consulta_url = models.URLField(max_length=250, blank=True)
    fonte_urls = models.URLField(max_length=250, blank=True)
    urls_confirmadas = models.BooleanField(default=False)
    schema_release = models.CharField(max_length=80, blank=True)
    schema_aplicabilidade_confirmada = models.BooleanField(default=False)
    def clean(self):
        super().clean()
        if self.configuracao_id and (self.configuracao.tipo != 'NFCE' or self.configuracao.ambiente != 'HOMOLOGACAO' or self.configuracao.motor != 'NFCE_SVRS_HOM'):
            raise ValidationError('Parâmetros exclusivos do motor NFC-e SVRS de homologação.')


class TributacaoProdutoNFCe(CadastroFiscal):
    configuracao = models.ForeignKey('operacao.ConfiguracaoNFCe', on_delete=models.PROTECT, related_name='tributacoes')
    peca = models.ForeignKey('gestao.Peca', on_delete=models.PROTECT)
    regra = models.ForeignKey('operacao.RegraTributariaFiscal', on_delete=models.PROTECT)
    parametros = models.JSONField(default=dict, blank=True, validators=[parametros_nfce])
    class Meta:
        constraints = [models.UniqueConstraint(fields=['configuracao', 'peca', 'regra'], name='nfce_produto_regra_versao')]
    def clean(self):
        super().clean()
        if self.regra_id and self.configuracao_id and self.regra.configuracao_id != self.configuracao.configuracao_id:
            raise ValidationError('Regra tributária de outra configuração.')


class ArtefatoNFCe(RegistroImutavel):
    """Append-only attempts and private XML/PDF links; no raw provider exception."""
    solicitacao = models.ForeignKey('operacao.SolicitacaoFiscal', on_delete=models.PROTECT, related_name='artefatos_nfce')
    arquivo = models.OneToOneField('operacao.Documento', on_delete=models.PROTECT)
    tipo = models.CharField(max_length=15, choices=[('PREPARADO', 'XML preparado'), ('ENVIADO', 'XML assinado enviado'), ('RESPOSTA', 'Retorno'), ('PROCESSADO', 'XML com protocolo'), ('DANFE', 'DANFE de homologação')])
    codigo = models.CharField(max_length=4, blank=True)
    protocolo = models.CharField(max_length=17, blank=True)
    recibo = models.CharField(max_length=15, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    def clean(self):
        super().clean()
        if self.arquivo_id and self.solicitacao_id and self.arquivo.fiscal_id != self.solicitacao.documento_id:
            raise ValidationError('Arquivo deve pertencer à mesma solicitação fiscal.')


class PagamentoFiscalNFCe(CadastroFiscal):
    configuracao = models.ForeignKey(ConfiguracaoNFCe, on_delete=models.PROTECT)
    forma = models.ForeignKey('gestao.FormaPagamento', on_delete=models.PROTECT)
    codigo = models.CharField(max_length=2, choices=[('01', 'Dinheiro'), ('03', 'Crédito'), ('04', 'Débito'), ('17', 'PIX dinâmico'), ('20', 'PIX estático')])
    integracao = models.CharField(max_length=1, blank=True, choices=[('1', 'Integrado'), ('2', 'Não integrado')])
    cnpj_instituicao = models.CharField(max_length=14, blank=True)
    bandeira = models.CharField(max_length=2, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['configuracao', 'forma'], name='nfce_meio_config_unico')]
