"""Citizen charts: scoped reads, encrypted events and append-only corrections."""
import base64
import hashlib
import json
import uuid

from cryptography.fernet import InvalidToken
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from platform_core.context import current_organization
from . import phase_g_models as health
from .clinical_forms import ClinicalEventForm, PURPOSES, PrescriptionForm, RecordSearchForm
from .phase_g_services import (_audit, _fernet, _health_hierarchy, _persist_clinical_entry,
                               _record_allowed, _require, read_clinical_entry)
from .public_services import scoped_queryset

MAX_DOCUMENT = 2 * 1024 * 1024


def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def _decrypt(value):
    try:
        return _fernet().decrypt(bytes(value)).decode('utf-8')
    except (InvalidToken, UnicodeError, TypeError) as exc:
        raise ValidationError('Conteúdo clínico indisponível ou inválido.') from exc


def _payload(entry):
    text = _decrypt(entry.conteudo_cifrado)
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != entry.conteudo_hash:
        raise ValidationError('A integridade do registro clínico não pôde ser validada.')
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        value = None
    if isinstance(value, dict) and value.get('schema') == 'vertyx.clinical.v1':
        return value
    return {'kind': 'legado', 'data': {'texto': text}}


def chart_patient(actor, patient_id, *, capability=None):
    org = _require(actor, 'saude.records.view')
    _require(actor, 'saude.patients.view')
    if capability:
        _require(actor, capability)
    patient = health.CidadaoSaudeMunicipal.objects.filter(organization=org, public_id=patient_id).first()
    if patient is None:
        raise PermissionDenied('Prontuário indisponível no escopo autorizado.')
    for code in ('saude.records.view', 'saude.patients.view', *([capability] if capability else [])):
        _record_allowed(actor, code, patient)
    return patient


def find_chart(actor, document):
    # Search is POST-only and restricted to operators; readers navigate from an authorized encounter.
    _require(actor, 'saude.records.create')
    _require(actor, 'saude.records.view')
    org = _require(actor, 'saude.patients.view')
    form = RecordSearchForm({'documento': document})
    if not form.is_valid():
        raise ValidationError('Informe CPF ou CNS completo.')
    value = form.cleaned_data['documento']
    patient = health.CidadaoSaudeMunicipal.objects.filter(
        organization=org, **{'cpf' if len(value) == 11 else 'cns': value},
    ).first()
    if patient is None:
        raise PermissionDenied('Prontuário indisponível no escopo autorizado.')
    patient = chart_patient(actor, patient.public_id, capability='saude.records.create')
    _audit(actor, org, 'PRONTUARIO_LOCALIZADO', patient._meta.label_lower, patient.pk,
           patient.pk, 'Busca exata autorizada')
    return patient


def _encounter(actor, patient_id, encounter_id, *, capability=None, sensitive=False, lock=False):
    patient = chart_patient(actor, patient_id, capability=capability)
    if capability and patient.situacao != 'ATIVO':
        raise ValidationError('O cidadão deve estar ativo para alterar o atendimento.')
    rows = health.AtendimentoSaudeMunicipal.objects.filter(organization=current_organization(), cidadao=patient)
    if lock:
        rows = rows.select_for_update()
    row = rows.filter(public_id=encounter_id).first()
    if row is None:
        raise PermissionDenied('Atendimento indisponível no escopo autorizado.')
    for code in ('saude.records.view', *([capability] if capability else []),
                 *(['saude.records.sensitive'] if sensitive else [])):
        _require(actor, code)
        _record_allowed(actor, code, row)
    return patient, row


def _professional(actor, appointment, capability):
    row = health.ProfissionalSaudeMunicipal.objects.filter(
        organization=current_organization(), unidade_saude=appointment.unidade_saude,
        servidor__usuario=actor, servidor__ativo=True, servidor__situacao_funcional='ATIVO', ativo=True,
        unidade_saude__ativo=True, unidade_saude__unidade__ativo=True,
    ).select_related('servidor', 'equipe').first()
    if row is None or (row.equipe_id and (
        not row.equipe.ativo or row.equipe.organization_id != current_organization().pk
        or row.equipe.unidade_saude_id != row.unidade_saude_id
    )):
        raise PermissionDenied('É necessário vínculo profissional ativo nesta unidade para registrar conteúdo clínico.')
    _record_allowed(actor, capability, row)
    _record_allowed(actor, 'saude.records.sensitive', row)
    return row


