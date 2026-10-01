from django import forms
from platform_core.forms import TenantModelForm
from ordens.models import OrdemServico
from contas.models import Tecnico
from gestao.models import Contrato
from .models import Configuracao, BLOCOS_PAINEL
from .planning_services import gestor

class ScheduleForm(TenantModelForm):
    revisao = forms.IntegerField(widget=forms.HiddenInput)
    autorizar_conflito = forms.BooleanField(label='Autorizar conflito conscientemente', required=False)
    justificativa = forms.CharField(label='Motivo da alteração / autorização do conflito', required=False, max_length=1000, widget=forms.Textarea(attrs={'rows':2}))
    class Meta:
        model = OrdemServico
        fields = ['tecnico','agendada_para','agendada_ate','prioridade']
        labels = {'agendada_para':'Início previsto'}
        widgets = {name:forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M') for name in ['agendada_para','agendada_ate']}
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['revisao'].initial = self.instance.revisao
        self.fields['tecnico'].queryset = Tecnico.objects.filter(ativo=True)
        if not gestor(user):
            self.fields.pop('autorizar_conflito')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class','form-control')

class QuickOrderForm(ScheduleForm):
    revisao = forms.IntegerField(required=False, widget=forms.HiddenInput)
    class Meta(ScheduleForm.Meta):
        fields = ['cliente','unidade','equipamento','contrato','tipo_atendimento','prioridade','defeito','prazo','tecnico','agendada_para','agendada_ate']
        widgets = dict(ScheduleForm.Meta.widgets, defeito=forms.Textarea(attrs={'rows':3}), prazo=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'))
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,user=user,**kwargs)
        self.fields['contrato'].queryset = Contrato.objects.exclude(status__in=['SUSPENSO','ENCERRADO'])

class TVConfigForm(TenantModelForm):
    painel_blocos = forms.MultipleChoiceField(label='Blocos visíveis', choices=BLOCOS_PAINEL, widget=forms.CheckboxSelectMultiple)
    class Meta:
        model=Configuracao
        fields=['painel_intervalo','painel_tema','painel_blocos']
        labels={'painel_intervalo':'Atualizar a cada','painel_tema':'Tema'}
