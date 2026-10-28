from django import forms
from platform_core.context import current_organization

from . import phase_g_models as health
from .phase_g_forms import _HealthScopedForm
from . import primary_care_services as svc


class PrimaryUnitFilterForm(forms.Form):
    unidade = forms.ModelChoiceField(queryset=health.UnidadeSaudeMunicipal.objects.none(), required=False,
                                    label='UBS / Centro de Saúde')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unidade'].queryset = svc.primary_units(actor).order_by('unidade__nome')
        self.fields['unidade'].label_from_instance = lambda row: row.unidade.nome
        self.fields['unidade'].widget.attrs['class'] = 'gp-input'


class PrimaryFamilyForm(_HealthScopedForm):
    class Meta:
        model = health.FamiliaTerritorialSaude
        fields = ('codigo', 'unidade_saude', 'equipe', 'microarea', 'endereco')
        labels = {'codigo': 'Código da família', 'endereco': 'Endereço do domicílio'}
        widgets = {'endereco': forms.TextInput(attrs={'autocomplete': 'off'})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        self.instance.organization = current_organization()
        self.fields['unidade_saude'].queryset = svc.primary_units(actor, manage=True)
        self.fields['unidade_saude'].label_from_instance = lambda row: row.unidade.nome
        teams = svc.primary_rows(actor, health.EquipeSaudeMunicipal, manage=True).filter(
            ativo=True, unidade_saude__in=self.fields['unidade_saude'].queryset,
        )
        unit = self.data.get(self.add_prefix('unidade_saude')) if self.is_bound else self.initial.get('unidade_saude')
        self.fields['equipe'].queryset = teams.filter(unidade_saude_id=unit) if str(unit or '').isdigit() else teams.none()
        self.fields['equipe'].label_from_instance = lambda row: f'{row.codigo} · {row.nome}'


class PrimaryFamilyMemberForm(forms.Form):
    familia = forms.ModelChoiceField(queryset=health.FamiliaTerritorialSaude.objects.none(), label='Família')
    cidadao = forms.CharField(label='CPF ou CNS do cidadão', max_length=20,
                             help_text='Informe o documento completo do cadastro existente. A tela não lista pacientes.')
    parentesco = forms.CharField(max_length=50, required=False, label='Parentesco')
    referencia = forms.BooleanField(required=False, label='Cidadão de referência da família')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['familia'].queryset = svc.primary_rows(
            actor, health.FamiliaTerritorialSaude, manage=True,
        ).filter(ativo=True, unidade_saude__in=svc.primary_units(actor, manage=True)).order_by('codigo')
        self.fields['familia'].label_from_instance = lambda row: row.codigo
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'gp-input', 'autocomplete': 'off'})

    def clean_cidadao(self):
        value = self.cleaned_data['cidadao'].replace('.', '').replace('-', '').replace(' ', '')
        if not value.isascii() or not value.isdigit() or len(value) not in (11, 15):
            raise forms.ValidationError('Informe CPF com 11 dígitos ou CNS com 15 dígitos.')
        return value