def _fingerprint(kind, data):
    return hashlib.sha256(_json({'kind': kind, 'data': data}).encode('utf-8')).hexdigest()


def _replay(actor, appointment, request_id, fingerprint):
    try:
        operation = uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError('Identificador de operação inválido.') from exc
    existing = health.EvolucaoClinicaMunicipal.objects.filter(organization=current_organization(), public_id=operation).first()
    if existing:
        if (existing.atendimento_id != appointment.pk or existing.autor_id != actor.pk
                or _payload(existing).get('fingerprint') != fingerprint):
            raise ValidationError('Esta operação já foi usada com outros dados.')
    return operation, existing


def _append(actor, appointment, professional, kind, data, operation, fingerprint, *, correction=None):
    if appointment.status != 'EM_ATENDIMENTO':
        raise ValidationError('O atendimento deve estar em andamento para receber registros.')
    if appointment.profissional_id is None:
        appointment.profissional = professional
        appointment.save(update_fields=['profissional'])
    payload = {
        'schema': 'vertyx.clinical.v1', 'kind': kind, 'data': data, 'fingerprint': fingerprint,
        'professional': {'id': professional.pk, 'nome': professional.servidor.nome,
                         'ocupacao': professional.ocupacao, 'conselho': professional.conselho,
                         'registro': professional.registro_conselho},
        'unit': {'id': appointment.unidade_saude_id, 'nome': appointment.unidade_saude.unidade.nome},
        'team': {'id': professional.equipe_id, 'nome': professional.equipe.nome if professional.equipe_id else ''},
        'responsible': {'id': appointment.profissional_id,
                        'nome': appointment.profissional.servidor.nome,
                        'equipe': appointment.profissional.equipe.nome if appointment.profissional.equipe_id else ''},
    }
    entry = _persist_clinical_entry(actor, appointment, _json(payload), public_id=operation,
                                    retifica=correction, justification='Registro clínico autorizado')
    if correction:
        _audit(actor, current_organization(), 'REGISTRO_CLINICO_RETIFICADO', entry._meta.label_lower,
               entry.pk, appointment.cidadao_id, 'Retificação com histórico preservado',
               {'anterior': correction.pk, 'atendimento': appointment.pk})
    return entry


@transaction.atomic
def begin_encounter(actor, *, patient_id, unit_id, professional_id, request_id):
    patient = chart_patient(actor, patient_id, capability='saude.records.create')
    health.CidadaoSaudeMunicipal.objects.select_for_update().get(pk=patient.pk, organization=current_organization())
    try:
        operation = uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError('Identificador de operação inválido.') from exc
    unit = health.UnidadeSaudeMunicipal.objects.filter(
        organization=current_organization(), pk=unit_id, ativo=True, unidade__ativo=True,
    ).first()
    professional = health.ProfissionalSaudeMunicipal.objects.filter(
        organization=current_organization(), pk=professional_id, ativo=True, servidor__ativo=True,
        servidor__situacao_funcional='ATIVO', unidade_saude=unit,
    ).first()
    if (unit is None or professional is None or patient.situacao != 'ATIVO'
            or patient.unidade_id != unit.unidade_id or (professional.equipe_id and not professional.equipe.ativo)):
        raise ValidationError('Selecione cidadão, unidade de referência e profissional ativos e compatíveis.')
    for record in (unit, professional):
        _record_allowed(actor, 'saude.records.create', record)
    previous = health.AtendimentoSaudeMunicipal.objects.filter(organization=current_organization(), public_id=operation).first()
    if previous:
        if (previous.cidadao_id != patient.pk or previous.unidade_saude_id != unit.pk
                or previous.profissional_id != professional.pk or previous.criado_por_id != actor.pk):
            raise ValidationError('Esta operação já foi usada com outros dados.')
        return previous
    row = health.AtendimentoSaudeMunicipal.objects.create(
        organization=current_organization(), public_id=operation, cidadao=patient,
        unidade_saude=unit, profissional=professional, criado_por=actor, status='EM_ATENDIMENTO',
        iniciado_em=timezone.now(), **_health_hierarchy(unit),
    )
    _audit(actor, current_organization(), 'ATENDIMENTO_CLINICO_INICIADO', row._meta.label_lower,
           row.pk, patient.pk, details={'unidade': unit.pk, 'profissional': professional.pk})
    return row


