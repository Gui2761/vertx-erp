from django import forms

from gestao.models import Fornecedor
from .public_services import scoped_queryset
from . import phase_d_models as m
from .phase_b_models import ContratoPublicoMunicipal, ProcessoContratacaoMunicipal
from .models import DepartamentoMunicipal, Secretaria, Servidor, SetorMunicipal, UnidadeMunicipal


class MunicipalModelForm(forms.ModelForm):
    def __init__(self, *args, organization, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.actor = actor
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')
        self._tenant_choices()

    def _tenant_choices(self):
        for field in self.fields.values():
            current = getattr(field, 'queryset', None)
            model = getattr(current, 'model', None)
            if model is None or not any(item.name == 'organization' for item in model._meta.fields):
                continue
            queryset = model.objects.filter(organization=self.organization)
            if any(item.name == 'ativo' for item in model._meta.fields):
                queryset = queryset.filter(ativo=True)
            if self.actor:
                queryset = scoped_queryset(self.actor, queryset)
            field.queryset = queryset


class BemPatrimonialForm(MunicipalModelForm):
    class Meta:
        model = m.BemPatrimonial
        exclude = ('organization', 'criado_por', 'criado_em')
        widgets = {'data_aquisicao': forms.DateInput(attrs={'type': 'date'}), 'observacoes': forms.Textarea(attrs={'rows': 3})}


class DepositoMunicipalForm(MunicipalModelForm):
    class Meta:
        model = m.DepositoAlmoxarifadoMunicipal
        exclude = ('organization', 'criado_por')


class ItemAlmoxarifadoForm(MunicipalModelForm):
    class Meta:
        model = m.ItemAlmoxarifadoMunicipal
        exclude = ('organization',)


class VeiculoMunicipalForm(MunicipalModelForm):
    class Meta:
        model = m.VeiculoMunicipal
        exclude = ('organization', 'quilometragem_atual', 'documento_key')


class CondutorMunicipalForm(MunicipalModelForm):
    class Meta:
        model = m.CondutorMunicipal
        exclude = ('organization',)
        widgets = {'validade': forms.DateInput(attrs={'type': 'date'})}


class SolicitacaoMaterialForm(forms.Form):
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none())
    item = forms.ModelChoiceField(queryset=m.ItemAlmoxarifadoMunicipal.objects.none())
    quantidade = forms.DecimalField(min_value=0.0001, decimal_places=4, max_digits=18)
    prioridade = forms.ChoiceField(choices=[('BAIXA','Baixa'),('NORMAL','Normal'),('ALTA','Alta'),('URGENTE','Urgente')])
    justificativa = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, organization, unit_queryset=None, item_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unidade'].queryset = unit_queryset or UnidadeMunicipal.objects.filter(organization=organization, ativo=True)
        self.fields['item'].queryset = item_queryset or m.ItemAlmoxarifadoMunicipal.objects.filter(organization=organization, ativo=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class EntradaAlmoxarifadoForm(forms.Form):
    deposito = forms.ModelChoiceField(queryset=m.DepositoAlmoxarifadoMunicipal.objects.none())
    item = forms.ModelChoiceField(queryset=m.ItemAlmoxarifadoMunicipal.objects.none())
    quantidade = forms.DecimalField(min_value=0.0001, decimal_places=4, max_digits=18)
    fornecedor = forms.ModelChoiceField(queryset=Fornecedor.objects.none(), required=False)
    processo = forms.ModelChoiceField(queryset=ProcessoContratacaoMunicipal.objects.none(), required=False)
    contrato = forms.ModelChoiceField(queryset=ContratoPublicoMunicipal.objects.none(), required=False)
    nota_fiscal = forms.CharField(required=False, max_length=80)
    lote = forms.CharField(required=False, max_length=80)
    validade = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    justificativa = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, organization, deposit_queryset=None, item_queryset=None, supplier_queryset=None,
                 process_queryset=None, contract_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['deposito'].queryset = deposit_queryset or m.DepositoAlmoxarifadoMunicipal.objects.filter(organization=organization, ativo=True)
        self.fields['item'].queryset = item_queryset or m.ItemAlmoxarifadoMunicipal.objects.filter(organization=organization, ativo=True)
        self.fields['fornecedor'].queryset = supplier_queryset or Fornecedor.objects.none()
        self.fields['processo'].queryset = process_queryset or ProcessoContratacaoMunicipal.objects.none()
        self.fields['contrato'].queryset = contract_queryset or ContratoPublicoMunicipal.objects.none()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class TransferenciaAlmoxarifadoForm(forms.Form):
    origem = forms.ModelChoiceField(queryset=m.DepositoAlmoxarifadoMunicipal.objects.none())
    destino = forms.ModelChoiceField(queryset=m.DepositoAlmoxarifadoMunicipal.objects.none())
    item = forms.ModelChoiceField(queryset=m.ItemAlmoxarifadoMunicipal.objects.none())
    quantidade = forms.DecimalField(min_value=0.0001, decimal_places=4, max_digits=18)
    justificativa = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, organization, deposit_queryset=None, item_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['origem'].queryset = deposit_queryset or m.DepositoAlmoxarifadoMunicipal.objects.filter(organization=organization, ativo=True)
        self.fields['destino'].queryset = self.fields['origem'].queryset
        self.fields['item'].queryset = item_queryset or m.ItemAlmoxarifadoMunicipal.objects.filter(organization=organization, ativo=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class ViagemMunicipalForm(forms.Form):
    veiculo = forms.ModelChoiceField(queryset=m.VeiculoMunicipal.objects.none())
    condutor = forms.ModelChoiceField(queryset=m.CondutorMunicipal.objects.none())
    origem = forms.CharField(max_length=180)
    destino = forms.CharField(max_length=180)
    finalidade = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}))
    quilometragem_inicial = forms.IntegerField(min_value=0)
    passageiros = forms.IntegerField(min_value=0, required=False)
    observacoes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, vehicle_queryset=None, driver_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['veiculo'].queryset = vehicle_queryset or m.VeiculoMunicipal.objects.none()
        self.fields['condutor'].queryset = driver_queryset or m.CondutorMunicipal.objects.none()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class AbastecimentoForm(forms.Form):
    combustivel = forms.CharField(max_length=30)
    quantidade_litros = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3)
    tanque_completo = forms.BooleanField(required=False)
    valor_unitario = forms.DecimalField(min_value=0, max_digits=12, decimal_places=4)
    quilometragem = forms.IntegerField(min_value=0)
    posto = forms.CharField(max_length=160, required=False)
    documento = forms.CharField(max_length=120, required=False)

    def __init__(self, *args, vehicle_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['veiculo'] = forms.ModelChoiceField(queryset=vehicle_queryset or m.VeiculoMunicipal.objects.none())
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class ManutencaoVeiculoForm(forms.ModelForm):
    class Meta:
        model = m.ManutencaoVeiculoMunicipal
        fields = ('veiculo', 'tipo', 'oficina', 'ordem', 'descricao', 'pecas', 'mao_de_obra', 'valor', 'quilometragem', 'iniciada_em', 'previsao')
        widgets = {'iniciada_em': forms.DateInput(attrs={'type': 'date'}), 'previsao': forms.DateInput(attrs={'type': 'date'}), 'descricao': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, vehicle_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['veiculo'].queryset = vehicle_queryset or m.VeiculoMunicipal.objects.none()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class DocumentoFrotaForm(forms.ModelForm):
    class Meta:
        model = m.DocumentoFrotaMunicipal
        fields = ('veiculo', 'tipo', 'numero', 'vence_em', 'valor', 'observacao')
        widgets = {'vence_em': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, vehicle_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['veiculo'].queryset = vehicle_queryset or m.VeiculoMunicipal.objects.none()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class MovimentacaoBemForm(forms.Form):
    tipo = forms.ChoiceField(choices=m.MovimentacaoPatrimonial.Tipo.choices)
    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False)
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False)
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False)
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), required=False)
    responsavel_novo = forms.ModelChoiceField(queryset=Servidor.objects.none(), required=False)
    localizacao = forms.CharField(max_length=180, required=False)
    motivo = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}))
    observacao = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        for model, name in ((Secretaria, 'secretaria'), (DepartamentoMunicipal, 'departamento'),
                            (SetorMunicipal, 'setor'), (UnidadeMunicipal, 'unidade'), (Servidor, 'responsavel_novo')):
            self.fields[name].queryset = model.objects.filter(organization=organization, ativo=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class CountPropertyForm(forms.Form):
    encontrado = forms.BooleanField(required=False)
    tombamento_informado = forms.CharField(max_length=40, required=False)
    localizacao_informada = forms.CharField(max_length=180, required=False)
    conservacao_informada = forms.ChoiceField(choices=[('', '—'), *m.BemPatrimonial.Conservacao.choices], required=False)
    observacao = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class CountStockForm(forms.Form):
    quantidade = forms.DecimalField(min_value=0, decimal_places=4, max_digits=18)
    observacao = forms.CharField(required=False)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')


class ReturnTripForm(forms.Form):
    quilometragem_final = forms.IntegerField(min_value=0)
    observacao = forms.CharField(required=False)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')

