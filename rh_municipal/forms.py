from django import forms

from platform_core.context import current_organization
from platform_core.models import MembershipERP, OrganizationMembership

from .models import (
    AcessoRH, CargoMunicipal, DepartamentoMunicipal, FuncaoMunicipal,
    JornadaMunicipal, Secretaria, Servidor, SetorMunicipal, UnidadeMunicipal, VinculoFuncional,
)


class ServidorForm(forms.ModelForm):
    class Meta:
        model = Servidor
        fields = [
            'matricula', 'nome', 'nome_social', 'cpf', 'email', 'telefone', 'usuario',
            'secretaria', 'departamento', 'setor', 'unidade', 'cargo', 'funcao',
            'vinculo', 'jornada', 'data_admissao', 'ativo',
        ]
        widgets = {'data_admissao': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        for name, model in {
            'secretaria': Secretaria, 'departamento': DepartamentoMunicipal,
            'setor': SetorMunicipal, 'unidade': UnidadeMunicipal,
            'cargo': CargoMunicipal, 'funcao': FuncaoMunicipal, 'vinculo': VinculoFuncional,
        }.items():
            self.fields[name].queryset = model.objects.filter(organization=org, ativo=True)
        self.fields['jornada'].queryset = JornadaMunicipal.objects.filter(organization=org, ativa=True)
        self.fields['usuario'].required = False
        self.fields['usuario'].queryset = OrganizationMembership.objects.filter(
            organization=org, status='ATIVO',
            erp_accesses__erp__code='gestao-publica', erp_accesses__enabled=True,
        ).values_list('user', flat=True)
        # ModelChoiceField expects User rows, while membership is the authorization source.
        from django.contrib.auth import get_user_model
        user_ids = list(self.fields['usuario'].queryset)
        self.fields['usuario'].queryset = get_user_model().objects.filter(pk__in=user_ids, is_active=True)


class AcessoRHForm(forms.Form):
    membership = forms.ModelChoiceField(queryset=OrganizationMembership.objects.none(), label='Conta municipal')
    papel = forms.ChoiceField(choices=AcessoRH.Papel.choices, label='Papel no RH Municipal')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['membership'].queryset = OrganizationMembership.objects.filter(
            organization=org, status='ATIVO',
            erp_accesses__erp__code='gestao-publica', erp_accesses__erp__active=True,
            erp_accesses__enabled=True,
        ).select_related('user').distinct()


class EstruturaMunicipalForm(forms.Form):
    codigo = forms.CharField(max_length=30, label='Código')
    nome = forms.CharField(max_length=150, label='Nome')
    descricao = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}), label='Descrição')
    secretaria = forms.ModelChoiceField(queryset=Secretaria.objects.none(), required=False, label='Secretaria')
    departamento = forms.ModelChoiceField(queryset=DepartamentoMunicipal.objects.none(), required=False, label='Departamento')
    setor = forms.ModelChoiceField(queryset=SetorMunicipal.objects.none(), required=False, label='Setor')
    carga_horaria_semanal = forms.IntegerField(min_value=1, max_value=168, required=False, label='Carga horária semanal (informativa)')

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.kind = kind
        if kind == 'departamento':
            self.fields['secretaria'].required = True
        elif kind == 'setor':
            self.fields['departamento'].required = True
        elif kind == 'unidade':
            self.fields['setor'].required = True
        elif kind == 'cargo':
            self.fields['carga_horaria_semanal'].required = False
        self.fields['secretaria'].queryset = Secretaria.objects.filter(organization=org, ativo=True)
        self.fields['departamento'].queryset = DepartamentoMunicipal.objects.filter(organization=org, ativo=True)
        self.fields['setor'].queryset = SetorMunicipal.objects.filter(organization=org, ativo=True)
        for field in ('secretaria', 'departamento', 'setor', 'carga_horaria_semanal'):
            if field not in {'secretaria', 'departamento', 'setor'} or field != {'departamento':'secretaria','setor':'departamento','unidade':'setor'}.get(kind):
                if field != 'carga_horaria_semanal' or kind != 'cargo':
                    self.fields.pop(field)


class JornadaMunicipalForm(forms.ModelForm):
    class Meta:
        model = JornadaMunicipal
        fields = ['nome', 'semana', 'ativa']
        widgets = {'semana': forms.Textarea(attrs={'rows': 6, 'spellcheck': 'false'})}


class SolicitacaoServidorForm(forms.Form):
    tipo = forms.ChoiceField(choices=[
        ('FERIAS', 'Férias'), ('AFASTAMENTO', 'Afastamento'),
        ('CORRECAO_PONTO', 'Correção de ponto'), ('DOCUMENTO', 'Documento'),
        ('ATUALIZACAO_CADASTRAL', 'Atualização cadastral'),
    ])
    descricao = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), max_length=4000)


class DecisaoSolicitacaoForm(forms.Form):
    public_id = forms.UUIDField(widget=forms.HiddenInput())
    aprovada = forms.TypedChoiceField(choices=[('true', 'Aprovar'), ('false', 'Recusar')], coerce=lambda v: v == 'true')
    motivo = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={'rows': 2}))
