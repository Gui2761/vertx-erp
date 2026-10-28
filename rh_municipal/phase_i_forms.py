"""Styled forms with tenant and municipal-scope filtered references."""
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership
from .models import Servidor
from .phase_f_models import Secretaria, DepartamentoMunicipal, SetorMunicipal, UnidadeMunicipal
from .phase_i_models import (AchadoControleInterno, ControleInternoMunicipal,
    PlanoAcaoInterno, RiscoControleInterno)
from .public_services import scoped_queryset


class Styled(forms.ModelForm):
    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'gp-input')

    def _scope(self, queryset):
        return scoped_queryset(self.actor, queryset)

    def _servers(self):
        org = current_organization()
        return self._scope(Servidor.objects.filter(organization=org, ativo=True))

    def _hierarchy(self):
        org = current_organization()
        self.fields['secretaria'].queryset = self._scope(Secretaria.objects.filter(organization=org, ativo=True))
        self.fields['departamento'].queryset = self._scope(DepartamentoMunicipal.objects.filter(organization=org, ativo=True))
        self.fields['setor'].queryset = self._scope(SetorMunicipal.objects.filter(organization=org, ativo=True))
        self.fields['unidade'].queryset = self._scope(UnidadeMunicipal.objects.filter(organization=org, ativo=True))


class RiskForm(Styled):
    class Meta:
        model = RiscoControleInterno
        fields = ('codigo', 'titulo', 'descricao', 'categoria', 'probabilidade', 'impacto', 'responsavel', 'prazo_revisao', 'secretaria', 'departamento', 'setor', 'unidade')
        widgets = {'descricao': forms.Textarea(attrs={'rows': 4}), 'prazo_revisao': forms.DateInput(attrs={'type': 'date'})}

    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False)
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False)
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False)
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hierarchy()
        self.fields['responsavel'].queryset = self._servers()


class ControlForm(Styled):
    class Meta:
        model = ControleInternoMunicipal
        fields = ('codigo', 'titulo', 'descricao', 'risco', 'responsavel', 'frequencia', 'ativo', 'secretaria', 'departamento', 'setor', 'unidade')
        widgets = {'descricao': forms.Textarea(attrs={'rows': 3})}

    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False)
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False)
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False)
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self._hierarchy()
        self.fields['risco'].queryset = self._scope(RiscoControleInterno.objects.filter(organization=org))
        self.fields['responsavel'].queryset = self._servers()


class FindingForm(Styled):
    class Meta:
        model = AchadoControleInterno
        fields = ('codigo', 'titulo', 'descricao', 'origem', 'risco', 'controle', 'severidade', 'prazo', 'responsavel', 'secretaria', 'departamento', 'setor', 'unidade')
        widgets = {'descricao': forms.Textarea(attrs={'rows': 4}), 'prazo': forms.DateInput(attrs={'type': 'date'})}

    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False)
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False)
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False)
    unidade = forms.ModelChoiceField(queryset=UnidadeMunicipal.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self._hierarchy()
        self.fields['risco'].queryset = self._scope(RiscoControleInterno.objects.filter(organization=org))
        self.fields['controle'].queryset = self._scope(ControleInternoMunicipal.objects.filter(organization=org, ativo=True))
        self.fields['responsavel'].queryset = self._servers()


class RecommendationForm(forms.Form):
    texto = forms.CharField(max_length=8000, widget=forms.Textarea(attrs={'rows': 5, 'class': 'gp-input'}))


class ActionPlanForm(Styled):
    class Meta:
        model = PlanoAcaoInterno
        fields = ('titulo', 'descricao', 'responsavel', 'prazo')
        widgets = {'descricao': forms.Textarea(attrs={'rows': 4}), 'prazo': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsavel'].queryset = self._servers()


class ActionUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=PlanoAcaoInterno.Status.choices)
    descricao = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3, 'class': 'gp-input'}))


class EvidenceForm(forms.Form):
    titulo = forms.CharField(max_length=180, widget=forms.TextInput(attrs={'class': 'gp-input'}))
    arquivo = forms.FileField()
