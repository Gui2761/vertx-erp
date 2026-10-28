"""Authenticated, contract-gated Education screens."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from platform_core.context import current_organization
from . import phase_h_services as svc
from .phase_h_forms import SchoolSetupForm, StudentEnrollmentForm
from .phase_h_models import EDUCATION_MODULE, EscolaMunicipal, MatriculaAlunoMunicipal
from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, scoped_queryset
from .public_views import _context


def _can(user, capability):
    org = current_organization()
    return bool(org and public_module_available(org, EDUCATION_MODULE)
                and has_municipal_permission(user, capability, module=EDUCATION_MODULE))


@login_required
@require_GET
def education_home(request):
    if not _can(request.user, 'educacao.dashboard.view'):
        raise PermissionDenied('Educação Municipal não contratada ou não autorizada para este acesso.')
    summary = svc.education_dashboard(request.user)
    organization = current_organization()
    can_view_schools = _can(request.user, 'educacao.schools.view') or _can(request.user, 'educacao.schools.manage')
    can_view_students = any(_can(request.user, code) for code in (
        'educacao.students.view', 'educacao.students.manage', 'educacao.enrollment.manage',
    ))
    schools = scoped_queryset(request.user, EscolaMunicipal.objects.filter(
        organization=organization, ativa=True,
    ).select_related('unidade')) if can_view_schools else EscolaMunicipal.objects.none()
    enrollments = scoped_queryset(request.user, MatriculaAlunoMunicipal.objects.filter(
        organization=organization, status=MatriculaAlunoMunicipal.Status.ATIVA,
    ).select_related('cidadao', 'escola__unidade', 'turma', 'ano_letivo'))[:10] if can_view_students else MatriculaAlunoMunicipal.objects.none()
    context = _context(
        request, can_view_education=True,
        can_manage_education_schools=_can(request.user, 'educacao.schools.manage'),
        can_manage_education_students=_can(request.user, 'educacao.students.manage'),
        can_register_education_students=(
            _can(request.user, 'educacao.enrollment.manage')
            and _can(request.user, 'educacao.students.manage')
        ),
        can_view_education_schools=can_view_schools,
        can_view_education_students=can_view_students,
        education_manifest='/gestao-publica/educacao/manifest.webmanifest',
    )
    context.update({'summary': summary, 'schools': schools, 'recent_enrollments': enrollments,
                    'title': 'Educação Municipal',
                    'subtitle': 'Escolas, turmas, matrículas, frequência e calendário no escopo contratado.'})
    return render(request, 'rh_municipal/phase_h_home.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def school_configure(request):
    if not _can(request.user, 'educacao.schools.manage'):
        raise PermissionDenied('Gerenciamento escolar não contratado ou não autorizado.')
    organization = current_organization()
    form = SchoolSetupForm(request.POST or None, organization=organization)
    if request.method == 'POST' and form.is_valid():
        try:
            svc.configure_school(request.user, unit_id=form.cleaned_data['unidade'].pk, data={
                'codigo_inep': form.cleaned_data['codigo_inep'], 'tipo': form.cleaned_data['tipo'],
                'etapas': form.cleaned_data['etapas'], 'ativa': form.cleaned_data['ativa'],
            })
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'Configuração escolar salva para a unidade municipal existente.')
            return redirect('rh_municipal_public:educacao_home')
    context = _context(request, can_view_education=True, can_manage_education_schools=True)
    context.update({'form': form, 'title': 'Configurar escola',
                    'subtitle': 'A configuração fica vinculada a uma Unidade Municipal já cadastrada.'})
    return render(request, 'rh_municipal/phase_h_form.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def student_register(request):
    if not (_can(request.user, 'educacao.enrollment.manage') and _can(request.user, 'educacao.students.manage')):
        raise PermissionDenied('Matrículas escolares não contratadas ou não autorizadas.')
    organization = current_organization()
    form = StudentEnrollmentForm(request.POST or None, organization=organization)
    if request.method == 'POST' and form.is_valid():
        try:
            svc.register_student(request.user, data=form.cleaned_data)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'Identidade municipal e matrícula criadas com sucesso.')
            return redirect('rh_municipal_public:educacao_home')
    context = _context(request, can_view_education=True,
        can_manage_education_schools=_can(request.user, 'educacao.schools.manage'),
        can_manage_education_students=True, can_register_education_students=True)
    context.update({'form': form, 'title': 'Matricular estudante',
                    'subtitle': 'A identidade é compartilhada no cadastro municipal; não são consultados dados clínicos.'})
    return render(request, 'rh_municipal/phase_h_form.html', context)


@login_required
@require_GET
def education_manifest(request):
    if not _can(request.user, 'educacao.dashboard.view'):
        raise PermissionDenied('PWA de Educação não contratado ou não autorizado.')
    body = {'id': '/gestao-publica/educacao/', 'name': 'VERTYX Educação Municipal',
            'short_name': 'VERTYX Educação', 'start_url': '/gestao-publica/educacao/',
            'scope': '/gestao-publica/educacao/', 'display': 'standalone',
            'background_color': '#f4f7fb', 'theme_color': '#123b67'}
    response = HttpResponse(json.dumps(body), content_type='application/manifest+json')
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_GET
def education_worker(request):
    if not _can(request.user, 'educacao.dashboard.view'):
        raise PermissionDenied('PWA de Educação não contratado ou não autorizado.')
    body = "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request,{cache:'no-store'}))});"
    response = HttpResponse(body, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/gestao-publica/educacao/'
    response['Cache-Control'] = 'no-store'
    return response
