import uuid
from django import forms
from operacao import models as m
from fiscal.forms import CadastroTenantForm


class CadastroNFCeForm(CadastroTenantForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in self.fields.values():
            if isinstance(field,forms.ModelChoiceField) and field.queryset.model is m.ConfiguracaoFiscal:
                field.queryset=m.ConfiguracaoFiscal.objects.filter(tipo='NFCE',ambiente='HOMOLOGACAO',motor='NFCE_SVRS_HOM')
            if isinstance(field,forms.ModelChoiceField) and field.queryset.model is m.CredencialFiscal:
                field.queryset=m.CredencialFiscal.objects.filter(ambiente='HOMOLOGACAO',mecanismo='REFERENCIA')


def cadastro(model,fields):return forms.modelform_factory(model,form=CadastroNFCeForm,fields=fields)


class SerieForm(forms.Form):
    estabelecimento=forms.ModelChoiceField(queryset=m.ConfiguracaoFiscal.objects.none())
    serie=forms.IntegerField(min_value=0,max_value=889)
    proximo_numero=forms.IntegerField(min_value=1,max_value=999999999)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from platform_core.models import FilialEmpresa
        self.fields['estabelecimento'].queryset=FilialEmpresa.objects.all()
    def clean_serie(self):return str(self.cleaned_data['serie'])


class ReferenciaForm(forms.Form):
    identificador=forms.UUIDField(help_text='Identificador opaco do futuro cofre; nunca enviar certificado, senha ou CSC.')
    versao=forms.IntegerField(min_value=1)
    expira_em=forms.DateTimeField(required=False)


CADASTROS={
    'perfil':(m.PerfilFiscalEstabelecimento,cadastro(m.PerfilFiscalEstabelecimento,['estabelecimento','municipio_ibge','uf','endereco_estruturado','regime','atividade'])),
    'configuracao':(m.ConfiguracaoFiscal,cadastro(m.ConfiguracaoFiscal,['estabelecimento','versao','habilitada'])),
    'parametros':(m.ConfiguracaoNFCe,cadastro(m.ConfiguracaoNFCe,['configuracao','municipio_nome','natureza_operacao','qr_versao','qr_url','consulta_url','fonte_urls','urls_confirmadas','schema_release','schema_aplicabilidade_confirmada'])),
    'serie':(m.SerieFiscal,SerieForm),
    'referencia':(m.CredencialFiscal,ReferenciaForm),
    'vinculo':(m.VinculoCredencialFiscal,cadastro(m.VinculoCredencialFiscal,['configuracao','credencial'])),
    'regra':(m.RegraTributariaFiscal,cadastro(m.RegraTributariaFiscal,['configuracao','versao','inicio','fim','parametros'])),
    'produto':(m.TributacaoProdutoNFCe,cadastro(m.TributacaoProdutoNFCe,['configuracao','peca','regra','parametros'])),
    'pagamento':(m.PagamentoFiscalNFCe,cadastro(m.PagamentoFiscalNFCe,['configuracao','forma','codigo','integracao','cnpj_instituicao','bandeira'])),
}


class PrepararForm(forms.Form):
    venda=forms.ModelChoiceField(queryset=m.Venda.objects.none())
    configuracao=forms.ModelChoiceField(queryset=m.ConfiguracaoFiscal.objects.none())
    serie=forms.ModelChoiceField(queryset=m.SerieFiscal.objects.none())
    credencial=forms.ModelChoiceField(queryset=m.CredencialFiscal.objects.none(),label='Referência opaca do cofre')
    regra=forms.ModelChoiceField(queryset=m.RegraTributariaFiscal.objects.none())
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['venda'].queryset=m.Venda.objects.filter(status='FINALIZADA')
        self.fields['configuracao'].queryset=m.ConfiguracaoFiscal.objects.filter(tipo='NFCE',ambiente='HOMOLOGACAO',motor='NFCE_SVRS_HOM')
        self.fields['serie'].queryset=m.SerieFiscal.objects.filter(tipo='NFCE',ambiente='HOMOLOGACAO')
        self.fields['credencial'].queryset=m.CredencialFiscal.objects.filter(ambiente='HOMOLOGACAO',mecanismo='REFERENCIA')
        self.fields['regra'].queryset=m.RegraTributariaFiscal.objects.filter(configuracao__ambiente='HOMOLOGACAO',configuracao__tipo='NFCE')


class SolicitarForm(forms.Form):
    request_id=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)


class CancelarForm(SolicitarForm):
    motivo=forms.CharField(min_length=15,max_length=255)
