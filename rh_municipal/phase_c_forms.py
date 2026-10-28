"""Tenant-scoped forms for municipal HR and timekeeping screens."""
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from platform_core.context import current_organization
from platform_core.models import MembershipERP

from .models import (
    AtribuicaoJornadaMunicipal, BeneficioServidorMunicipal, CargoMunicipal,
    CompetenciaFolhaMunicipal, DepartamentoMunicipal, EscalaMunicipal,
    EventoFolhaMunicipal, LancamentoFolhaMunicipal, RemuneracaoBaseServidorMunicipal,
    FuncaoMunicipal, GrupoJornadaMunicipal, HorarioJornadaMunicipal, JornadaMunicipal, Secretaria,
    Servidor, SetorMunicipal, UnidadeMunicipal, VinculoFuncional,
)


class ServidorMunicipalForm(forms.ModelForm):
    class Meta:
        model = Servidor
        fields = ('usuario', 'matricula', 'nome', 'nome_social', 'cpf', 'email', 'telefone',
                  'secretaria', 'departamento', 'setor', 'unidade', 'cargo', 'funcao',
                  'vinculo', 'jornada', 'data_admissao', 'situacao_funcional',
                  'observacoes_funcionais', 'ativo')
        widgets = {
            'data_admissao': forms.DateInput(attrs={'type': 'date'}),
            'observacoes_funcionais': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        for field, model in {
            'secretaria': Secretaria, 'departamento': DepartamentoMunicipal,
            'setor': SetorMunicipal, 'unidade': UnidadeMunicipal,
            'funcao': FuncaoMunicipal, 'vinculo': VinculoFuncional,
        }.items():
            self.fields[field].queryset = model.objects.filter(organization=org, ativo=True)
        self.fields['cargo'].queryset = CargoMunicipal.objects.filter(organization=org, ativo=True)
        self.fields['jornada'].queryset = JornadaMunicipal.objects.filter(organization=org, ativa=True)
        member_ids = MembershipERP.objects.filter(
            membership__organization=org, membership__status='ATIVO',
            erp__code='gestao-publica', erp__active=True, enabled=True,
        ).values_list('membership__user_id', flat=True)
        self.fields['usuario'].queryset = get_user_model().objects.filter(pk__in=member_ids, is_active=True)
        self.fields['usuario'].required = False
        for name in ('nome_social','cpf','email','telefone','funcao','jornada','data_admissao','observacoes_funcionais'):
            self.fields[name].required = False


class JornadaMunicipalForm(forms.ModelForm):
    class Meta:
        model = JornadaMunicipal
        fields = ('nome', 'semana', 'ativa')
        widgets = {'semana': forms.Textarea(attrs={'rows': 5, 'spellcheck': 'false'})}

    def clean_semana(self):
        value = self.cleaned_data['semana']
        if not isinstance(value, dict):
            raise ValidationError('Informe a configuração semanal como objeto JSON.')
        return value


class HorarioJornadaMunicipalForm(forms.ModelForm):
    class Meta:
        model = HorarioJornadaMunicipal
        fields = ('jornada','dia_semana','inicio','fim','intervalo_inicio','intervalo_fim',
                  'carga_minutos','tolerancia_entrada_minutos','tolerancia_saida_minutos','turno','ativo')
        widgets = {name: forms.TimeInput(attrs={'type':'time'}) for name in ('inicio','fim','intervalo_inicio','intervalo_fim')}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['jornada'].queryset=JornadaMunicipal.objects.filter(organization=current_organization(),ativa=True)


class AtribuicaoJornadaMunicipalForm(forms.ModelForm):
    class Meta:
        model = AtribuicaoJornadaMunicipal
        fields = ('servidor','grupo','jornada','escala','inicio_vigencia','fim_vigencia')
        widgets = {'inicio_vigencia':forms.DateInput(attrs={'type':'date'}), 'fim_vigencia':forms.DateInput(attrs={'type':'date'})}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        org=current_organization()
        self.fields['servidor'].queryset=Servidor.objects.filter(organization=org,ativo=True)
        self.fields['grupo'].queryset=GrupoJornadaMunicipal.objects.filter(organization=org,ativo=True)
        self.fields['jornada'].queryset=JornadaMunicipal.objects.filter(organization=org,ativa=True)
        self.fields['escala'].queryset=EscalaMunicipal.objects.filter(organization=org,ativa=True)
        self.fields['servidor'].required=False; self.fields['grupo'].required=False


class JustificativaPontoForm(forms.Form):
    inicio = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type':'datetime-local'}), label='Início do período')
    fim = forms.DateTimeField(required=False, widget=forms.DateTimeInput(attrs={'type':'datetime-local'}), label='Fim do período')
    motivo = forms.CharField(max_length=80)
    descricao = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={'rows':3}), label='Justificativa')


