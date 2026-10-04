import calendar
from urllib.parse import urlencode
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from gestao.forms import FiltrosForm
from gestao.models import Contrato
from ordens.models import Status, OrdemServico
from ordens.services import visiveis, endereco, gestor
from platform_core.access import effective_role
from .models import PRIORIDADES, ENCERRADAS
from .planning_forms import ScheduleForm, QuickOrderForm
from . import planning_services as ps

class CalendarioForm(FiltrosForm):
    data = forms.DateField(required=False, widget=forms.DateInput(attrs={'type':'date','class':'form-control'},format='%Y-%m-%d'))
    visao = forms.ChoiceField(required=False, choices=[('DIA','Dia'),('SEMANA','Semana'),('MES','Mês')])
    modo = forms.ChoiceField(required=False, choices=[('CALENDARIO','Calendário'),('LISTA','Lista'),('TIMELINE','Linha do tempo')])
    prioridade = forms.ChoiceField(required=False, choices=[('','Todas')]+PRIORIDADES)
    contrato = forms.ModelChoiceField(queryset=Contrato.objects.none(),required=False)
    tipo = forms.ChoiceField(required=False, choices=[('','Todos')]+list(OrdemServico._meta.get_field('tipo_atendimento').choices))
    grupo = forms.ChoiceField(required=False, choices=[('','Todas as atividades'),('ATRASADAS','Atrasadas'),('NAO_PLANEJADAS','Não planejadas'),('SEM_TECNICO','Sem técnico'),('CONFLITOS','Conflitos'),('AG_PECA','Aguardando peças'),('PREVENTIVAS','Preventivas pendentes'),('PREVENTIVAS_ATRASADAS','Preventivas atrasadas')])
    q = forms.CharField(label='Buscar OS, cliente ou equipamento', required=False, max_length=100)
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields.pop('tipo_atendimento', None)
        self.fields['contrato'].queryset=Contrato.objects.all()
        if effective_role(user)=='TECNICO':
            orders=ps.orders_for(user)
            pending=ps.preventive_events(user) + ps.call_events(user)
            self.fields['tecnico'].queryset=ps.technicians_for(user)
            from django.db.models import Q
            for name in ['cliente','unidade','equipamento','contrato']:
                self.fields[name].queryset=self.fields[name].queryset.filter(Q(pk__in=orders.values(name+'_id'))|Q(pk__in=[event[name+'_id'] for event in pending if event[name+'_id']]))
        for field in self.fields.values():
            field.widget.attrs.setdefault('class','form-control')

def filtered(events,data):
    result=[]
    for event in events:
        if any(data.get(name) and (data[name].pk not in event.get('tecnico_ids', [event['tecnico_id']]) if name == 'tecnico' else event[name+'_id']!=data[name].pk) for name in ['cliente','unidade','tecnico','equipamento','contrato']):
            continue
        if any(data.get(name) and event[name+'_code']!=data[name] for name in ['status','prioridade','tipo']):
            continue
        if data.get('q') and data['q'].casefold() not in ' '.join(str(event[key]) for key in ['numero','title','cliente','equipamento','unidade','tecnico','contrato']).casefold():
            continue
        group=data.get('grupo')
        if group=='ATRASADAS' and not event['late'] or group=='NAO_PLANEJADAS' and not event['unplanned'] or group=='SEM_TECNICO' and event['tecnico_id'] or group=='CONFLITOS' and not event['conflicts'] or group=='AG_PECA' and event['status_code']!='AG_PECA' or group=='PREVENTIVAS' and event['kind'] not in ['PREVENTIVA', 'VISITA'] or group=='PREVENTIVAS_ATRASADAS' and (event['kind'] not in ['PREVENTIVA', 'VISITA'] or not event['late']):
            continue
        result.append(event)
    return result

