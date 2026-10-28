from django import forms
from django.core.exceptions import ValidationError

from . import phase_h_models as m
from .phase_g_models import CidadaoSaudeMunicipal
from .models import UnidadeMunicipal


class SchoolSetupForm(forms.ModelForm):
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), widget=forms.Select(attrs={'class': 'gp-input'}))
    etapas = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'gp-input', 'placeholder': 'Ex.: Fundamental I, Fundamental II'}))

    class Meta:
        model = m.EscolaMunicipal
        fields = ('unidade', 'codigo_inep', 'tipo', 'etapas', 'ativa')
        widgets = {
            'codigo_inep': forms.TextInput(attrs={'class': 'gp-input', 'autocomplete': 'off'}),
            'tipo': forms.Select(attrs={'class': 'gp-input'}),
            'ativa': forms.CheckboxInput(attrs={'class': 'gp-checkbox'}),
        }

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unidade'].queryset = UnidadeMunicipal.objects.filter(organization=organization, ativo=True).order_by('nome')
        self.fields['etapas'].help_text = 'Informe as etapas como uma lista separada por vírgulas.'

    def clean_etapas(self):
        value = self.cleaned_data.get('etapas')
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value or []


class StudentEnrollmentForm(forms.Form):
    nome = forms.CharField(max_length=180, widget=forms.TextInput(attrs={'class': 'gp-input', 'autocomplete': 'name'}))
    cpf = forms.CharField(required=False, max_length=14, widget=forms.TextInput(attrs={'class': 'gp-input', 'inputmode': 'numeric'}))
    data_nascimento = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'gp-input', 'type': 'date'}))
    escola = forms.ModelChoiceField(queryset=m.EscolaMunicipal.objects.none(), widget=forms.Select(attrs={'class': 'gp-input'}))
    turma = forms.ModelChoiceField(queryset=m.TurmaMunicipal.objects.none(), widget=forms.Select(attrs={'class': 'gp-input'}))
    ano_letivo = forms.ModelChoiceField(queryset=m.AnoLetivoMunicipal.objects.none(), widget=forms.Select(attrs={'class': 'gp-input'}))
    numero = forms.CharField(max_length=36, widget=forms.TextInput(attrs={'class': 'gp-input', 'autocomplete': 'off'}))

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields['escola'].queryset = m.EscolaMunicipal.objects.filter(organization=organization, ativa=True).select_related('unidade').order_by('unidade__nome')
        self.fields['turma'].queryset = m.TurmaMunicipal.objects.filter(organization=organization, ativa=True).select_related('escola', 'ano_letivo').order_by('escola__unidade__nome', 'codigo')
        self.fields['ano_letivo'].queryset = m.AnoLetivoMunicipal.objects.filter(organization=organization, ativo=True).order_by('-inicio')

    def clean_cpf(self):
        value = ''.join(c for c in self.cleaned_data.get('cpf', '') if c.isdigit())
        if value and len(value) != 11:
            raise ValidationError('Informe um CPF com 11 dígitos ou deixe em branco.')
        if value and CidadaoSaudeMunicipal.objects.filter(organization=self.organization, cpf=value).exists():
            raise ValidationError('Já existe uma identidade municipal com este CPF. Utilize o cadastro existente.')
        return value

    def clean(self):
        data = super().clean()
        group, school, year = data.get('turma'), data.get('escola'), data.get('ano_letivo')
        if group and school and group.escola_id != school.pk:
            self.add_error('turma', 'Selecione uma turma da escola informada.')
        if group and year and group.ano_letivo_id != year.pk:
            self.add_error('turma', 'Selecione uma turma do ano letivo informado.')
        return data