@transaction.atomic
def start_scheduled_encounter(actor, *, patient_id, encounter_id):
    _, row = _encounter(actor, patient_id, encounter_id, capability='saude.records.create', sensitive=True, lock=True)
    _professional(actor, row, 'saude.records.create')
    if row.status != 'AGENDADO':
        raise ValidationError('Somente um atendimento agendado pode ser iniciado por esta operação.')
    if row.profissional_id is None:
        row.profissional = _professional(actor, row, 'saude.records.create')
    row.status = 'EM_ATENDIMENTO'
    row.iniciado_em = timezone.now()
    row.save(update_fields=['status', 'iniciado_em', 'profissional'])
    _audit(actor, current_organization(), 'ATENDIMENTO_CLINICO_INICIADO', row._meta.label_lower,
           row.pk, row.cidadao_id, details={'agenda': row.agenda_id})
    return row


@transaction.atomic
def record_event(actor, *, patient_id, encounter_id, data):
    form = ClinicalEventForm(data)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    values = dict(form.cleaned_data)
    correction_id = values.pop('corrige', None)
    request_id = values.pop('request_id')
    kind = values.pop('tipo')
    capability = 'saude.records.edit' if correction_id else 'saude.records.create'
    _, row = _encounter(actor, patient_id, encounter_id, capability=capability, sensitive=True, lock=True)
    professional = _professional(actor, row, capability)
    fingerprint = _fingerprint(kind, {**values, 'retifica': correction_id})
    operation, previous = _replay(actor, row, request_id, fingerprint)
    if previous:
        return previous
    correction = None
    if correction_id:
        correction = health.EvolucaoClinicaMunicipal.objects.filter(
            organization=current_organization(), atendimento=row, public_id=correction_id,
        ).first()
        previous_kind = _payload(correction)['kind'] if correction else None
        if (correction is None or not (previous_kind == kind or (previous_kind == 'legado' and kind == 'evolucao'))
                or health.EvolucaoClinicaMunicipal.objects.filter(organization=current_organization(), retifica=correction).exists()):
            raise ValidationError('Selecione a versão atual de um registro clínico deste atendimento para retificar.')
    return _append(actor, row, professional, kind, values, operation, fingerprint, correction=correction)


@transaction.atomic
def prescribe(actor, *, patient_id, encounter_id, data):
    form = PrescriptionForm(data)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    values = dict(form.cleaned_data)
    request_id = values.pop('request_id')
    _, row = _encounter(actor, patient_id, encounter_id, capability='saude.records.create', sensitive=True, lock=True)
    professional = _professional(actor, row, 'saude.records.create')
    fingerprint = _fingerprint('prescricao', values)
    operation, previous = _replay(actor, row, request_id, fingerprint)
    if previous:
        return previous
    cipher = _fernet()
    hierarchy = _health_hierarchy(row.unidade_saude)
    prescription = health.PrescricaoSaudeMunicipal.objects.create(
        organization=current_organization(), atendimento=row, profissional=professional,
        orientacao_cifrada=cipher.encrypt(values['orientacao'].encode('utf-8')), **hierarchy,
    )
    health.ItemPrescricaoSaude.objects.create(
        organization=current_organization(), prescricao=prescription, medicamento_nome='',
        medicamento_nome_cifrado=cipher.encrypt(values['medicamento'].encode('utf-8')),
        quantidade=values['quantidade'], posologia_cifrada=cipher.encrypt(values['posologia'].encode('utf-8')),
        **hierarchy,
    )
    return _append(actor, row, professional, 'prescricao', {'prescricao_id': prescription.pk}, operation, fingerprint)