@login_required
def calendario(request):
    ps.require_planning(request.user)
    query=request.GET.copy()
    query.setdefault('data',timezone.localdate().isoformat())
    query.setdefault('visao','SEMANA')
    query.setdefault('modo','CALENDARIO')
    from .models import Chamado
    statuses = dict(Status.choices)
    statuses.update(dict(Chamado._meta.get_field('status').choices))
    form=CalendarioForm(query,user=request.user,statuses=statuses.items())
    if not form.is_valid():
        return render(request,'operacao/calendario.html',{'form':form},status=400)
    data=form.cleaned_data
    selected=data.get('data') or timezone.localdate()
    mode=data.get('visao') or 'SEMANA'
    start=selected if mode=='DIA' else selected-timezone.timedelta(days=selected.weekday()) if mode=='SEMANA' else selected.replace(day=1)
    end=start if mode=='DIA' else start+timezone.timedelta(days=6) if mode=='SEMANA' else start.replace(day=calendar.monthrange(start.year,start.month)[1])
    # Encerradas só entram no período exibido; pendências alimentam a fila e os
    # indicadores globais. Conflitos não dependem dos filtros da tela.
    from django.db.models import Q
    orders=list(ps.orders_for(request.user).filter(Q(status__in=ENCERRADAS,agendada_para__date__range=(start,end))|Q(status__in=ENCERRADAS,conclusao__date__range=(start,end))|~Q(status__in=ENCERRADAS)))
    conflict=ps.conflict_map(orders)
    events=[ps.order_event(row,conflict.get(row.pk)) for row in orders]+ps.preventive_events(request.user)+ps.call_events(request.user)
    for event in events:
        if event['kind']!='OS' and gestor(request.user):
            event['origin_url']=event['url']
        if event['kind']=='OS':
            event['url']=reverse('operacao:planning_detail',args=[event['id']])
    active=[event for event in events if event['status_code'] not in ENCERRADAS]
    summaries=[]
    for label,group,predicate in [('Atrasadas','ATRASADAS',lambda e:e['late']),('Não planejadas','NAO_PLANEJADAS',lambda e:e['unplanned']),('Conflitos','CONFLITOS',lambda e:bool(e['conflicts'])),('Aguardando peças','AG_PECA',lambda e:e['status_code']=='AG_PECA'),('Preventivas atrasadas','PREVENTIVAS_ATRASADAS',lambda e:e['kind']!='OS' and e['late'])]:
        summaries.append({'label':label,'total':sum(predicate(event) for event in active),'url':'?'+urlencode({'grupo':group,'modo':'LISTA','visao':mode,'data':selected.isoformat()})})
    matching=filtered(events,data)
    queue=sorted([event for event in matching if event['unplanned'] and event['status_code'] not in ENCERRADAS],key=lambda e:(e['prioridade_code']!='URGENTE',not e['late'],e.get('abertura',''),e['id']))
    period=sorted([event for event in matching if event['date'] and start<=event['date']<=end],key=lambda e:(e['date'],e['time'],e['numero']))
    scoped_group=data.get('grupo')
    listed=sorted([event for event in matching if event in period or event in queue or scoped_group and event['status_code'] not in ENCERRADAS],key=lambda e:(e['date'] or timezone.localdate(),e['time'],e['numero']))
    days=[{'date':start+timezone.timedelta(days=index),'events':[e for e in period if e['date']==start+timezone.timedelta(days=index)]} for index in range((end-start).days+1)]
    for day in days:
        day['extra']=max(0,len(day['events'])-3)
        day['url']='?'+urlencode(dict(query.items(),data=day['date'].isoformat(),visao='DIA',modo='LISTA'))
    previous=start-timezone.timedelta(days=1) if mode=='MES' else selected-timezone.timedelta(days=1 if mode=='DIA' else 7)
    following=end+timezone.timedelta(days=1) if mode=='MES' else selected+timezone.timedelta(days=1 if mode=='DIA' else 7)
    return render(request,'operacao/calendario.html',{'form':form,'days':days,'inicio':start,'fim':end,'selected':selected,'mode':mode,'presentation':data.get('modo') or 'CALENDARIO',
        'prev_url':'?'+urlencode(dict(query.items(),data=previous.isoformat())),'next_url':'?'+urlencode(dict(query.items(),data=following.isoformat())),
        'summaries':summaries,'queue':queue,'events':listed,'can_write':effective_role(request.user) in ps.PLANNERS,'can_tv':ps.can_tv(request.user),
        'timeline':ps.timeline_rows(ps.technicians_for(request.user),period,selected),'hours':range(7,18),
        'available':sum(not any(e['tecnico_id']==tech.pk and e['status_code']=='EXECUCAO' for e in events) for tech in ps.technicians_for(request.user))})

