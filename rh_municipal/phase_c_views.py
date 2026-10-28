"""Municipal HR and Digital Timekeeping interface (Phase C)."""
import json
from datetime import date, datetime, time
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from platform_core.context import current_organization

from . import phase_c_models as pc
from .models import (
    AfastamentoServidor, AcessoMunicipal, AtribuicaoJornadaMunicipal,
    BeneficioServidorMunicipal, CompetenciaFolhaMunicipal,
    DependenteServidorMunicipal, EventoFolhaMunicipal, FeriasServidor,
    HistoricoServidor, HorarioJornadaMunicipal, JornadaMunicipal,
    JustificativaPontoMunicipal, LancamentoFolhaMunicipal,
    MovimentacaoBancoHorasMunicipal, PeriodoPontoMunicipal, PontoServidor,
    RemuneracaoBaseServidorMunicipal, Secretaria, Servidor,
    SolicitacaoHoraExtraMunicipal,
)
from .phase_c_forms import (
    AtribuicaoJornadaMunicipalForm, BeneficioServidorMunicipalForm,
    DecisionPontoForm, HoraExtraMunicipalForm, LancamentoInformativoFolhaForm,
    ManualPunchForm, RemuneracaoBaseMunicipalForm,
    HorarioJornadaMunicipalForm, JornadaMunicipalForm,
    JustificativaPontoForm, PeriodActionForm, ServidorMunicipalForm,
)
from .phase_c_services import (
    bank_balance_minutes, decide_request, register_manual_punch, register_punch,
    request_justification, request_overtime, transition_period,
)
from .public_services import audit_public, has_municipal_permission, require_municipal_permission, scoped_queryset


def _context(request, **extra):
    from .public_views import _context as public_context
    return public_context(request, **extra)


def _active_month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return start, end


@login_required
def rh_dashboard(request):
    require_municipal_permission(request.user, 'rh.view', module='rh_municipal')
    org=current_organization()
    servers=scoped_queryset(request.user, Servidor.objects.filter(organization=org))
    context={
        'title':'RH Municipal',
        'active_servers':servers.filter(ativo=True,situacao_funcional='ATIVO').count(),
        'away_servers':servers.filter(situacao_funcional='AFASTADO').count(),
        'secretaries':scoped_queryset(request.user,Secretaria.objects.filter(organization=org,ativo=True)).count(),
        'pending_leave':scoped_queryset(request.user,AfastamentoServidor.objects.filter(organization=org,status='SOLICITADO')).count(),
        'pending_vacation':scoped_queryset(request.user,FeriasServidor.objects.filter(organization=org,status='SOLICITADA')).count(),
        'employee_rows':servers.select_related('secretaria','unidade','cargo','jornada').order_by('nome')[:100],
        'can_manage_rh':has_municipal_permission(request.user,'rh.manage',module='rh_municipal'),
        'can_see_documents':has_municipal_permission(request.user,'rh.documents',module='rh_municipal'),
        'can_see_payroll':has_municipal_permission(request.user,'folha.view',module='rh_municipal'),
    }
    return render(request,'rh_municipal/phase_c_rh_dashboard.html',_context(request,**context))


@login_required
@require_http_methods(['GET','POST'])
def employee_register(request):
    require_municipal_permission(request.user,'rh.manage',module='rh_municipal')
    form=ServidorMunicipalForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                row=form.save(commit=False)
                row.organization=current_organization()
                row.save()
                event=HistoricoServidor(organization=row.organization,servidor=row,
                    acao='CADASTRO_FUNCIONAL',depois={'matricula':row.matricula,'situacao':row.situacao_funcional},
                    usuario=request.user,motivo='Cadastro funcional municipal')
                event._service_write=True; event.save()
                audit_public(request.user,'RH_SERVIDOR_CRIADO',row,{'matricula':row.matricula,'public_id':str(row.public_id)})
        except (ValidationError,IntegrityError) as exc:
            form.add_error(None,'; '.join(getattr(exc,'messages',[str(exc)])))
        else:
            messages.success(request,'Ficha funcional criada com trilha de histórico.')
            return redirect(reverse('rh_municipal_public:rh_municipal_employees'))
    org=current_organization()
    rows=scoped_queryset(request.user,Servidor.objects.filter(organization=org)).select_related('secretaria','unidade','cargo').order_by('nome')[:200]
    return render(request,'rh_municipal/phase_c_employees.html',_context(request,form=form,rows=rows,
        can_manage_rh=True, title='Servidores municipais'))


