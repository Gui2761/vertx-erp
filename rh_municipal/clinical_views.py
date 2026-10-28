import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from . import clinical_services as svc
from .clinical_forms import (ClinicalDocumentForm, ClinicalEventForm, EncounterForm, KINDS,
                             PURPOSES, PrescriptionForm, RecordSearchForm)
from .public_services import has_municipal_permission
from .public_views import _context


def _can(actor, capability, record=None):
    return has_municipal_permission(actor, capability, module='saude_sus', record=record)


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def clinical_home(request):
    svc._require(request.user, 'saude.records.view')
    svc._require(request.user, 'saude.patients.view')
    can_search = _can(request.user, 'saude.records.create')
    if request.method == 'POST' and not can_search:
        raise PermissionDenied('Este acesso permite somente consulta.')
    form = RecordSearchForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        patient = svc.find_chart(request.user, form.cleaned_data['documento'])
        return redirect('rh_municipal_public:saude_citizen_chart', patient_id=patient.public_id)
    return render(request, 'rh_municipal/clinical_home.html', _context(
        request, title='Prontuários e atendimentos', search_form=form, can_search_chart=can_search,
    ))


def _render_chart(request, patient_id, *, encounter_id=None, bound=None, status=200):
    try:
        selected_id = encounter_id or (uuid.UUID(request.GET['atendimento']) if request.GET.get('atendimento') else None)
        chart = svc.citizen_chart(request.user, patient_id=patient_id, encounter_id=selected_id,
                                  purpose=request.GET.get('purpose') or None,
                                  visit_page=request.GET.get('visitas', 1), event_page=request.GET.get('eventos', 1),
                                  prescription_page=request.GET.get('receitas', 1))
    except (ValueError, ValidationError):
        return HttpResponse('Consulta clínica indisponível ou inválida.', status=400)
    patient, selected = chart['patient'], chart['selected']
    can_begin = _can(request.user, 'saude.records.create', patient)
    can_create = can_edit = False
    if selected and selected.status in ('AGENDADO', 'EM_ATENDIMENTO') and _can(request.user, 'saude.records.sensitive', selected):
        for capability in ('saude.records.create', 'saude.records.edit'):
            if _can(request.user, capability, selected) and _can(request.user, capability, patient):
                try:
                    svc._professional(request.user, selected, capability)
                except PermissionDenied:
                    continue
                if capability.endswith('create'):
                    can_create = True
                else:
                    can_edit = True
    can_start = bool(selected and selected.status == 'AGENDADO' and can_create)
    if can_start:
        can_create = can_edit = False
    event_form = ClinicalEventForm() if can_create or can_edit else None
    if request.GET.get('retificar'):
        if not can_edit or not chart['purpose']:
            raise PermissionDenied('Retificação clínica não autorizada.')
        try:
            correction_id = uuid.UUID(request.GET['retificar'])
        except ValueError:
            return HttpResponse('Registro inválido.', status=400)
        entry = next((entry for entry in chart['events'] if entry.public_id == correction_id), None)
        if entry is None or not entry.clinical or entry.clinical['kind'] not in {*dict(KINDS), 'legado'}:
            return HttpResponse('Selecione um registro desta página do histórico.', status=400)
        event_form = ClinicalEventForm(initial={**entry.clinical['data'],
                                               'tipo': 'evolucao' if entry.clinical['kind'] == 'legado' else entry.clinical['kind'],
                                               'corrige': entry.public_id, 'motivo': ''})
    for entry in chart['events'] or []:
        entry.visible_fields = []
        entry.can_correct = False
        if entry.clinical:
            kind = entry.clinical['kind']
            entry.kind_label = dict(KINDS).get(kind, {
                'legado': 'Evolução anterior', 'prescricao': 'Prescrição', 'documento': 'Documento clínico',
                'cancelamento_prescricao': 'Cancelamento de prescrição', 'conclusao': 'Conclusão do atendimento',
            }.get(kind, 'Registro clínico'))
            labels = {key: field.label or key.capitalize() for key, field in ClinicalEventForm.base_fields.items()}
            labels.update(titulo='Documento', orientacao='Orientações', status='Situação', motivo='Motivo', situacao='Situação')
            entry.visible_fields = [(labels[key], value) for key, value in entry.clinical['data'].items()
                                    if key in labels and value not in (None, '')]
            entry.can_correct = can_edit and kind in {*dict(KINDS), 'legado'} and not entry.has_correction
    context = _context(request, title='Prontuário por cidadão', **chart,
                       can_begin_encounter=can_begin, can_create_clinical=can_create, can_edit_clinical=can_edit,
                       can_start_scheduled=can_start,
                       can_read_clinical=bool(selected and _can(request.user, 'saude.records.sensitive', selected)),
                       purposes=PURPOSES,
                       encounter_form=EncounterForm(actor=request.user, patient=patient) if can_begin else None,
                       event_form=event_form,
                       prescription_form=PrescriptionForm() if can_create else None,
                       document_form=ClinicalDocumentForm() if can_create else None)
    if bound:
        context[bound[0]] = bound[1]
    return render(request, 'rh_municipal/citizen_chart.html', context, status=status)


