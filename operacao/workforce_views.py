import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from platform_core.context import current_organization
from platform_core.modules import require_capability, has_capability
from gestao import services as gs, reporting
from gestao.forms import Estilizado
from contas.models import Usuario
from . import models as m, workforce as w

class FuncionarioForm(Estilizado):
    class Meta:
        model=m.Funcionario
        fields=['usuario','tecnico','matricula','nome','departamento','gestor','cargo','vinculo','admissao','desligamento','jornada','autoriza_geolocalizacao','ativo']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for name in ('usuario','gestor'):
            self.fields[name].queryset=Usuario.objects.filter(is_active=True,memberships__organization=current_organization(),memberships__status='ATIVO').distinct()

class DepartamentoForm(Estilizado):
    class Meta:
        model=m.Departamento
        fields=['nome','filial','centro_custo','ativo']

class JornadaForm(Estilizado):
    class Meta:
        model=m.JornadaTrabalho
        fields=['nome','semana','virada_dia','tolerancia_atraso_minutos','banco_horas_habilitado','compensar_deficit','ativo']

class EscalaForm(Estilizado):
    class Meta:
        model=m.EscalaFuncionario
        fields=['funcionario','data','tipo','jornada','motivo']

RESOURCES={'funcionarios':(m.Funcionario,FuncionarioForm,'Funcionários'),'departamentos':(m.Departamento,DepartamentoForm,'Departamentos'),'jornadas':(m.JornadaTrabalho,JornadaForm,'Jornadas'),'escalas':(m.EscalaFuncionario,EscalaForm,'Escalas e folgas')}

@login_required
def management(request,resource='funcionarios',pk=None,new=False):
    require_capability(request.user,'rh')
    if resource not in RESOURCES: raise Http404
    model,cls,title=RESOURCES[resource]
    form=None
    if new or pk:
        instance=get_object_or_404(model,pk=pk) if pk else model()
        form=cls(request.POST or None,instance=instance)
        if request.method=='POST' and form.is_valid():
            with transaction.atomic():
                row=form.save();gs.audit(request.user,'RH_CADASTRO_SALVO',row,{'campos':form.changed_data})
            return redirect('operacao:rh_list',resource=resource)
    return render(request,'operacao/rh.html',{'titulo':title,'resource':resource,'rows':model.objects.all()[:100],'form':form,'back_url':reverse('operacao:rh_list',args=['funcionarios'])})

@login_required
def home(request):
    require_capability(request.user,'ponto')
    try: employee=w.employee_for(request.user)
    except m.Funcionario.DoesNotExist:
        return render(request,'operacao/ponto.html',{'missing':True,'back_url':reverse('platform_core:home')})
    if request.method=='POST':
        try:
            if request.POST.get('action')=='ajuste':
                at=parse_datetime(request.POST.get('data_hora',''))
                if at is None: raise ValidationError('Data/hora inválida.')
                if timezone.is_naive(at): at=timezone.make_aware(at)
                w.request_adjustment(request.user,request.POST['tipo'],at,request.POST.get('motivo',''),int(request.POST['marcacao']) if request.POST.get('marcacao') else None)
            elif request.POST.get('action')=='marcar':
                w.mark(request.user,request.POST['tipo'],request.POST['request_id'],origin=request.POST.get('origem','WEB'),device=request.META.get('HTTP_USER_AGENT','')[:160],session=request.session.session_key or '',ip=request.META.get('REMOTE_ADDR') or None,latitude=request.POST.get('latitude') or None,longitude=request.POST.get('longitude') or None,geo_consent=request.POST.get('geo_consentimento')=='on')
            else: raise ValidationError('Operação inválida.')
            messages.success(request,'Registro salvo.');return redirect('operacao:ponto_home')
        except (ValidationError,ValueError,KeyError,ObjectDoesNotExist) as exc:
            messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Revise os dados informados.')
    now=timezone.localdate()
    return render(request,'operacao/ponto.html',{'employee':employee,'marks':employee.marcacoes.order_by('-data_hora')[:100],'requests':employee.solicitacoes_ponto.order_by('-criado_em')[:50],'request_id':uuid.uuid4(),'today':now,'back_url':reverse('platform_core:home')})

@login_required
def mirror(request,public_id):
    if request.method=='POST':
        try:
            w.close_month(request.user,public_id,int(request.POST['ano']),int(request.POST['mes']))
            messages.success(request,'Competência fechada e preservada no histórico.')
            return redirect(reverse('operacao:ponto_mirror',args=[public_id])+'?ano='+request.POST['ano']+'&mes='+request.POST['mes'])
        except m.Funcionario.DoesNotExist: raise Http404
        except (ValidationError,ValueError,KeyError) as exc:
            messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Competência inválida.')
    try: data=w.mirror(request.user,public_id,int(request.GET.get('ano',timezone.localdate().year)),int(request.GET.get('mes',timezone.localdate().month)))
    except m.Funcionario.DoesNotExist: raise Http404
    except (ValidationError,ValueError): return HttpResponse('Competência inválida.',status=400)
    headers=['Data','Marcações','Previsto min','Trabalhado min','Atraso min','Extra min','Falta min','Banco min','Inconsistente']
    rows=[[day[k] if day[k] is not None else 'Sem jornada/base' for k in ('data','marcacoes','previsto','trabalhado','atraso','extra','falta','banco','inconsistente')] for day in data['dias']]
    export=request.GET.get('formato')
    if export in ('pdf','xlsx'):
        content=reporting.pdf_bytes('Espelho interno de ponto',current_organization(),headers,rows,details=[('Funcionário',data.get('funcionario_nome',str(data['funcionario']))),('Saldo da competência (min)',str(data['saldo_banco_minutos'])),('Fechado',str(data.get('fechado',False))),('Regra interna',data['ressalva'])]) if export=='pdf' else reporting.xlsx_bytes(headers,rows,numeric_columns=(2,3,4,5,6,7))
        response=HttpResponse(content,content_type='application/pdf' if export=='pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');response['Content-Disposition']=f'attachment; filename="espelho-{data["ano"]}-{data["mes"]}.{export}"';return response
    return render(request,'operacao/ponto_mirror.html',{'data':data,'back_url':reverse('operacao:ponto_home'),'headers':headers,'rows':rows})

@login_required
def adjustments(request):
    require_capability(request.user,'ajuste_ponto')
    if request.method=='POST':
        try:
            w.decide_adjustment(request.user,request.POST['solicitacao'],request.POST.get('decisao')=='aprovar',request.POST.get('motivo',''))
            messages.success(request,'Decisão registrada.');return redirect('operacao:ponto_adjustments')
        except m.SolicitacaoAjustePonto.DoesNotExist: raise Http404
        except (ValidationError,ValueError,KeyError) as exc: messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Solicitação inválida.')
    return render(request,'operacao/ponto_adjustments.html',{'rows':m.SolicitacaoAjustePonto.objects.select_related('funcionario','marcacao').order_by('-criado_em')[:100],'back_url':reverse('operacao:rh_list',args=['funcionarios'])})