@transaction.atomic
def cancel_prescription(actor, *, patient_id, encounter_id, prescription_id, reason):
    _, row = _encounter(actor, patient_id, encounter_id, capability='saude.records.edit', sensitive=True, lock=True)
    professional = _professional(actor, row, 'saude.records.edit')
    if not str(reason or '').strip() or len(reason) > 2000:
        raise ValidationError('Justifique o cancelamento da prescrição em até 2000 caracteres.')
    prescription = health.PrescricaoSaudeMunicipal.objects.filter(
        organization=current_organization(), atendimento=row, public_id=prescription_id,
    ).first()
    if prescription is None or prescription.status != 'ATIVA':
        raise ValidationError('Prescrição ativa não encontrada neste atendimento.')
    entry = _append(actor, row, professional, 'cancelamento_prescricao',
                    {'prescricao_id': prescription.pk, 'motivo': reason}, uuid.uuid4(),
                    _fingerprint('cancelamento_prescricao', prescription.pk))
    prescription.status = 'CANCELADA'
    prescription.save(update_fields=['status'])
    _audit(actor, current_organization(), 'PRESCRICAO_CLINICA_CANCELADA', prescription._meta.label_lower,
           prescription.pk, row.cidadao_id, 'Cancelamento justificado no registro cifrado')
    return entry


@transaction.atomic
def attach_document(actor, *, patient_id, encounter_id, title, uploaded_file, request_id):
    _, row = _encounter(actor, patient_id, encounter_id, capability='saude.records.create', sensitive=True, lock=True)
    professional = _professional(actor, row, 'saude.records.create')
    if not title.strip() or len(title) > 160 or uploaded_file is None:
        raise ValidationError('Informe título e documento PDF.')
    content = uploaded_file.read(MAX_DOCUMENT + 1)
    if not content.startswith(b'%PDF-') or len(content) > MAX_DOCUMENT:
        raise ValidationError('Envie um PDF de até 2 MB.')
    digest = hashlib.sha256(content).hexdigest()
    fingerprint = _fingerprint('documento', {'titulo': title, 'hash': digest})
    operation, previous = _replay(actor, row, request_id, fingerprint)
    if previous:
        return previous
    return _append(actor, row, professional, 'documento',
                   {'titulo': title, 'sha256': digest, 'arquivo': base64.b64encode(content).decode('ascii')},
                   operation, fingerprint)


@transaction.atomic
def conclude_encounter(actor, *, patient_id, encounter_id):
    _, row = _encounter(actor, patient_id, encounter_id, capability='saude.records.edit', sensitive=True, lock=True)
    professional = _professional(actor, row, 'saude.records.edit')
    if not row.evolucoes.exists():
        raise ValidationError('Registre o atendimento antes de concluí-lo.')
    _append(actor, row, professional, 'conclusao', {'situacao': 'CONCLUIDO'}, uuid.uuid4(),
            _fingerprint('conclusao', row.public_id))
    row.status = 'CONCLUIDO'
    row.concluido_em = timezone.now()
    row.save(update_fields=['status', 'concluido_em'])
    _audit(actor, current_organization(), 'ATENDIMENTO_CLINICO_CONCLUIDO', row._meta.label_lower, row.pk, row.cidadao_id)
    return row


