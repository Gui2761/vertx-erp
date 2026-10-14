from django import forms
from decimal import Decimal
from operacao import models as m
from clientes.models import Cliente

class CadastroTenantForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Factory fields are built outside a tenant request. Rebuild FK choices NOW.
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                field.queryset = field.queryset.model.objects.all()

def cadastro(model, fields):
    return forms.modelform_factory(model, form=CadastroTenantForm, fields=fields)

class ReferenciaSimuladaForm(forms.Form):
    versao = forms.IntegerField(min_value=1, initial=1)
    expira_em = forms.DateTimeField(required=False)

CADASTROS = {
    'perfil': (m.PerfilFiscalEstabelecimento, cadastro(m.PerfilFiscalEstabelecimento, ['estabelecimento', 'municipio_ibge', 'uf', 'regime', 'atividade'])),
    'configuracao': (m.ConfiguracaoFiscal, cadastro(m.ConfiguracaoFiscal, ['estabelecimento', 'tipo', 'versao', 'habilitada'])),
    'referencia': (m.CredencialFiscal, ReferenciaSimuladaForm),
    'vinculo': (m.VinculoCredencialFiscal, cadastro(m.VinculoCredencialFiscal, ['configuracao', 'credencial'])),
    'serie': (m.SerieFiscal, cadastro(m.SerieFiscal, ['estabelecimento', 'tipo', 'serie'])),
    'regra': (m.RegraTributariaFiscal, cadastro(m.RegraTributariaFiscal, ['configuracao', 'versao', 'inicio', 'fim', 'parametros'])),
}

class DocumentoSimuladoForm(forms.Form):
    configuracao = forms.ModelChoiceField(queryset=m.ConfiguracaoFiscal.objects.none())
    serie = forms.ModelChoiceField(queryset=m.SerieFiscal.objects.none())
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.none(), required=False)
    venda = forms.ModelChoiceField(queryset=m.Venda.objects.none(), required=False, help_text='Somente vendas já finalizadas; sem alteração de caixa/estoque.')
    credencial = forms.ModelChoiceField(queryset=m.CredencialFiscal.objects.none(), required=False, label='Referência de simulação (não é certificado)')
    regra = forms.ModelChoiceField(queryset=m.RegraTributariaFiscal.objects.none(), required=False)
    descricao = forms.CharField(max_length=300)
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'), required=False, help_text='Serviços: informe valor. Mercadorias: usa o total da venda.')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['configuracao'].queryset = m.ConfiguracaoFiscal.objects.filter(ambiente='SIMULACAO', habilitada=True)
        self.fields['serie'].queryset = m.SerieFiscal.objects.filter(ambiente='SIMULACAO')
        self.fields['cliente'].queryset = Cliente.objects.all()
        self.fields['venda'].queryset = m.Venda.objects.filter(status='FINALIZADA')
        self.fields['credencial'].queryset = m.CredencialFiscal.objects.filter(mecanismo='SIMULACAO', ativa=True)
        self.fields['regra'].queryset = m.RegraTributariaFiscal.objects.all()

class SolicitacaoForm(forms.Form):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    cenario = forms.ChoiceField(choices=m.SolicitacaoFiscal._meta.get_field('cenario_simulacao').choices)

class CancelamentoForm(forms.Form):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    motivo = forms.CharField(max_length=500)