@login_required
@require_http_methods(['GET','POST'])
def journeys(request):
    require_municipal_permission(request.user,'rh.manage',module='rh_municipal')
    selected=request.POST.get('form_type') if request.method=='POST' else ''
    journey_form=JornadaMunicipalForm(request.POST if selected=='journey' else None)
    hours_form=HorarioJornadaMunicipalForm(request.POST if selected=='hours' else None)
    assignment_form=AtribuicaoJornadaMunicipalForm(request.POST if selected=='assignment' else None)
    if request.method=='POST':
        form={'journey':journey_form,'hours':hours_form,'assignment':assignment_form}.get(selected)
        if form is None:
            messages.error(request,'Selecione uma operação de jornada válida.')
        elif form.is_valid():
            try:
                with transaction.atomic():
                    row=form.save(commit=False); row.organization=current_organization()
                    if isinstance(row,AtribuicaoJornadaMunicipal): row.criado_por=request.user
                    row.save()
                    audit_public(request.user,'RH_JORNADA_CONFIGURADA',row,{'tipo':selected,'id':row.pk})
            except (ValidationError,IntegrityError) as exc:
                form.add_error(None,'; '.join(getattr(exc,'messages',[str(exc)])))
            else:
                messages.success(request,'Configuração de jornada salva e auditada.')
                return redirect('rh_municipal_public:rh_municipal_journeys')
    org=current_organization()
    return render(request,'rh_municipal/phase_c_journeys.html',_context(request,
        journeys=scoped_queryset(request.user,JornadaMunicipal.objects.filter(organization=org)).prefetch_related('horarios_detalhados').order_by('nome'),
        assignments=scoped_queryset(request.user,AtribuicaoJornadaMunicipal.objects.filter(organization=org)).select_related('servidor','grupo','jornada','escala').order_by('-inicio_vigencia')[:100],
        journey_form=journey_form,hours_form=hours_form,assignment_form=assignment_form,
        can_manage_rh=True,title='Jornadas e escalas'))


@login_required
@require_http_methods(['GET','POST'])
def point_home(request):
    if not (has_municipal_permission(request.user,'servidor.portal',module='ponto_digital')
            or has_municipal_permission(request.user,'ponto.view',module='ponto_digital')
            or has_municipal_permission(request.user,'ponto.register',module='ponto_digital')):
        raise PermissionDenied('Ponto Digital indisponível para seu vínculo, escopo ou plano.')
    org=current_organization(); self_server=Servidor.objects.filter(organization=org,usuario=request.user,ativo=True).first()
    justification_form=JustificativaPontoForm(request.POST if request.POST.get('action')=='justification' else None)
    overtime_form=HoraExtraMunicipalForm(request.POST if request.POST.get('action')=='overtime' else None)
    if request.method=='POST':
        action=request.POST.get('action')
        try:
            if action=='punch':
                row,created=register_punch(request.user,request.POST.get('tipo'),request.POST.get('request_id'),request=request,device=request.POST.get('device',''))
                messages.success(request,'Marcação registrada.' if created else 'Esta marcação já havia sido recebida; nenhuma duplicidade foi criada.')
            elif action=='justification' and justification_form.is_valid():
                request_justification(
                    request.user, start=justification_form.cleaned_data['inicio'],
                    end=justification_form.cleaned_data['fim'],
                    reason=justification_form.cleaned_data['motivo'],
                    description=justification_form.cleaned_data['descricao'],
                )
                messages.success(request,'Justificativa enviada para análise.')
            elif action=='overtime' and overtime_form.is_valid():
                request_overtime(
                    request.user, start=overtime_form.cleaned_data['inicio'],
                    end=overtime_form.cleaned_data['fim'],
                    justification=overtime_form.cleaned_data['justificativa'],
                )
                messages.success(request,'Solicitação de hora extra enviada para aprovação.')
            else:
                raise ValidationError('Revise os dados informados para esta solicitação.')
            return redirect('rh_municipal_public:ponto_home')
        except (ValidationError,PermissionDenied,ValueError) as exc:
            messages.error(request,'; '.join(getattr(exc,'messages',[str(exc)])))
    today=timezone.localdate(); punches=[]; balance=None; expected=None
    if self_server:
        punches=PontoServidor.objects.filter(organization=org,servidor=self_server,data_hora__date=today).order_by('data_hora')
        balance=bank_balance_minutes(self_server)
        last=punches.last(); expected={'ENTRADA':'SAIDA_INTERVALO','SAIDA_INTERVALO':'RETORNO_INTERVALO','RETORNO_INTERVALO':'SAIDA','SAIDA':None}.get(last.tipo if last else None,'ENTRADA')
    manager=has_municipal_permission(request.user,'ponto.view',module='ponto_digital')
    if self_server and not has_municipal_permission(request.user,'servidor.portal',module='ponto_digital') and not has_municipal_permission(request.user,'ponto.register',module='ponto_digital'):
        raise PermissionDenied('Você não pode consultar este Ponto Digital.')
    scoped_server_cards=[]
    if manager:
        manager_servers=scoped_queryset(request.user,Servidor.objects.filter(organization=org,ativo=True)).select_related('unidade').order_by('nome')[:100]
        for server in manager_servers:
            scoped_server_cards.append({'server':server,'punch_count':PontoServidor.objects.filter(
                organization=org,servidor=server,data_hora__date=today,
            ).count()})
    context=_context(request,title='Ponto Digital',self_server=self_server,punches=punches,
        expected_punch=expected,bank_balance_minutes=balance,manager=manager,
        scoped_server_cards=scoped_server_cards,
        server_now=timezone.localtime(),
        justification_form=justification_form,overtime_form=overtime_form,
        overtime_rows=(SolicitacaoHoraExtraMunicipal.objects.filter(organization=org,servidor=self_server).order_by('-criado_em')[:10] if self_server else []),
        justification_rows=(JustificativaPontoMunicipal.objects.filter(organization=org,servidor=self_server).order_by('-criado_em')[:10] if self_server else []),
        can_register=bool(self_server and expected and (has_municipal_permission(request.user,'servidor.portal',module='ponto_digital') or has_municipal_permission(request.user,'ponto.register',module='ponto_digital'))),
        can_approve=has_municipal_permission(request.user,'ponto.approve',module='ponto_digital'),
        municipal_location_enabled=bool(getattr(settings, 'MUNICIPAL_POINT_LOCATION_ENABLED', False)),
        pwa_point=True)
    return render(request,'rh_municipal/phase_c_point_home.html',context)