@transaction.atomic
def citizen_chart(actor, *, patient_id, encounter_id=None, purpose=None, visit_page=1, event_page=1, prescription_page=1):
    patient = chart_patient(actor, patient_id)
    if purpose is not None and purpose not in dict(PURPOSES):
        raise ValidationError('Selecione uma finalidade de consulta válida.')
    encounters = scoped_queryset(actor, health.AtendimentoSaudeMunicipal.objects.filter(
        organization=current_organization(), cidadao=patient,
    ), capability='saude.records.view').select_related('profissional__servidor', 'unidade_saude__unidade').order_by('-iniciado_em', '-pk')
    visits = Paginator(encounters, 20).get_page(visit_page)
    selected = None
    if encounter_id:
        _, selected = _encounter(actor, patient_id, encounter_id, sensitive=bool(purpose))
    elif visits.object_list:
        selected = visits.object_list[0]
        if purpose:
            _require(actor, 'saude.records.sensitive')
            _record_allowed(actor, 'saude.records.sensitive', selected)
    elif purpose:
        _require(actor, 'saude.records.sensitive')
        _record_allowed(actor, 'saude.records.sensitive', patient)
    if purpose:
        _fernet()
    _audit(actor, current_organization(), 'PRONTUARIO_CIDADAO_ABERTO', patient._meta.label_lower,
           patient.pk, patient.pk, dict(PURPOSES).get(purpose, 'Consulta de metadados'),
           {'atendimento': selected.pk if selected else None})
    events = prescriptions = None
    if selected:
        entries = health.EvolucaoClinicaMunicipal.objects.filter(
            organization=current_organization(), atendimento=selected,
        ).select_related('autor').annotate(has_correction=Exists(
            health.EvolucaoClinicaMunicipal.objects.filter(organization=current_organization(), retifica_id=OuterRef('pk')),
        )).defer('conteudo_cifrado').order_by('criada_em', 'pk')
        events = Paginator(entries, 30).get_page(event_page)
        for entry in events:
            entry.clinical = None
            if purpose:
                # The shared reader records each clinical access before returning plaintext.
                read_clinical_entry(actor, entry_id=entry.pk, justification=dict(PURPOSES)[purpose])
                entry.clinical = _payload(entry)
                if entry.clinical['kind'] == 'documento':
                    entry.clinical['data'].pop('arquivo', None)
                if entry.clinical['kind'] == 'prescricao':
                    prescription = health.PrescricaoSaudeMunicipal.objects.get(
                        organization=current_organization(), atendimento=selected,
                        pk=entry.clinical['data']['prescricao_id'],
                    )
                    entry.clinical['prescription'] = prescription
                    entry.clinical['data'] = {'status': prescription.status}
        if purpose:
            prescriptions = Paginator(health.PrescricaoSaudeMunicipal.objects.filter(
                organization=current_organization(), atendimento=selected,
            ).select_related('profissional__servidor').order_by('emitida_em', 'pk'), 20).get_page(prescription_page)
            for prescription in prescriptions:
                _record_allowed(actor, 'saude.records.sensitive', prescription)
                _audit(actor, current_organization(), 'PRESCRICAO_CLINICA_ACESSADA', prescription._meta.label_lower,
                       prescription.pk, patient.pk, dict(PURPOSES)[purpose])
                prescription.clinical_orientation = _decrypt(prescription.orientacao_cifrada) if prescription.orientacao_cifrada else ''
                prescription.clinical_items = [
                        {'medicamento': _decrypt(item.medicamento_nome_cifrado) if item.medicamento_nome_cifrado else item.medicamento_nome,
                         'quantidade': item.quantidade, 'posologia': _decrypt(item.posologia_cifrada) if item.posologia_cifrada else ''}
                        for item in prescription.itens.filter(organization=current_organization())
                    ]
    family_count = scoped_queryset(actor, health.VinculoFamiliaSaude.objects.filter(
        organization=current_organization(), cidadao=patient, familia__ativo=True,
    ), capability='saude.records.view').count()
    return {'patient': patient, 'visits': visits, 'selected': selected, 'events': events,
            'purpose': purpose or '', 'family_count': family_count, 'prescriptions': prescriptions}


@transaction.atomic
def download_document(actor, *, patient_id, entry_id):
    entry = health.EvolucaoClinicaMunicipal.objects.filter(
        organization=current_organization(), public_id=entry_id,
    ).select_related('atendimento').first()
    if entry is None:
        raise PermissionDenied('Documento indisponível no escopo autorizado.')
    _encounter(actor, patient_id, entry.atendimento.public_id, sensitive=True)
    read_clinical_entry(actor, entry_id=entry.pk, justification='Consulta de documento do atendimento')
    payload = _payload(entry)
    if payload['kind'] != 'documento':
        raise ValidationError('O registro selecionado não é um documento.')
    content = base64.b64decode(payload['data']['arquivo'], validate=True)
    if len(content) > MAX_DOCUMENT or hashlib.sha256(content).hexdigest() != payload['data']['sha256']:
        raise ValidationError('A integridade do documento não pôde ser validada.')
    _audit(actor, current_organization(), 'DOCUMENTO_CLINICO_BAIXADO', entry._meta.label_lower, entry.pk,
           entry.atendimento.cidadao_id, 'Download privado autorizado')
    return content
