import uuid
from decimal import Decimal
from django import forms
from django.db.models import Q
from django.utils import timezone
from gestao.forms import Estilizado
from gestao.models import Peca, Fornecedor
from ordens.models import OrdemServico
from . import models as m

class ConfigEstoqueForm(Estilizado):
    class Meta:
        model = m.Configuracao
        fields = ['estoque_minimo_padrao','estoque_ideal_padrao','intervalo_alertas_minutos','dias_alerta_validade','relatorio_semanal_ativo','relatorio_dia_semana','relatorio_horario','consumo_historico_dias','reposicao_dias']
        widgets = {'relatorio_horario':forms.TimeInput(attrs={'type':'time'},format='%H:%M')}
        labels = {'estoque_minimo_padrao':'Mínimo padrão para novos produtos','estoque_ideal_padrao':'Ideal/máximo padrão para novos produtos','intervalo_alertas_minutos':'Intervalo de alertas (minutos)','dias_alerta_validade':'Alertas de validade (lista de dias)','relatorio_semanal_ativo':'Gerar relatório semanal automaticamente','relatorio_dia_semana':'Dia do relatório','relatorio_horario':'Horário local do relatório','consumo_historico_dias':'Janela de consumo histórico (dias)','reposicao_dias':'Cobertura de reposição (dias)'}

class EntradaLoteForm(forms.Form):
    peca = forms.ModelChoiceField(queryset=Peca.objects.none(),label='Produto')
    deposito = forms.ModelChoiceField(queryset=m.Deposito.objects.none(),label='Depósito')
    numero = forms.CharField(max_length=100,label='Número do lote')
    fabricacao = forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'),label='Fabricação')
    validade = forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    quantidade = forms.DecimalField(max_digits=14,decimal_places=3,min_value=Decimal('.001'))
    fornecedor = forms.ModelChoiceField(queryset=Fornecedor.objects.none(),required=False)
    custo_unitario = forms.DecimalField(max_digits=14,decimal_places=2,min_value=0,label='Custo unitário')
    localizacao = forms.CharField(max_length=150,required=False,label='Localização')
    documento_entrada = forms.CharField(max_length=180,required=False,label='Documento de entrada')
    motivo = forms.CharField(max_length=255)
    request_id = forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['peca'].queryset=Peca.objects.filter(ativo=True)
        self.fields['deposito'].queryset=m.Deposito.objects.filter(ativo=True)
        self.fields['fornecedor'].queryset=Fornecedor.objects.filter(ativo=True)
        style(self)
    def clean(self):
        data=super().clean()
        if data.get('peca') and data['peca'].controla_validade and not data.get('validade'):
            self.add_error('validade','Este produto exige validade por lote.')
        if data.get('fabricacao') and data.get('validade') and data['fabricacao'] > data['validade']:
            self.add_error('validade','Validade anterior à fabricação.')
        return data

class ReservaForm(forms.Form):
    request_id = forms.UUIDField(initial=uuid.uuid4, required=False, widget=forms.HiddenInput)
    lote = forms.ModelChoiceField(queryset=m.LoteEstoque.objects.none(), required=False, help_text='Opcional. Sem seleção: FEFO entre lotes livres e válidos.')
    peca=forms.ModelChoiceField(queryset=Peca.objects.none(),label='Produto')
    deposito=forms.ModelChoiceField(queryset=m.Deposito.objects.none())
    quantidade=forms.DecimalField(max_digits=14,decimal_places=3,min_value=Decimal('.001'))
    ordem=forms.ModelChoiceField(queryset=OrdemServico.objects.none(),required=False,label='OS comprometida')
    venda=forms.ModelChoiceField(queryset=m.Venda.objects.none(),required=False,label='Venda comprometida')
    motivo=forms.CharField(max_length=255)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['peca'].queryset=Peca.objects.filter(ativo=True)
        self.fields['deposito'].queryset=m.Deposito.objects.filter(ativo=True)
        self.fields['ordem'].queryset=OrdemServico.objects.exclude(status__in=m.ENCERRADAS)
        self.fields['venda'].queryset=m.Venda.objects.filter(status='RASCUNHO')
        self.fields['lote'].queryset=m.LoteEstoque.objects.filter(quantidade__gt=0).filter(Q(validade__isnull=True) | Q(validade__gte=timezone.localdate()))
        style(self)

class RecebimentoLoteForm(Estilizado):
    class Meta:
        model=m.ItemCompra
        fields=['lote','fabricacao','validade','documento_entrada']

class CompraRelatorioForm(forms.Form):
    deposito=forms.ModelChoiceField(queryset=m.Deposito.objects.none())
    vencimento=forms.DateField(initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    justificativa=forms.CharField(required=False,widget=forms.Textarea(attrs={'rows':2}),help_text='Obrigatória para exceder a recomendação atual, inclusive se compras pendentes já cobrem a necessidade.')
    request_id=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput)
    def __init__(self,*args,rows,**kwargs):
        super().__init__(*args,**kwargs)
        self.rows=rows
        self.fields['deposito'].queryset=m.Deposito.objects.filter(ativo=True)
        for row in rows:
            self.fields[f'selecionar_{row.pk}']=forms.BooleanField(required=False,label='Selecionar')
            self.fields[f'quantidade_{row.pk}']=forms.DecimalField(required=False,max_digits=14,decimal_places=3,min_value=0,initial=row.dados['sugerido'],label='Quantidade solicitada')
        style(self)
    def clean(self):
        data=super().clean()
        selection={}
        for row in self.rows:
            if data.get(f'selecionar_{row.pk}'):
                quantity=data.get(f'quantidade_{row.pk}')
                if not quantity:
                    self.add_error(f'quantidade_{row.pk}','Informe quantidade positiva.')
                else:
                    selection[str(row.pk)]=quantity
        if not selection:
            raise forms.ValidationError('Selecione pelo menos um produto.')
        data['selecao']=selection
        return data

def style(form):
    for field in form.fields.values():
        field.widget.attrs.setdefault('class','form-check-input' if isinstance(field.widget,forms.CheckboxInput) else 'form-select' if isinstance(field.widget,forms.Select) else 'form-control')
