from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods
from django.db import transaction
from gestao.models import Contrato
from gestao import reporting
from gestao.services import audit
from gestao.permissions import require as require_contract
from platform_core.forms import TenantModelForm
from . import contract_workday as s
from .permissions import require


class ConfigForm(TenantModelForm):
    class Meta:
        model=s.Config
        fields=['habilitada','exigir_inicio','deslocamento_faturavel','inicio_contagem','retorno_faturavel','descontar_intervalos','limite_diario_minutos','horario_inicial','horario_final','categoria_padrao','tarifas','fracao_minutos','arredondamento']
        widgets={name:forms.TimeInput(attrs={'type':'time'}) for name in ['horario_inicial','horario_final']}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in self.fields.values():
            field.widget.attrs['class']='form-check-input' if isinstance(field.widget,forms.CheckboxInput) else 'form-control'


class StartForm(forms.Form):
    origem=forms.CharField(label='Base / origem (opcional)',max_length=255,required=False)
    categoria=forms.ChoiceField(label='Categoria do atendimento',choices=())


class CorrectionForm(forms.Form):
    inicio_solicitado=forms.DateTimeField(label='Início solicitado',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    fim_solicitado=forms.DateTimeField(label='Fim solicitado',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    justificativa=forms.CharField(min_length=10,max_length=2000,widget=forms.Textarea(attrs={'rows':3}))


@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def configuration(request,pk):
    require(request.user,'gestao')
    require_contract(request.user,'contratos')
    if request.method == 'POST':
        s.require_journey_writable()
    contract=get_object_or_404(Contrato,pk=pk)
    cfg=s.Config.objects.select_for_update().filter(contrato=contract).first() or s.Config(contrato=contract,tarifas={'Assistência técnica':'0.00'})
    before=s.rules(cfg) if cfg.pk else {}
    form=ConfigForm(request.POST if request.method=='POST' else None,instance=cfg)
    if request.method=='POST' and form.is_valid():
        cfg=form.save()
        audit(request.user,'JORNADA_CONTRATO_CONFIGURADA',cfg,{'anterior':before,'posterior':s.rules(cfg),'habilitada':cfg.habilitada,'exigir_inicio':cfg.exigir_inicio})
        messages.success(request,'Configuração salva. Jornadas anteriores mantêm as regras originais.')
        return redirect('operacao:contract_measurement')
    return render(request,'operacao/form.html',{'titulo':f'Jornada contratual · {contract.numero}','form':form,'back_url':'/contratos/jornadas/'},status=400 if request.method=='POST' else 200)


@login_required
@require_http_methods(['GET','POST'])
def activity(request,order_id):
    tech=s.own_technician(request.user)
    s.require_journey_writable()
    order=get_object_or_404(s.OrdemServico.objects.filter(s.Q(tecnico=tech)|s.Q(auxiliares=tech)).distinct(),pk=order_id)
    cfg=s.config(order)
    if not cfg:
        return HttpResponse('Contrato sem jornada externa habilitada.',status=400)
    row=s.Jornada.objects.filter(tecnico=tech,contrato=order.contrato,data=s.timezone.localdate()).first()
    if row is None:
        row=s.Jornada.objects.filter(tecnico=tech,contrato=order.contrato).exclude(eventos__tipo='FIM').first()
    history=s.Jornada.objects.filter(tecnico=tech,contrato=order.contrato).values('pk','data')[:31]
    if request.GET.get('jornada'):
        try: history_pk=forms.IntegerField(min_value=1).clean(request.GET['jornada'])
        except ValidationError: return HttpResponse('Identificador da jornada inválido.',status=400)
        row=get_object_or_404(s.Jornada.objects.filter(tecnico=tech,contrato=order.contrato),pk=history_pk)
    form=StartForm(request.POST if request.method=='POST' and request.POST.get('acao')=='INICIO' else None)
    form.fields['categoria'].choices=[(name,name) for name in cfg.tarifas]
    form.initial['categoria']=cfg.categoria_padrao
    correction_form=CorrectionForm(request.POST if request.method=='POST' and request.POST.get('acao')=='CORRECAO' else None)
    if request.method=='POST':
        try:
            action=request.POST.get('acao','')
            if action=='INICIO' and form.is_valid():
                row=s.start(request.user,order.pk,form.cleaned_data['origem'],request.POST,form.cleaned_data['categoria'])
            elif action=='CORRECAO' and row and correction_form.is_valid():
                s.request_correction(request.user,row.pk,**{'start_time':correction_form.cleaned_data['inicio_solicitado'],'end_time':correction_form.cleaned_data['fim_solicitado'],'reason':correction_form.cleaned_data['justificativa']})
            elif row and action in ['CHEGADA','PAUSA','RETOMADA','RETORNO','FIM']:
                s.event(request.user,row.pk,action,request.POST.get('observacao',''),request.POST)
            else:
                raise ValidationError('Preencha o formulário e selecione uma ação válida.')
        except ValidationError as exc:
            messages.error(request,'; '.join(exc.messages))
        else:
            messages.success(request,'Registro salvo com horário do servidor e auditoria.')
            return redirect('operacao:contract_activity',order_id=order.pk)
    # Projeção técnica explícita: sem regras, tarifas ou resultados financeiros.
    public={'id':row.pk,'inicio':row.inicio,'fim':row.fim,'origem':row.origem,'eventos':[{'tipo':e.get_tipo_display(),'horario':e.horario,'observacao':e.observacao} for e in row.eventos.all()],'correcoes':[{'inicio':c.inicio_solicitado,'fim':c.fim_solicitado,'justificativa':c.justificativa,'decisao':('Aprovada' if c.decisao.aprovada else 'Rejeitada') if hasattr(c,'decisao') else 'Pendente'} for c in row.correcoes.select_related('decisao')]} if row else None
    last=row.eventos.last().tipo if row and row.eventos.exists() else 'INICIO'
    actions=[] if not row or row.fim else {'INICIO':['CHEGADA','FIM'],'CHEGADA':['PAUSA','RETORNO','FIM'],'PAUSA':['RETOMADA'],'RETOMADA':['PAUSA','RETORNO','FIM'],'RETORNO':['FIM']}.get(last,[])
    labels=dict(s.Evento._meta.get_field('tipo').choices)
    target=order.unidade or order.cliente
    return render(request,'operacao/contract_activity.html',{'destination':{'municipio':target.cidade,'resumo':str(target),'contrato':order.contrato.numero},'activity':public,'start_form':form,'correction_form':correction_form,'actions':[(a,labels[a]) for a in actions],'unlocked':bool(row and not row.fim and s.operational(row)),'order_id':order.pk,'history':history},status=400 if request.method=='POST' else 200)


class PeriodForm(forms.Form):
    contrato=forms.ModelChoiceField(queryset=Contrato.objects.none(),required=False)
    inicio=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
    fim=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.fields['contrato'].queryset=Contrato.objects.all()
    def clean(self):
        data=super().clean()
        if data.get('inicio') and data.get('fim') and (data['fim']<data['inicio'] or (data['fim']-data['inicio']).days>366):
            raise forms.ValidationError('Selecione período crescente de até 366 dias.')
        return data


@login_required
@require_http_methods(['GET','POST'])
def measurement(request):
    require(request.user,'gestao')
    require_contract(request.user,'contratos')
    if request.method=='POST':
        s.require_journey_writable()
        try: correction_pk=forms.IntegerField(min_value=1).clean(request.POST.get('correcao'))
        except ValidationError: return HttpResponse('Identificador da solicitação inválido.',status=400)
        correction=get_object_or_404(s.Correcao,pk=correction_pk)
        try:
            if request.POST.get('acao') not in ['aprovar','rejeitar']: raise ValidationError('Decisão inválida.')
            s.decide(request.user,correction.pk,request.POST['acao']=='aprovar',request.POST.get('justificativa',''))
        except ValidationError as exc: messages.error(request,'; '.join(exc.messages))
        else: messages.success(request,'Decisão registrada; horários originais preservados.')
        return redirect('operacao:contract_measurement')
    today=s.timezone.localdate()
    form=PeriodForm(request.GET or {'inicio':today.replace(day=1),'fim':today})
    rows=[]
    if form.is_valid():
        qs=s.Jornada.objects.filter(data__range=(form.cleaned_data['inicio'],form.cleaned_data['fim'])).select_related('contrato','tecnico')
        if form.cleaned_data.get('contrato'): qs=qs.filter(contrato=form.cleaned_data['contrato'])
        rows=[s.measurement(row) for row in qs]
    total=sum((r['valor'] for r in rows if not r['provisoria']),Decimal('0'))
    if request.GET.get('formato')=='pdf' and form.is_valid():
        headers=['Dia / contrato','Técnico / categoria','Ida / retorno (min)','Intervalo / OS (min)','Horas / tarifa','Valor','OS / ajustes / observações']
        values=[[f"{r['row'].data} / {r['row'].contrato}",f"{r['row'].tecnico} / {r['row'].categoria}",f"{r['ida']} / {r['retorno']}",f"{r['intervalos']} / {r['tempo_os']}",f"{r['horas']} / {r['tarifa']}",str(r['valor'])+(' PROVISÓRIO' if r['provisoria'] else ''),'; '.join([o['numero'] for o in r['ordens']]+r['divergencias']+[f'Correção #{c.pk}: {c.justificativa}' for c in r['ajustes']]+[f'{e.get_tipo_display()}: {e.observacao}' for e in r['row'].eventos.all() if e.observacao])] for r in rows]
        return HttpResponse(reporting.pdf_bytes('Medição do Contrato — administrativo',request.organization,headers,values,details=[('Período',f"{form.cleaned_data['inicio']} a {form.cleaned_data['fim']}"),('Total encerradas',total),('Aviso','Não é OS do cliente. Provisórias não compõem total. Ida só faturável quando saída BASE e deslocamento habilitado; retorno conforme regra. Sem cobrança automática.')]),content_type='application/pdf')
    return render(request,'operacao/contract_measurement.html',{'form':form,'rows':rows,'total':total,'contracts':Contrato.objects.all()},status=200 if form.is_valid() else 400)