class HoraExtraMunicipalForm(forms.Form):
    inicio = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type':'datetime-local'}), label='Início')
    fim = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type':'datetime-local'}), label='Fim')
    justificativa = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={'rows':3}))


class DecisionPontoForm(forms.Form):
    tipo = forms.ChoiceField(choices=[('justificativa','Justificativa'),('hora_extra','Hora extra')])
    solicitacao_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    aprovada = forms.BooleanField(required=False, label='Aprovar')
    motivo = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={'rows':2}), label='Observação da decisão')


class PeriodActionForm(forms.Form):
    periodo_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    acao = forms.ChoiceField(choices=[
        ('conferir','Iniciar conferência'),('enviar_aprovacao','Enviar para aprovação'),
        ('aprovar','Aprovar'),('fechar','Fechar período'),('reabrir','Reabrir período'),
    ])
    motivo = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={'rows':2}))


class ManualPunchForm(forms.Form):
    servidor = forms.ModelChoiceField(queryset=Servidor.objects.none())
    tipo = forms.ChoiceField(choices=[('ENTRADA','Entrada'),('SAIDA_INTERVALO','Saída para intervalo'),('RETORNO_INTERVALO','Retorno do intervalo'),('SAIDA','Saída')])
    data_hora = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    motivo = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows':2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['servidor'].queryset = Servidor.objects.filter(organization=current_organization(), ativo=True)


class RemuneracaoBaseMunicipalForm(forms.ModelForm):
    class Meta:
        model = RemuneracaoBaseServidorMunicipal
        fields = ('servidor', 'valor_base', 'inicio_vigencia', 'fim_vigencia', 'referencia_legal')
        widgets = {'inicio_vigencia': forms.DateInput(attrs={'type': 'date'}), 'fim_vigencia': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['servidor'].queryset = Servidor.objects.filter(organization=current_organization(), ativo=True)


class BeneficioServidorMunicipalForm(forms.ModelForm):
    class Meta:
        model = BeneficioServidorMunicipal
        fields = ('servidor', 'codigo', 'nome', 'inicio', 'fim', 'valor_informativo', 'observacao', 'ativo')
        widgets = {'inicio': forms.DateInput(attrs={'type': 'date'}), 'fim': forms.DateInput(attrs={'type': 'date'}), 'observacao': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['servidor'].queryset = Servidor.objects.filter(organization=current_organization(), ativo=True)


class LancamentoInformativoFolhaForm(forms.ModelForm):
    class Meta:
        model = LancamentoFolhaMunicipal
        fields = ('competencia', 'servidor', 'evento', 'valor_informativo', 'referencia', 'observacao')
        widgets = {'observacao': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = current_organization()
        self.fields['competencia'].queryset = CompetenciaFolhaMunicipal.objects.filter(organization=org, status__in=('PREPARACAO', 'CONFERENCIA'))
        self.fields['servidor'].queryset = Servidor.objects.filter(organization=org, ativo=True)
        self.fields['evento'].queryset = EventoFolhaMunicipal.objects.filter(organization=org, ativo=True)