@login_required
@never_cache
@require_GET
def citizen_chart(request, patient_id):
    return _render_chart(request, patient_id)


@login_required
@never_cache
@require_POST
def begin_encounter(request, patient_id):
    patient = svc.chart_patient(request.user, patient_id, capability='saude.records.create')
    form = EncounterForm(request.POST, actor=request.user, patient=patient)
    if form.is_valid():
        try:
            encounter = svc.begin_encounter(request.user, patient_id=patient_id,
                                            unit_id=form.cleaned_data['unidade'].pk,
                                            professional_id=form.cleaned_data['profissional'].pk,
                                            request_id=form.cleaned_data['request_id'])
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            return redirect(reverse('rh_municipal_public:saude_citizen_chart', kwargs={'patient_id': patient_id})
                            + f'?atendimento={encounter.public_id}')
    return _render_chart(request, patient_id, bound=('encounter_form', form), status=400)


@login_required
@never_cache
@require_POST
def clinical_action(request, patient_id, encounter_id):
    action = request.POST.get('action')
    if action not in {'event', 'prescription', 'document', 'conclude', 'cancel_prescription', 'start'}:
        raise PermissionDenied('Operação clínica desconhecida.')
    capability = 'saude.records.edit' if action in {'conclude', 'cancel_prescription'} or request.POST.get('corrige') else 'saude.records.create'
    svc._encounter(request.user, patient_id, encounter_id, capability=capability, sensitive=True)
    svc._require(request.user, capability)
    form = None
    form_key = None
    try:
        if action == 'event':
            form_key, form = 'event_form', ClinicalEventForm(request.POST)
            if form.is_valid():
                svc.record_event(request.user, patient_id=patient_id, encounter_id=encounter_id, data=request.POST)
        elif action == 'prescription':
            form_key, form = 'prescription_form', PrescriptionForm(request.POST)
            if form.is_valid():
                svc.prescribe(request.user, patient_id=patient_id, encounter_id=encounter_id, data=request.POST)
        elif action == 'document':
            form_key, form = 'document_form', ClinicalDocumentForm(request.POST, request.FILES)
            if form.is_valid():
                svc.attach_document(request.user, patient_id=patient_id, encounter_id=encounter_id,
                                    title=form.cleaned_data['titulo'], uploaded_file=form.cleaned_data['arquivo'],
                                    request_id=form.cleaned_data['request_id'])
        elif action == 'start':
            svc.start_scheduled_encounter(request.user, patient_id=patient_id, encounter_id=encounter_id)
        elif action == 'conclude':
            svc.conclude_encounter(request.user, patient_id=patient_id, encounter_id=encounter_id)
        else:
            svc.cancel_prescription(request.user, patient_id=patient_id, encounter_id=encounter_id,
                                    prescription_id=request.POST.get('prescription_id'), reason=request.POST.get('motivo', ''))
    except ValidationError as exc:
        if form is not None:
            form.add_error(None, '; '.join(exc.messages))
        else:
            messages.error(request, '; '.join(exc.messages))
    if form is not None and form.errors:
        return _render_chart(request, patient_id, encounter_id=encounter_id, bound=(form_key, form), status=400)
    return redirect(reverse('rh_municipal_public:saude_citizen_chart', kwargs={'patient_id': patient_id})
                    + f'?atendimento={encounter_id}')


@login_required
@never_cache
@require_GET
def clinical_document(request, patient_id, entry_id):
    try:
        content = svc.download_document(request.user, patient_id=patient_id, entry_id=entry_id)
    except ValidationError:
        return HttpResponse('Documento indisponível ou inválido.', status=400)
    response = HttpResponse(content, content_type='application/octet-stream')
    response['Content-Disposition'] = 'attachment; filename="documento-clinico.pdf"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response
