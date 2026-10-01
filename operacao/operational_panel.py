"""Painel somente de leitura; DTO explícito não utiliza snapshot de documentos."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from platform_core.access import require_erp
from gestao.services import audit
from .models import Configuracao, ENCERRADAS, blocos_painel_padrao
from .planning_forms import TVConfigForm
from . import planning_services as ps

def payload(user):
    query, technicians_query=ps.television_rows(user)
    today=timezone.localdate()
    now=timezone.now()
    rows=list(query.filter(~Q(status__in=ENCERRADAS)|Q(conclusao__date=today,status__in=['FINALIZADA','APROVADA','FATURADA'])|Q(agendada_para__date=today)))
    conflict=ps.conflict_map(rows)
    events=[ps.order_event(row,conflict.get(row.pk)) for row in rows]
    # Lista permitida. Endereço, descrição livre, contato, documentos, estoque,
    # custos e snapshot completo jamais são serializados na interface de TV.
    keys=['numero','cliente','unidade','equipamento','tecnico','tipo','status','status_code','prioridade','prioridade_code','date','time','start','end','inicio','conclusao','late','conflicts','tecnico_id','unplanned']
    safe=lambda event:{key:event.get(key) for key in keys}
    active=[event for event in events if event['status_code'] not in ENCERRADAS]
    current=[event for event in active if event['status_code']=='EXECUCAO']
    done=sorted([event for event in events if event['conclusao'] and timezone.localdate(timezone.datetime.fromisoformat(event['conclusao']))==today and event['status_code'] in ['FINALIZADA','APROVADA','FATURADA']],key=lambda event:event['conclusao'],reverse=True)
    queue=sorted([event for event in active if event['status_code']!='EXECUCAO' and (event['unplanned'] or event['late'] or event['prioridade_code']=='URGENTE' or event['status_code'] in ['AG_PECA','AG_CLIENTE'] or event['date']==today)],key=lambda event:(event['prioridade_code']!='URGENTE',not event['late'],event['numero']))
    technicians=list(technicians_query)
    team=[]
    for tech in technicians:
        executing=[safe(event) for event in current if event['tecnico_id']==tech.pk]
        following=sorted([event for event in active if event['tecnico_id']==tech.pk and event['start'] and timezone.datetime.fromisoformat(event['start'])>=now and event['status_code']!='EXECUCAO'],key=lambda event:event['start'])
        team.append({'nome':tech.nome,'status':'Em atendimento' if executing else 'Sem atendimento em execução','agora':executing,'proxima':safe(following[0]) if following else None})
    next_by_tech={tech.pk:row['proxima'] for tech,row in zip(technicians,team)}
    preventive=ps.preventive_events(user,television=True)
    preventive=[{'numero':event['numero'],'cliente':event['cliente'],'equipamento':event['equipamento'],'tecnico':event['tecnico'],'date':event['date'],'late':event['late'],'tipo':event['tipo']} for event in preventive if event['date']<=today+timezone.timedelta(days=30)]
    config=Configuracao.objects.first()
    blocks=config.painel_blocos if config else blocos_painel_padrao()
    timeline=ps.timeline_rows(technicians,events,today)
    timeline=[{'tecnico':row['tecnico'],'total':row['total'],'horas':row['horas'],'sem_duracao':row['sem_duracao'],'bars':[dict(safe(event),left=event['left'],width=event['width']) for event in row['bars']]} for row in timeline]
    alerts={'urgentes':sum(event['prioridade_code']=='URGENTE' for event in active),'atrasadas':sum(event['late'] for event in active),'conflitos':sum(bool(event['conflicts']) for event in active),'pecas':sum(event['status_code']=='AG_PECA' for event in active)}
    return {'organization':str(ps.current_organization().display_name),'date':today,'generated_at':now.isoformat(),
        'config':{'interval':config.painel_intervalo if config else 30,'theme':config.painel_tema if config else 'ESCURO','blocks':blocks},
        'indicadores':{'OS hoje':sum(event['date']==today for event in events),'Em atendimento':len(current),'Aguardando':sum(event['status_code'] in ['ABERTA','AGENDADA','AG_CLIENTE'] for event in active),'Atrasadas':alerts['atrasadas'],'Concluídas hoje':len(done),'Aguardando peças':alerts['pecas']},
        'agora':[dict(safe(event),proxima=next_by_tech.get(event['tecnico_id'])) for event in current] if 'agora' in blocks else [],'equipe':team if 'equipe' in blocks else [],
        'timeline':timeline if 'timeline' in blocks else [],'fila':[safe(event) for event in queue] if 'fila' in blocks else [],
        'concluidas':[safe(event) for event in done] if 'concluidas' in blocks else [],'preventivas':preventive if 'preventivas' in blocks else [],'alertas':alerts}

@login_required
@require_http_methods(['GET'])
def panel(request):
    return render(request,'operacao/operational_panel.html',{'panel_data':payload(request.user)})

@login_required
@require_http_methods(['GET'])
def data(request):
    response=JsonResponse(payload(request.user))
    response['Cache-Control']='private, no-store'
    response['Vary']='Cookie'
    return response

@login_required
@require_http_methods(['GET','POST'])
def config(request):
    require_erp(request.user,roles=['ADMIN'])
    instance=Configuracao.objects.first() or Configuracao()
    form=TVConfigForm(request.POST or None,instance=instance)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            ps.lock_planning()
            old=Configuracao.objects.select_for_update().first()
            # Evita sobrescrever a configuração de estoque alterada em outra tela.
            row=old or Configuracao()
            before={name:getattr(row,name) for name in form.Meta.fields}
            for name in form.Meta.fields:
                setattr(row,name,form.cleaned_data[name])
            row.save()
            audit(request.user,'PAINEL_OPERACIONAL_CONFIGURADO',row,{'anterior':before,'posterior':{name:getattr(row,name) for name in form.Meta.fields}})
        return redirect('operacao:panel_config')
    return render(request,'operacao/form.html',{'titulo':'Configurar painel operacional','form':form,'back_url':reverse('operacao:calendario')},status=400 if request.method=='POST' else 200)
