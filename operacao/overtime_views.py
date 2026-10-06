"""Self-service overtime stays under Ponto; management stays under RH."""
import calendar
import uuid
from datetime import date, timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from . import models as m, overtime as o, workforce as w

class OvertimeForm(forms.Form):
    data=forms.DateField(label='Data do atendimento/ponto',widget=forms.DateInput(attrs={'type':'date','class':'form-control'},format='%Y-%m-%d'))
    minutos=forms.IntegerField(label='Quantidade solicitada (minutos)',min_value=1,widget=forms.NumberInput(attrs={'class':'form-control','step':1}))
    motivo=forms.CharField(label='Motivo / justificativa',max_length=5000,widget=forms.Textarea(attrs={'class':'form-control','rows':3}))
    request_id=forms.UUIDField(widget=forms.HiddenInput)

@login_required
def own(request):
    try: employee=w.employee_for(request.user)
    except m.Funcionario.DoesNotExist:
        return render(request,'operacao/overtime_own.html',{'missing':True,'back_url':reverse('operacao:ponto_home')})
    today=timezone.localdate()
    try: day=date.fromisoformat(request.GET.get('data',today.isoformat()))
    except (ValueError,TypeError): return HttpResponse('Data inválida.',status=400)
    if not 2000<=day.year<=2100 or day>today: return HttpResponse('Data inválida.',status=400)
    form=OvertimeForm(request.POST if request.method=='POST' else None,initial={'data':day,'request_id':uuid.uuid4()})
    if request.method=='POST' and form.is_valid():
        day=form.cleaned_data['data']
        try:
            o.request_overtime(request.user,day,form.cleaned_data['minutos'],form.cleaned_data['motivo'],form.cleaned_data['request_id'])
        except ValidationError as exc: form.add_error(None,'; '.join(exc.messages))
        else:
            messages.success(request,'Hora extra solicitada. Aguarde a aprovação; excedente não é aprovação automática.')
            return redirect(reverse('operacao:ponto_overtime')+'?data='+day.isoformat())
    if day>today or not 2000<=day.year<=2100:
        day=today
    data,closed=o.day_data(request.user,employee,day)
    if request.method!='POST' and data['extra'] and not data.get('extra_status'): form.initial['minutos']=data['extra']
    return render(request,'operacao/overtime_own.html',{'employee':employee,'day':day,'data':data,'closed':closed,'form':form,'requests':o.requests_for(request.user).select_related('decisao','decisao__usuario','referencia').order_by('-data','-pk')[:100],'back_url':reverse('operacao:ponto_home')},status=400 if request.method=='POST' else 200)

class ReportFilter(forms.Form):
    inicio=forms.DateField(widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    fim=forms.DateField(widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'))
    funcionario=forms.ModelChoiceField(queryset=m.Funcionario.objects.none(),required=False)
    departamento=forms.ModelChoiceField(queryset=m.Departamento.objects.none(),required=False)
    cargo=forms.CharField(required=False,max_length=100)
    jornada=forms.ModelChoiceField(queryset=m.JornadaTrabalho.objects.none(),required=False)
    status=forms.ChoiceField(required=False,choices=[('','Todos'),('PENDENTE','Pendente'),('APROVADA','Aprovada'),('RECUSADA','Recusada'),('SEM_SOLICITACAO','Sem solicitação')])
    def __init__(self,*args,employees,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['funcionario'].queryset=employees
        self.fields['departamento'].queryset=m.Departamento.objects.filter(funcionario__in=employees).distinct()
        self.fields['jornada'].queryset=m.JornadaTrabalho.objects.filter(funcionario__in=employees).distinct()
        for field in self.fields.values(): field.widget.attrs['class']='form-select' if isinstance(field.widget,forms.Select) else 'form-control'
    def clean(self):
        data=super().clean()
        if data.get('inicio') and data.get('fim'):
            if not 2000<=data['inicio'].year<=2100 or not 2000<=data['fim'].year<=2100 or not 0<=(data['fim']-data['inicio']).days<=366:
                raise forms.ValidationError('Consulte um período válido de até 367 dias.')
        return data

@login_required
def management(request):
    employees=o.managed_employees(request.user).select_related('jornada','departamento')
    if request.method=='POST':
        try:
            if request.POST.get('decisao') not in ('aprovar','recusar'): raise ValidationError('Decisão inválida.')
            o.decide_overtime(request.user,request.POST['solicitacao'],request.POST['decisao']=='aprovar',request.POST.get('minutos'),request.POST.get('motivo',''))
        except (m.SolicitacaoHoraExtra.DoesNotExist,ValueError): raise Http404
        except (ValidationError,KeyError) as exc:
            messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Solicitação inválida.')
        else:
            messages.success(request,'Decisão registrada com responsável, quantidade e histórico.')
            return redirect('operacao:rh_overtime')
    today=timezone.localdate()
    filter_data=request.GET.copy()
    if not filter_data.get('inicio'): filter_data['inicio']=today.replace(day=1).isoformat()
    if not filter_data.get('fim'): filter_data['fim']=today.isoformat()
    form=ReportFilter(filter_data,employees=employees)
    totals={name:0 for name in ('previsto','trabalhado','extra','extra_pendente','extra_aprovada','extra_recusada')}
    report=[];requests=o.requests_for(request.user,management=True).none()
    if form.is_valid():
        data=form.cleaned_data
        if data['funcionario']: employees=employees.filter(pk=data['funcionario'].pk)
        if data['departamento']: employees=employees.filter(departamento=data['departamento'])
        if data['cargo']: employees=employees.filter(cargo__icontains=data['cargo'])
        if data['jornada']: employees=employees.filter(jornada=data['jornada'])
        requests=o.requests_for(request.user,management=True).filter(funcionario__in=employees,data__range=(data['inicio'],data['fim'])).select_related('funcionario','decisao','decisao__usuario','referencia').order_by('-data','-pk')
        if data['status']=='PENDENTE': requests=requests.filter(decisao__isnull=True)
        elif data['status'] in ('APROVADA','RECUSADA'): requests=requests.filter(decisao__aprovado=data['status']=='APROVADA')
        elif data['status']=='SEM_SOLICITACAO': requests=requests.none()
        month=data['inicio'].replace(day=1)
        months=[]
        while month<=data['fim']:
            months.append(month)
            month=(month+timedelta(days=calendar.monthrange(month.year,month.month)[1])).replace(day=1)
        for employee in employees:
            for month in months:
                mirror=w.mirror(request.user,employee.public_id,month.year,month.month)
                for item in mirror['dias']:
                    when=date.fromisoformat(item['data'])
                    if not data['inicio']<=when<=data['fim']: continue
                    status=item.get('extra_status','')
                    if data['status'] and status!=('' if data['status']=='SEM_SOLICITACAO' else data['status']): continue
                    for key in totals: totals[key]+=item.get(key) or 0
                    if item['marcacoes'] or status:
                        report.append({'funcionario':employee,'day':item,'historico_anterior':mirror.get('fechado') and 'extra_aprovada' not in item})
    return render(request,'operacao/overtime_management.html',{'filter':form,'totals':totals,'report':report,'requests':requests,'back_url':reverse('operacao:rh_list',args=['funcionarios'])},status=400 if not form.is_valid() else 200)
