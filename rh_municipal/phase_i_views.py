"""Authenticated Control Internal screens; no compliance/legal assertions."""
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from platform_core.context import current_organization
from . import phase_i_models as m
from . import phase_i_services as svc
from .phase_i_forms import (ActionPlanForm, ActionUpdateForm, ControlForm,
    EvidenceForm, FindingForm, RecommendationForm, RiskForm)
from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, scoped_queryset
from .public_views import _context
from .models import Servidor


def _can(user, permission):
    org = current_organization()
    return bool(org and public_module_available(org, m.GOVERNANCE_MODULE) and
                has_municipal_permission(user, permission, module=m.GOVERNANCE_MODULE))


def _render(request, *, form=None, title='Controle Interno', error=None, status=200):
    org = current_organization()
    context = _context(
        request,
        can_view_governance=_can(request.user, 'governance.dashboard.view'),
        can_manage_governance_risks=_can(request.user, 'governance.risks.manage'),
        can_manage_governance_controls=_can(request.user, 'governance.controls.manage'),
        can_manage_governance_findings=_can(request.user, 'governance.findings.manage'),
        can_close_governance_findings=_can(request.user, 'governance.findings.close'),
        can_manage_governance_actions=_can(request.user, 'governance.actions.manage'),
        can_approve_governance_actions=_can(request.user, 'governance.actions.approve'),
        can_manage_governance_evidence=_can(request.user, 'governance.evidence.manage'),
        can_view_governance_evidence=_can(request.user, 'governance.evidence.view'),
    )
    summary = svc.dashboard(request.user) if _can(request.user, 'governance.dashboard.view') else {
        'risks': None, 'controls': None, 'findings': None, 'open_findings': None, 'overdue_actions': None,
    }
    context.update({'organization': org, 'title': title, 'form': form, 'error': error,
                    'governance_summary': summary})
    if _can(request.user, 'governance.risks.view'):
        context['risks'] = scoped_queryset(request.user, m.RiscoControleInterno.objects.filter(organization=org))[:50]
    if _can(request.user, 'governance.controls.view'):
        context['controls'] = scoped_queryset(request.user, m.ControleInternoMunicipal.objects.filter(organization=org))[:50]
    if _can(request.user, 'governance.findings.view'):
        context['findings'] = scoped_queryset(request.user, m.AchadoControleInterno.objects.filter(organization=org).select_related('risco', 'controle').prefetch_related(
            Prefetch('recomendacoes', queryset=m.RecomendacaoControleInterno.objects.filter(organization=org).prefetch_related(
                Prefetch('planos', queryset=m.PlanoAcaoInterno.objects.filter(organization=org))
            )),
            Prefetch('evidencias', queryset=m.EvidenciaControleInterno.objects.filter(organization=org)),
        ))[:50]
    if _can(request.user, 'governance.actions.view'):
        context['action_plans'] = scoped_queryset(request.user, m.PlanoAcaoInterno.objects.filter(organization=org).select_related('recomendacao__achado').prefetch_related(
            Prefetch('evidencias', queryset=m.EvidenciaControleInterno.objects.filter(organization=org)),
        ))[:50]
    if _can(request.user, 'governance.risks.manage'):
        context['risk_form'] = RiskForm(actor=request.user)
    if _can(request.user, 'governance.controls.manage'):
        context['control_form'] = ControlForm(actor=request.user)
    if _can(request.user, 'governance.findings.manage'):
        context['finding_form'] = FindingForm(actor=request.user)
    if _can(request.user, 'governance.actions.manage') or _can(request.user, 'governance.actions.approve'):
        context['governance_action_statuses'] = m.PlanoAcaoInterno.Status.choices
    if _can(request.user, 'governance.actions.manage'):
        context['governance_servers'] = scoped_queryset(request.user, Servidor.objects.filter(organization=org, ativo=True))
    return render(request, 'rh_municipal/phase_i_home.html', context, status=status)


@login_required
@require_GET
def governance_home(request):
    if not _can(request.user, 'governance.dashboard.view') and not any(_can(request.user, capability) for capability in (
        'governance.risks.view', 'governance.risks.manage', 'governance.controls.view',
        'governance.controls.manage', 'governance.findings.view', 'governance.findings.manage',
        'governance.findings.close', 'governance.actions.view', 'governance.actions.manage',
        'governance.actions.approve', 'governance.evidence.view', 'governance.evidence.manage',
    )):
        raise PermissionDenied('Controle Interno não contratado ou não autorizado para esta Prefeitura.')
    return _render(request)


