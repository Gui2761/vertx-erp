"""Contract-gated Education services with school scope, audit and transactions."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count

from platform_core.context import current_organization
from . import phase_h_models as m
from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, require_municipal_permission, scoped_queryset


def _require(actor, capability):
    org = current_organization()
    if org is None:
        raise PermissionDenied('Selecione uma Prefeitura ativa para continuar.')
    if not public_module_available(org, m.EDUCATION_MODULE):
        raise PermissionDenied('Educação Municipal não está contratada e ativa para esta Prefeitura.')
    require_municipal_permission(actor, capability, module=m.EDUCATION_MODULE)
    return org


def _record_allowed(actor, capability, record):
    if record.organization_id != current_organization().pk or not has_municipal_permission(
        actor, capability, module=m.EDUCATION_MODULE, record=record,
    ):
        raise PermissionDenied('O registro está fora do escopo educacional autorizado.')


def _audit(actor, org, action, row, before=None, after=None):
    return m.EventoEducacaoMunicipal.objects.create(
        organization=org, unidade_id=getattr(row, 'unidade_id', None),
        secretaria_id=getattr(row, 'secretaria_id', None),
        departamento_id=getattr(row, 'departamento_id', None),
        setor_id=getattr(row, 'setor_id', None), acao=action,
        entidade=row._meta.label_lower, entidade_id=row.pk,
        antes=before or {}, depois=after or {}, usuario=actor,
    )


def education_dashboard(actor):
    org = _require(actor, 'educacao.dashboard.view')
    schools = scoped_queryset(actor, m.EscolaMunicipal.objects.filter(organization=org, ativa=True))
    school_ids = schools.values('pk')
    classes = m.TurmaMunicipal.objects.filter(organization=org, escola_id__in=school_ids, ativa=True)
    enrollments = m.MatriculaAlunoMunicipal.objects.filter(
        organization=org, escola_id__in=school_ids, status=m.MatriculaAlunoMunicipal.Status.ATIVA,
    )
    return {
        'schools': schools.count(), 'classes': classes.count(),
        'students': enrollments.values('cidadao_id').distinct().count(),
        'active_enrollments': enrollments.count(),
        'teachers': m.LotacaoProfessorTurma.objects.filter(
            organization=org, turma_id__in=classes.values('pk'), ativa=True,
        ).values('servidor_id').distinct().count(),
    }


@transaction.atomic
def configure_school(actor, *, unit_id, data):
    org = _require(actor, 'educacao.schools.manage')
    from .models import UnidadeMunicipal
    unit = UnidadeMunicipal.objects.filter(organization=org, pk=unit_id, ativo=True).first()
    if unit is None:
        raise ValidationError('Unidade municipal não encontrada nesta Prefeitura.')
    candidate = m.EscolaMunicipal(organization=org, unidade=unit, **data)
    _record_allowed(actor, 'educacao.schools.manage', candidate)
    candidate.full_clean()
    row, created = m.EscolaMunicipal.objects.update_or_create(
        organization=org, unidade=unit, defaults={
            'codigo_inep': candidate.codigo_inep, 'tipo': candidate.tipo,
            'etapas': candidate.etapas, 'ativa': candidate.ativa,
            'secretaria': candidate.secretaria, 'departamento': candidate.departamento,
            'setor': candidate.setor,
        },
    )
    _audit(actor, org, 'ESCOLA_CONFIGURADA' if created else 'ESCOLA_ATUALIZADA', row,
           after={'unidade': unit.pk, 'codigo_inep': row.codigo_inep, 'tipo': row.tipo})
    return row


@transaction.atomic
def create_student_identity(actor, *, data):
    """Create a shared municipal identity, without touching clinical records."""
    org = _require(actor, 'educacao.students.manage')
    from .phase_g_models import CidadaoSaudeMunicipal
    row = CidadaoSaudeMunicipal(organization=org, **data)
    _record_allowed(actor, 'educacao.students.manage', row)
    row.save()
    _audit(actor, org, 'IDENTIDADE_ESTUDANTE_CRIADA', row,
           after={'public_id': str(row.public_id)})
    return row


@transaction.atomic
def register_student(actor, *, data):
    """Atomically create the shared identity and its school enrollment."""
    _require(actor, 'educacao.enrollment.manage')
    citizen = create_student_identity(actor, data={
        'nome': data['nome'], 'cpf': data.get('cpf', ''),
        'data_nascimento': data.get('data_nascimento'),
    })
    enrollment = enroll_student(
        actor, citizen_id=citizen.pk, school_id=data['escola'].pk,
        class_id=data['turma'].pk, school_year_id=data['ano_letivo'].pk,
        enrollment_number=data['numero'],
    )
    return citizen, enrollment


@transaction.atomic
def enroll_student(actor, *, citizen_id, school_id, class_id, school_year_id, enrollment_number):
    org = _require(actor, 'educacao.enrollment.manage')
    school = m.EscolaMunicipal.objects.select_for_update().filter(organization=org, pk=school_id, ativa=True).first()
    year = m.AnoLetivoMunicipal.objects.filter(organization=org, pk=school_year_id, ativo=True).first()
    citizen = m.CidadaoSaudeMunicipal.objects.filter(organization=org, pk=citizen_id, situacao='ATIVO').first()
    group = m.TurmaMunicipal.objects.select_for_update().filter(
        organization=org, pk=class_id, escola_id=school_id, ano_letivo_id=school_year_id, ativa=True,
    ).first()
    if not all((school, year, citizen, group)):
        raise ValidationError('Escola, aluno, turma ou ano letivo não encontrado nesta Prefeitura.')
    existing = m.MatriculaAlunoMunicipal.objects.filter(
        organization=org, cidadao=citizen, ano_letivo=year,
    ).first()
    if existing:
        raise ValidationError('Já existe matrícula deste aluno para o ano letivo informado.')
    if group.capacidade and group.matriculas.filter(status=m.MatriculaAlunoMunicipal.Status.ATIVA).count() >= group.capacidade:
        raise ValidationError('A turma atingiu sua capacidade configurada.')
    row = m.MatriculaAlunoMunicipal(
        organization=org, cidadao=citizen, escola=school, turma=group, ano_letivo=year,
        numero=enrollment_number.strip(), criado_por=actor,
        unidade=school.unidade, setor=school.unidade.setor,
        departamento=school.unidade.setor.departamento,
        secretaria=school.unidade.setor.departamento.secretaria,
    )
    _record_allowed(actor, 'educacao.enrollment.manage', row)
    row.save()
    _audit(actor, org, 'MATRICULA_CRIADA', row,
           after={'turma': group.pk, 'ano_letivo': year.pk, 'numero': row.numero})
    return row


@transaction.atomic
def record_attendance(actor, *, enrollment_id, date, status, note=''):
    org = _require(actor, 'educacao.attendance.manage')
    enrollment = m.MatriculaAlunoMunicipal.objects.select_for_update().filter(organization=org, pk=enrollment_id).select_related(
        'escola__unidade__setor__departamento__secretaria',
    ).first()
    if enrollment is None or enrollment.status != m.MatriculaAlunoMunicipal.Status.ATIVA:
        raise ValidationError('Matrícula ativa não encontrada nesta Prefeitura.')
    _record_allowed(actor, 'educacao.attendance.manage', enrollment)
    if not enrollment.ano_letivo.inicio <= date <= enrollment.ano_letivo.fim:
        raise ValidationError('A data informada está fora do ano letivo da matrícula.')
    if status not in m.FrequenciaEscolarMunicipal.Situacao.values:
        raise ValidationError('Situação de frequência inválida.')
    row = m.FrequenciaEscolarMunicipal.objects.filter(
        organization=org, matricula=enrollment, data=date,
    ).first()
    before = {'situacao': row.situacao, 'observacao': row.observacao} if row else {}
    if row is None:
        row = m.FrequenciaEscolarMunicipal(
            organization=org, matricula=enrollment, data=date, situacao=status,
            observacao=note[:300], registrada_por=actor,
            unidade=enrollment.unidade, setor=enrollment.setor,
            departamento=enrollment.departamento, secretaria=enrollment.secretaria,
        )
    else:
        row.situacao, row.observacao, row.registrada_por = status, note[:300], actor
    row.save()
    _audit(actor, org, 'FREQUENCIA_REGISTRADA', row, before,
           {'situacao': row.situacao, 'observacao': row.observacao})
    return row


@transaction.atomic
def record_grade(actor, *, assessment_id, enrollment_id, value):
    org = _require(actor, 'educacao.grades.manage')
    assessment = m.AvaliacaoEscolarMunicipal.objects.select_for_update().filter(organization=org, pk=assessment_id).first()
    enrollment = m.MatriculaAlunoMunicipal.objects.filter(organization=org, pk=enrollment_id).first()
    if not assessment or not enrollment or assessment.turma_id != enrollment.turma_id:
        raise ValidationError('Avaliação ou matrícula não pertence à turma selecionada nesta Prefeitura.')
    _record_allowed(actor, 'educacao.grades.manage', assessment)
    row = m.NotaEscolarMunicipal(organization=org, avaliacao=assessment, matricula=enrollment,
                                valor=value, registrada_por=actor, unidade=assessment.unidade,
                                setor=assessment.setor, departamento=assessment.departamento,
                                secretaria=assessment.secretaria)
    row.full_clean()
    row.save()
    _audit(actor, org, 'NOTA_REGISTRADA', row, after={'avaliacao': assessment.pk, 'valor': str(row.valor)})
    return row

