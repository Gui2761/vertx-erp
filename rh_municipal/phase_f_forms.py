from django import forms
from django.utils import timezone

from . import phase_f_models as m

WIDGET = {'class': 'gp-input'}


class ScopeMixin:
    def _scope_fields(self, organization, actor):
        from .models import Secretaria, DepartamentoMunicipal, SetorMunicipal, UnidadeMunicipal
        from .public_services import scoped_queryset
        models = {
            'secretaria': Secretaria, 'departamento': DepartamentoMunicipal,
            'setor': SetorMunicipal, 'unidade': UnidadeMunicipal,
        }
        for field, model in models.items():
            qs = model.objects.filter(organization=organization, ativo=True)
            self.fields[field].queryset = scoped_queryset(actor, qs)
            self.fields[field].required = False
            self.fields[field].widget.attrs.update(WIDGET)


class ContributorForm(ScopeMixin, forms.ModelForm):
    class Meta:
        model = m.ContribuinteMunicipal
        fields = ['codigo', 'tipo', 'documento', 'nome', 'email', 'telefone', 'cep', 'logradouro', 'numero_endereco', 'complemento', 'bairro', 'municipio', 'uf', 'secretaria', 'departamento', 'setor', 'unidade']
        widgets = {'tipo': forms.Select(attrs=WIDGET)}

    def __init__(self, *args, organization=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            if field not in {'tipo', 'secretaria', 'departamento', 'setor', 'unidade'}:
                self.fields[field].widget.attrs.update(WIDGET)
        if organization and actor:
            self._scope_fields(organization, actor)


class PropertyForm(ScopeMixin, forms.ModelForm):
    class Meta:
        model = m.ImovelMunicipal
        fields = ['inscricao', 'matricula', 'proprietario', 'possuidor', 'logradouro', 'numero_endereco', 'complemento', 'bairro', 'cep', 'area_terreno', 'area_edificada', 'utilizacao', 'latitude', 'longitude', 'secretaria', 'departamento', 'setor', 'unidade']
        widgets = {'proprietario': forms.Select(attrs=WIDGET), 'possuidor': forms.Select(attrs=WIDGET), 'utilizacao': forms.Select(attrs=WIDGET)}

    def __init__(self, *args, organization=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update(WIDGET)
        if organization and actor:
            self._scope_fields(organization, actor)
        parties = m.ContribuinteMunicipal.objects.filter(organization=organization, situacao='ATIVO')
        if actor:
            from .public_services import scoped_queryset
            parties = scoped_queryset(actor, parties)
        self.fields['proprietario'].queryset = parties
        self.fields['possuidor'].queryset = parties


class TaxRuleForm(ScopeMixin, forms.ModelForm):
    class Meta:
        model = m.RegraTributariaMunicipal
        fields = ['codigo', 'tributo', 'versao', 'vigencia_inicio', 'vigencia_fim', 'parametros', 'ativa', 'secretaria', 'departamento', 'setor', 'unidade']
        widgets = {
            'codigo': forms.TextInput(attrs=WIDGET), 'tributo': forms.Select(attrs=WIDGET),
            'versao': forms.NumberInput(attrs=WIDGET),
            'vigencia_inicio': forms.DateInput(attrs={**WIDGET, 'type': 'date'}, format='%Y-%m-%d'),
            'vigencia_fim': forms.DateInput(attrs={**WIDGET, 'type': 'date'}, format='%Y-%m-%d'),
            'parametros': forms.Textarea(attrs={**WIDGET, 'rows': 4}), 'ativa': forms.CheckboxInput(),
        }

    def __init__(self, *args, organization=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization and actor:
            self._scope_fields(organization, actor)


class TaxLaunchForm(forms.Form):
    tax_type = forms.ChoiceField(label='Tributo', choices=m.RegraTributariaMunicipal.Tributo.choices, widget=forms.Select(attrs=WIDGET))
    taxpayer = forms.ModelChoiceField(label='Contribuinte', queryset=m.ContribuinteMunicipal.objects.none(), widget=forms.Select(attrs=WIDGET))
    property = forms.ModelChoiceField(label='Imóvel (IPTU)', queryset=m.ImovelMunicipal.objects.none(), required=False, widget=forms.Select(attrs=WIDGET))
    rule = forms.ModelChoiceField(label='Regra vigente', queryset=m.RegraTributariaMunicipal.objects.none(), widget=forms.Select(attrs=WIDGET))
    exercise = forms.IntegerField(label='Exercício', min_value=2000, max_value=2200, initial=timezone.localdate().year, widget=forms.NumberInput(attrs=WIDGET))
    competence = forms.CharField(label='Competência (se aplicável)', max_length=7, required=False, widget=forms.TextInput(attrs=WIDGET))
    base_amount = forms.DecimalField(label='Base de cálculo', min_value=0, max_digits=15, decimal_places=2, widget=forms.NumberInput(attrs={**WIDGET, 'step': '0.01'}))
    due_date = forms.DateField(label='Vencimento', widget=forms.DateInput(attrs={**WIDGET, 'type': 'date'}, format='%Y-%m-%d'))

    def __init__(self, *args, organization=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .public_services import scoped_queryset
        self.fields['taxpayer'].queryset = scoped_queryset(actor, m.ContribuinteMunicipal.objects.filter(organization=organization, situacao='ATIVO'))
        self.fields['property'].queryset = scoped_queryset(actor, m.ImovelMunicipal.objects.filter(organization=organization, situacao='ATIVO'))
        self.fields['rule'].queryset = scoped_queryset(actor, m.RegraTributariaMunicipal.objects.filter(organization=organization, ativa=True, vigencia_inicio__lte=timezone.localdate()).filter(forms_q_rule_end()))

    def clean(self):
        data = super().clean()
        if data.get('rule') and data.get('tax_type') != data['rule'].tributo:
            self.add_error('rule', 'A regra selecionada é de outro tributo.')
        if data.get('tax_type') == m.RegraTributariaMunicipal.Tributo.IPTU and not data.get('property'):
            self.add_error('property', 'Selecione um imóvel para lançamento de IPTU.')
        return data


def forms_q_rule_end():
    from django.db.models import Q
    return Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=timezone.localdate())


class InstallmentForm(forms.Form):
    launch = forms.ModelChoiceField(label='Lançamento', queryset=m.LancamentoTributarioMunicipal.objects.none(), widget=forms.Select(attrs=WIDGET))
    count = forms.IntegerField(label='Quantidade de parcelas', min_value=1, max_value=60, widget=forms.NumberInput(attrs=WIDGET))
    first_due = forms.DateField(label='Primeiro vencimento', widget=forms.DateInput(attrs={**WIDGET, 'type': 'date'}, format='%Y-%m-%d'))
    interval_days = forms.IntegerField(label='Intervalo em dias', min_value=1, max_value=366, initial=30, widget=forms.NumberInput(attrs=WIDGET))

    def __init__(self, *args, organization=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .public_services import scoped_queryset
        self.fields['launch'].queryset = scoped_queryset(actor, m.LancamentoTributarioMunicipal.objects.filter(organization=organization, status='ABERTO'))


class ManualPaymentForm(forms.Form):
    installment = forms.ModelChoiceField(label='Parcela', queryset=m.ParcelaTributariaMunicipal.objects.none(), widget=forms.Select(attrs=WIDGET))
    amount = forms.DecimalField(label='Valor recebido', min_value='0.01', max_digits=15, decimal_places=2, widget=forms.NumberInput(attrs={**WIDGET, 'step': '0.01'}))
    request_id = forms.UUIDField(widget=forms.HiddenInput())
    reference = forms.CharField(label='Referência externa (opcional)', max_length=100, required=False, widget=forms.TextInput(attrs=WIDGET))

    def __init__(self, *args, organization=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .public_services import scoped_queryset
        self.fields['installment'].queryset = scoped_queryset(actor, m.ParcelaTributariaMunicipal.objects.filter(organization=organization))


class NfseDraftForm(ScopeMixin, forms.ModelForm):
    class Meta:
        model = m.NotaServicoMunicipal
        fields = ['prestador', 'tomador', 'codigo_servico', 'descricao', 'competencia', 'valor_servico', 'secretaria', 'departamento', 'setor', 'unidade']
        widgets = {'prestador': forms.Select(attrs=WIDGET), 'tomador': forms.Select(attrs=WIDGET), 'codigo_servico': forms.TextInput(attrs=WIDGET), 'descricao': forms.Textarea(attrs={**WIDGET, 'rows': 3}), 'competencia': forms.TextInput(attrs=WIDGET), 'valor_servico': forms.NumberInput(attrs={**WIDGET, 'step': '0.01'})}

    def __init__(self, *args, organization=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization and actor:
            self._scope_fields(organization, actor)
        parties = m.ContribuinteMunicipal.objects.filter(organization=organization, situacao='ATIVO')
        if actor:
            from .public_services import scoped_queryset
            parties = scoped_queryset(actor, parties)
        self.fields['prestador'].queryset = parties
        self.fields['tomador'].queryset = parties