@login_required
@require_POST
def risk_create(request):
    if not _can(request.user, 'governance.risks.manage'):
        raise PermissionDenied('Gerenciamento de riscos não autorizado.')
    form = RiskForm(request.POST, actor=request.user)
    if form.is_valid():
        try:
            svc.create_risk(request.user, data=form.cleaned_data)
        except (PermissionDenied, ValidationError) as exc:
            return _render(request, form=form, title='Novo risco', error='; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
        messages.success(request, 'Risco registrado e auditado.')
        return redirect('rh_municipal_public:governance_home')
    return _render(request, form=form, title='Novo risco', error='Revise os campos informados.', status=400)


@login_required
@require_POST
def control_create(request):
    if not _can(request.user, 'governance.controls.manage'):
        raise PermissionDenied('Gerenciamento de controles não autorizado.')
    form = ControlForm(request.POST, actor=request.user)
    if form.is_valid():
        try:
            svc.create_control(request.user, data=form.cleaned_data)
        except (PermissionDenied, ValidationError) as exc:
            return _render(request, form=form, title='Novo controle', error='; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
        messages.success(request, 'Controle registrado e auditado.')
        return redirect('rh_municipal_public:governance_home')
    return _render(request, form=form, title='Novo controle', error='Revise os campos informados.', status=400)


@login_required
@require_POST
def finding_create(request):
    if not _can(request.user, 'governance.findings.manage'):
        raise PermissionDenied('Registro de achados não autorizado.')
    form = FindingForm(request.POST, actor=request.user)
    if form.is_valid():
        try:
            svc.create_finding(request.user, data=form.cleaned_data)
        except (PermissionDenied, ValidationError) as exc:
            return _render(request, form=form, title='Novo achado', error='; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
        messages.success(request, 'Achado registrado e auditado.')
        return redirect('rh_municipal_public:governance_home')
    return _render(request, form=form, title='Novo achado', error='Revise os campos informados.', status=400)


@login_required
@require_POST
def recommendation_create(request, pk):
    if not _can(request.user, 'governance.findings.manage'):
        raise PermissionDenied('Registro de recomendação não autorizado.')
    form = RecommendationForm(request.POST)
    if form.is_valid():
        try:
            svc.create_recommendation(request.user, finding_id=pk, text=form.cleaned_data['texto'])
        except (PermissionDenied, ValidationError) as exc:
            return HttpResponse('; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
        messages.success(request, 'Recomendação criada e auditada.')
        return redirect('rh_municipal_public:governance_home')
    return HttpResponse('Informe o texto da recomendação.', status=400)


@login_required
@require_POST
def finding_close(request, pk):
    if not _can(request.user, 'governance.findings.close'):
        raise PermissionDenied('Encerramento de achados não autorizado.')
    reason = (request.POST.get('motivo') or '').strip()
    try:
        svc.close_finding(request.user, finding_id=pk, reason=reason)
    except (PermissionDenied, ValidationError) as exc:
        return HttpResponse('; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
    messages.success(request, 'Achado encerrado com justificativa auditada.')
    return redirect('rh_municipal_public:governance_home')


@login_required
@require_POST
def action_plan_create(request, pk):
    if not _can(request.user, 'governance.actions.manage'):
        raise PermissionDenied('Gestão de planos de ação não autorizada.')
    form = ActionPlanForm(request.POST, actor=request.user)
    if form.is_valid():
        try:
            svc.create_action_plan(request.user, recommendation_id=pk, data=form.cleaned_data)
        except (PermissionDenied, ValidationError) as exc:
            return HttpResponse('; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
        messages.success(request, 'Plano de ação criado e auditado.')
        return redirect('rh_municipal_public:governance_home')
    return HttpResponse('Revise os dados do plano de ação.', status=400)


@login_required
@require_POST
def action_plan_update(request, pk):
    form = ActionUpdateForm(request.POST)
    if not form.is_valid():
        return HttpResponse('Revise a situação do plano.', status=400)
    status = form.cleaned_data['status']
    approve = status == m.PlanoAcaoInterno.Status.CONCLUIDO
    try:
        svc.update_action_plan(request.user, plan_id=pk, status=status,
                               description=form.cleaned_data['descricao'], approve=approve)
    except (PermissionDenied, ValidationError) as exc:
        return HttpResponse('; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
    messages.success(request, 'Plano atualizado; a decisão foi registrada no histórico.')
    return redirect('rh_municipal_public:governance_home')


@login_required
@require_POST
def evidence_upload(request):
    if not _can(request.user, 'governance.evidence.manage'):
        raise PermissionDenied('Envio de evidência não autorizado.')
    form = EvidenceForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            svc.upload_evidence(request.user, finding_id=request.POST.get('finding_id') or None,
                                plan_id=request.POST.get('plan_id') or None,
                                title=form.cleaned_data['titulo'], uploaded_file=form.cleaned_data['arquivo'],
                                content_type=getattr(form.cleaned_data['arquivo'], 'content_type', ''))
        except (PermissionDenied, ValidationError) as exc:
            return HttpResponse('; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc), status=400)
        messages.success(request, 'Evidência anexada em armazenamento privado e auditada.')
        return redirect('rh_municipal_public:governance_home')
    return HttpResponse('Informe título e arquivo de evidência.', status=400)


@login_required
@require_GET
def evidence_download(request, pk):
    if not _can(request.user, 'governance.evidence.view'):
        raise PermissionDenied('Consulta de evidências não autorizada.')
    evidence = svc.permitted_evidence(request.user, pk)
    if evidence is None:
        raise Http404
    svc.audit_evidence_access(request.user, evidence)
    response = FileResponse(evidence.arquivo.open('rb'), as_attachment=True,
                            filename=Path(evidence.nome_original).name)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response