@login_required
@require_http_methods(['GET','POST'])
def point_approvals(request):
    require_municipal_permission(request.user,'ponto.approve',module='ponto_digital')
    form=DecisionPontoForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            decide_request(request.user,request_type=form.cleaned_data['tipo'],request_id=form.cleaned_data['solicitacao_id'],
                approve=form.cleaned_data['aprovada'],reason=form.cleaned_data['motivo'])
        except (ValidationError,PermissionDenied) as exc:
            form.add_error(None,'; '.join(getattr(exc,'messages',[str(exc)])))
        else:
            messages.success(request,'Decisão registrada no histórico do Ponto.')
            return redirect('rh_municipal_public:ponto_approvals')
    org=current_organization()
    pending_justifications=scoped_queryset(request.user,JustificativaPontoMunicipal.objects.filter(organization=org,status='PENDENTE')).select_related('servidor')
    pending_overtime=scoped_queryset(request.user,SolicitacaoHoraExtraMunicipal.objects.filter(organization=org,status='PENDENTE')).select_related('servidor')
    return render(request,'rh_municipal/phase_c_point_approvals.html',_context(request,title='Aprovações de ponto',
        pending_justifications=pending_justifications,pending_overtime=pending_overtime,form=form))


@login_required
@require_http_methods(['GET', 'POST'])
def point_adjustments(request):
    require_municipal_permission(request.user, 'ponto.adjust', module='ponto_digital')
    form = ManualPunchForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            row = register_manual_punch(
                request.user, server_id=form.cleaned_data['servidor'].pk,
                kind=form.cleaned_data['tipo'], occurred_at=form.cleaned_data['data_hora'],
                reason=form.cleaned_data['motivo'],
            )
        except (ValidationError, PermissionDenied, IntegrityError) as exc:
            form.add_error(None, '; '.join(getattr(exc, 'messages', [str(exc)])))
        else:
            messages.success(request, 'Ajuste registrado como novo evento imutável.')
            return redirect('rh_municipal_public:ponto_adjustments')
    return render(request, 'rh_municipal/phase_c_point_adjustments.html', _context(
        request, title='Ajustes de ponto', form=form,
        can_adjust_ponto=True,
    ))