@login_required
@require_http_methods(['GET'])
def detail(request,pk):
    row=get_object_or_404(ps.orders_for(request.user),pk=pk)
    event=ps.order_event(row,[other.numero for other in ps.conflicts(row)])
    event.update(descricao=row.defeito, fabricante=row.equipamento.fabricante, modelo=row.equipamento.modelo, patrimonio=row.equipamento.codigo_interno, serie=row.equipamento.numero_serie,
                 endereco=endereco(row.unidade or row.cliente), can_write=effective_role(request.user) in ps.PLANNERS and row.status not in ENCERRADAS+['EXECUCAO'],
                 edit_url=reverse('operacao:planning_schedule',args=[pk]),open_url=reverse('ordens:detalhe',args=[pk]) if gestor(request.user) or effective_role(request.user)=='TECNICO' else '',
                 can_start=bool(row.tecnico_id and row.status in ['ABERTA','AGENDADA'] and (gestor(request.user) or row.tecnico.usuario_id==request.user.pk)))
    from .stock import metrics
    parts=[]
    cache={}
    for reserve in row.reservas_estoque.filter(status='ATIVA').select_related('peca','deposito'):
        values=cache.setdefault(reserve.peca_id,metrics(reserve.peca))
        parts.append({'sku':reserve.peca.sku,'produto':reserve.peca.descricao,'deposito':reserve.deposito.nome,'reservado_os':str(reserve.quantidade),'disponivel':str(values['disponivel']),'em_compra':str(values['em_compra'])})
    event['pecas']=parts
    return JsonResponse(event)

@login_required
@require_http_methods(['GET','POST'])
def quick(request):
    ps.require_planning(request.user,writing=True)
    form=QuickOrderForm(request.POST or None,user=request.user)
    if request.method=='POST' and form.is_valid():
        try:
            row=ps.save_plan(request.user,form)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,f'{row.numero} criada no fluxo atual de OS.')
            return redirect('operacao:calendario')
    choices={'units':list(form.fields['unidade'].queryset.values('id','cliente_id','nome')),'equipment':list(form.fields['equipamento'].queryset.values('id','cliente_id','unidade_id','nome'))}
    return render(request,'operacao/planning_form.html',{'form':form,'titulo':'Nova OS rápida','back_url':reverse('operacao:calendario'),'quick':True,'quick_choices':choices},status=400 if request.method=='POST' else 200)

@login_required
@require_http_methods(['GET','POST'])
def schedule(request,pk):
    ps.require_planning(request.user,writing=True)
    row=get_object_or_404(ps.orders_for(request.user),pk=pk)
    form=ScheduleForm(request.POST or None,instance=row,user=request.user)
    if request.method=='POST' and form.is_valid():
        try:
            ps.save_plan(request.user,form,pk)
        except ValidationError as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,'Agenda e atribuição atualizadas com auditoria.')
            return redirect('operacao:calendario')
    return render(request,'operacao/planning_form.html',{'form':form,'titulo':f'Planejar {row.numero}','back_url':reverse('operacao:calendario')},status=400 if request.method=='POST' else 200)

@login_required
def tecnico(request):
    ps.require_planning(request.user)
    today=timezone.localdate()
    orders=visiveis(request.user, destinos=True).exclude(status__in=ENCERRADAS).order_by('agendada_para','prazo','pk')
    groups=[]
    seen=set()
    for title,rows in [('Hoje',orders.filter(agendada_para__date=today)),('Atrasadas',[row for row in orders if ps.late(row)]),('Próximas',orders.filter(agendada_para__date__gt=today)),('Sem agendamento',orders.filter(agendada_para__isnull=True)),('Concluídas hoje',visiveis(request.user).filter(status__in=['FINALIZADA','APROVADA','FATURADA'],conclusao__date=today))]:
        items=[]
        for row in rows:
            if row.pk not in seen:
                seen.add(row.pk)
                from .contract_workday import blocked, config
                if blocked(request.user,row):
                    target=row.unidade or row.cliente
                    items.append({'blocked':True,'destination':{'municipio':target.cidade,'contrato':row.contrato.numero,'resumo':str(target)},'activity_url':reverse('operacao:contract_activity',args=[row.pk])})
                else:
                    items.append({'order':row,'activity_url':reverse('operacao:contract_activity',args=[row.pk]) if config(row) else '', 'route':'https://www.google.com/maps/dir/?'+urlencode({'api':1,'destination':endereco(row.unidade or row.cliente)})})
        groups.append((title,items))
    return render(request,'operacao/tecnico.html',{'groups':groups})