@login_required
@require_http_methods(['GET','POST'])
def point_periods(request):
    if request.method=='POST' and request.POST.get('action')=='create':
        require_municipal_permission(request.user,'ponto.close',module='ponto_digital')
        try:
            year=int(request.POST.get('ano','')); month=int(request.POST.get('mes',''))
            if not 1900<=year<=2200 or not 1<=month<=12: raise ValueError
            row,created=PeriodoPontoMunicipal.objects.get_or_create(organization=current_organization(),ano=year,mes=month,defaults={'aberto_por':request.user})
            messages.success(request,'Período criado.' if created else 'Este período já existe; nenhuma duplicidade foi criada.')
            return redirect('rh_municipal_public:ponto_periods')
        except (ValueError,IntegrityError):
            messages.error(request,'Informe ano e mês válidos.')
    require_municipal_permission(request.user,'ponto.view',module='ponto_digital')
    org=current_organization()
    rows=scoped_queryset(request.user,PeriodoPontoMunicipal.objects.filter(organization=org)).order_by('-ano','-mes')
    can_close=has_municipal_permission(request.user,'ponto.close',module='ponto_digital')
    if request.method=='POST' and request.POST.get('action')=='transition':
        form=PeriodActionForm(request.POST)
        if form.is_valid():
            try: transition_period(request.user,period_id=form.cleaned_data['periodo_id'],action=form.cleaned_data['acao'],reason=form.cleaned_data['motivo'])
            except (ValidationError,PermissionDenied) as exc: messages.error(request,'; '.join(getattr(exc,'messages',[str(exc)])))
            else: messages.success(request,'Etapa do período registrada com snapshot e auditoria.')
            return redirect('rh_municipal_public:ponto_periods')
    return render(request,'rh_municipal/phase_c_point_periods.html',_context(request,title='Fechamento do ponto',periods=rows,can_close=can_close))


@login_required
def monthly_mirror(request,public_id):
    org=current_organization(); server=scoped_queryset(request.user,Servidor.objects.filter(organization=org)).filter(public_id=public_id).select_related('secretaria','unidade','jornada').first()
    if server is None: raise Http404
    own=server.usuario_id==request.user.pk and has_municipal_permission(request.user,'servidor.portal',module='ponto_digital')
    if not own:
        require_municipal_permission(request.user,'ponto.report',module='ponto_digital',record=server)
    try: year=int(request.GET.get('ano',timezone.localdate().year)); month=int(request.GET.get('mes',timezone.localdate().month))
    except ValueError: raise Http404
    if not 1900<=year<=2200 or not 1<=month<=12: raise Http404
    start,end=_active_month_bounds(year,month)
    punches=PontoServidor.objects.filter(organization=org,servidor=server,data_hora__date__gte=start,data_hora__date__lt=end).order_by('data_hora')
    overtime=SolicitacaoHoraExtraMunicipal.objects.filter(organization=org,servidor=server,inicio__date__gte=start,inicio__date__lt=end)
    justifications=JustificativaPontoMunicipal.objects.filter(organization=org,servidor=server,inicio__date__gte=start,inicio__date__lt=end)
    movements=MovimentacaoBancoHorasMunicipal.objects.filter(organization=org,servidor=server).order_by('criado_em')
    return render(request,'rh_municipal/phase_c_mirror.html',_context(request,title='Espelho mensal de ponto',server=server,
        year=year,month=month,punches=punches,overtime=overtime,justifications=justifications,
        bank_balance_minutes=bank_balance_minutes(server),movements=movements,printable=True,
        calculation_notice='Atrasos, faltas e totais legais aguardam regra homologada pela Prefeitura.'), content_type='text/html')


@login_required
@require_http_methods(['GET','POST'])
def payroll_foundation(request):
    require_municipal_permission(request.user,'folha.view',module='rh_municipal')
    org=current_organization(); can_manage=has_municipal_permission(request.user,'folha.manage',module='rh_municipal')
    action=request.POST.get('action') if request.method == 'POST' else ''
    remuneration_form=RemuneracaoBaseMunicipalForm(request.POST if action == 'remuneracao' else None)
    benefit_form=BeneficioServidorMunicipalForm(request.POST if action == 'beneficio' else None)
    launch_form=LancamentoInformativoFolhaForm(request.POST if action == 'lancamento' else None)

    def render_page():
        return render(request,'rh_municipal/phase_c_payroll.html',_context(request,title='Fundação da Folha',can_manage_folha=can_manage,
            remuneration_form=remuneration_form,benefit_form=benefit_form,launch_form=launch_form,
            competencies=scoped_queryset(request.user,CompetenciaFolhaMunicipal.objects.filter(organization=org)).order_by('-ano','-mes'),
            events=scoped_queryset(request.user,EventoFolhaMunicipal.objects.filter(organization=org,ativo=True)).order_by('codigo'),
            launches=scoped_queryset(request.user,LancamentoFolhaMunicipal.objects.filter(organization=org)).select_related('servidor','evento','competencia').order_by('-pk')[:100],
            active_servers=scoped_queryset(request.user,Servidor.objects.filter(organization=org,ativo=True)).count(),
            limitation='Fundação de dados sem cálculo legal, tributário, previdenciário, trabalhista ou geração de folha oficial.'))

    if request.method=='POST':
        if not can_manage: raise PermissionDenied
        try:
            if action=='competencia':
                year=int(request.POST.get('ano','')); month=int(request.POST.get('mes',''))
                if not (1900<=year<=2200 and 1<=month<=12): raise ValueError
                row,created=CompetenciaFolhaMunicipal.objects.get_or_create(organization=org,ano=year,mes=month,defaults={'criado_por':request.user})
                messages.success(request,'Competência criada.' if created else 'Competência já existente.')
            elif action=='evento':
                row=EventoFolhaMunicipal(organization=org,codigo=request.POST.get('codigo','').strip(),nome=request.POST.get('nome','').strip(),natureza=request.POST.get('natureza',''),referencia=request.POST.get('referencia',''))
                row.save(); audit_public(request.user,'FOLHA_EVENTO_FUNDACAO_CRIADO',row,{'codigo':row.codigo,'natureza':row.natureza})
                messages.success(request,'Evento cadastrado como fundação informativa; nenhum cálculo foi executado.')
            elif action in {'remuneracao','beneficio','lancamento'}:
                form={'remuneracao':remuneration_form,'beneficio':benefit_form,'lancamento':launch_form}[action]
                if not form.is_valid():
                    form.add_error(None, 'Revise os campos destacados antes de salvar.')
                    return render_page()
                row=form.save(commit=False)
                row.organization=org
                if hasattr(row,'criado_por_id'):
                    row.criado_por=request.user
                row.save()
                audit_public(request.user,'FOLHA_FUNDACAO_'+action.upper()+'_CRIADO',row,{'id':row.pk,'tipo':action})
                messages.success(request,'Registro informativo incluído. Nenhum valor de folha foi calculado.')
            else: raise ValueError
        except (ValueError,ValidationError,IntegrityError) as exc:
            if action in {'remuneracao','beneficio','lancamento'}:
                {'remuneracao':remuneration_form,'beneficio':benefit_form,'lancamento':launch_form}[action].add_error(None, '; '.join(getattr(exc,'messages',[str(exc)])))
                return render_page()
            messages.error(request,'Revise os campos: '+ '; '.join(getattr(exc,'messages',[str(exc)])))
        return redirect('rh_municipal_public:folha_home')
    return render_page()


def point_manifest(request):
    manifest={
        'id':'/gestao-publica/ponto/','name':'VERTYX Ponto Digital','short_name':'VERTYX Ponto',
        'start_url':'/gestao-publica/ponto/','scope':'/gestao-publica/ponto/',
        'display':'standalone','background_color':'#f4f7fa','theme_color':'#123b67',
        'description':'Registro e consulta de ponto digital municipal.',
        'icons':[{'src':'/static/pwa/ponto-digital-icon.svg','sizes':'any','type':'image/svg+xml','purpose':'any'},
                 {'src':'/static/pwa/icon-192.png','sizes':'192x192','type':'image/png'},
                 {'src':'/static/pwa/icon-512.png','sizes':'512x512','type':'image/png','purpose':'any maskable'}],
    }
    response=HttpResponse(json.dumps(manifest,ensure_ascii=False),content_type='application/manifest+json')
    response['Cache-Control']='no-store'
    return response


def point_worker(request):
    script=(Path(settings.BASE_DIR)/'static/pwa/ponto-digital-sw.js').read_text(encoding='utf-8')
    response=HttpResponse(script,content_type='application/javascript')
    response['Service-Worker-Allowed']='/gestao-publica/ponto/'
    response['Cache-Control']='no-store'
    return response
