"""UBS operations reusing the municipal health domain and permission scopes."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q

from platform_core.context import current_organization
from . import phase_g_models as health
from .phase_g_services import _audit, _health_hierarchy, _record_allowed, _require
from .public_services import has_municipal_permission, scoped_queryset


def primary_capability(actor, *, manage=False):
    capability = 'saude.primary.manage' if manage else 'saude.primary.view'
    if not manage and not has_municipal_permission(actor, capability, module=health.HEALTH_MODULE):
        capability = 'saude.primary.manage'
    _require(actor, capability)
    return capability


def primary_rows(actor, model, *, manage=False):
    capability = primary_capability(actor, manage=manage)
    return scoped_queryset(
        actor, model.objects.filter(organization=current_organization()), capability=capability,
    )


def primary_units(actor, *, manage=False):
    return primary_rows(actor, health.UnidadeSaudeMunicipal, manage=manage).filter(
        ativo=True, tipo__in=('UBS', 'CENTRO'), unidade__ativo=True,
    ).select_related('unidade__setor__departamento__secretaria')


def primary_overview(actor, *, unit_id=None):
    """Return operational counts, never patient identities or household addresses."""
    capability = primary_capability(actor)
    units = primary_units(actor)
    if unit_id is not None:
        units = units.filter(pk=unit_id)
        if not units.exists():
            raise PermissionDenied('UBS indisponível no escopo autorizado.')
    rows = list(units.order_by('unidade__nome').values('pk', 'unidade__nome', 'tipo', 'cnes'))
    ids = [row['pk'] for row in rows]
    families = primary_rows(actor, health.FamiliaTerritorialSaude).filter(
        ativo=True, unidade_saude_id__in=ids,
    )
    family_counts = {row['unidade_saude_id']: row for row in families.values('unidade_saude_id').annotate(
        total=Count('pk', distinct=True), without_team=Count('pk', filter=Q(equipe__isnull=True), distinct=True),
    )}
    teams = primary_rows(actor, health.EquipeSaudeMunicipal).filter(
        ativo=True, unidade_saude_id__in=ids,
    ).values('unidade_saude_id').annotate(total=Count('pk'))
    team_counts = {row['unidade_saude_id']: row['total'] for row in teams}
    for row in rows:
        counts = family_counts.get(row['pk'], {})
        row.update(families=counts.get('total', 0), without_team=counts.get('without_team', 0),
                   teams=team_counts.get(row['pk'], 0))
    _audit(actor, current_organization(), 'ATENCAO_BASICA_CONSULTADA', 'rh_municipal.unidadesaudemunicipal',
           details={'unidades': len(rows), 'capacidade': capability})
    return rows


@transaction.atomic
def create_family(actor, *, data):
    primary_capability(actor, manage=True)
    unit = primary_units(actor, manage=True).filter(pk=getattr(data.get('unidade_saude'), 'pk', None)).first()
    if unit is None:
        raise PermissionDenied('Selecione uma UBS ativa do seu escopo.')
    team = data.get('equipe')
    if team is not None:
        team = primary_rows(actor, health.EquipeSaudeMunicipal, manage=True).filter(
            pk=team.pk, ativo=True, unidade_saude=unit,
        ).first()
        if team is None:
            raise ValidationError('A equipe deve estar ativa e pertencer à UBS selecionada.')
    microarea = (data.get('microarea') or '').strip()
    if team and team.microarea and microarea and microarea != team.microarea:
        raise ValidationError('A microárea deve corresponder à equipe selecionada.')
    family = health.FamiliaTerritorialSaude(
        organization=current_organization(), unidade_saude=unit, equipe=team,
        codigo=data['codigo'], endereco=data['endereco'],
        microarea=microarea or (team.microarea if team else ''),
        **_health_hierarchy(unit),
    )
    _record_allowed(actor, 'saude.primary.manage', family)
    family.save()
    _audit(actor, current_organization(), 'FAMILIA_UBS_CADASTRADA', family._meta.label_lower, family.pk,
           details={'unidade_saude': unit.pk, 'equipe': team.pk if team else None})
    return family


@transaction.atomic
def link_family_member(actor, *, family_id, citizen_public_id=None, citizen_document=None,
                       relationship='', reference=False):
    primary_capability(actor, manage=True)
    _require(actor, 'saude.patients.view')
    if citizen_public_id is not None and citizen_document is not None:
        raise ValidationError('Informe somente um identificador do cidadão.')
    if citizen_document is not None:
        if not citizen_document.isascii() or not citizen_document.isdigit() or len(citizen_document) not in (11, 15):
            raise ValidationError('Informe CPF com 11 dígitos ou CNS com 15 dígitos.')
        lookup = {'cpf' if len(citizen_document) == 11 else 'cns': citizen_document}
    else:
        lookup = {'public_id': citizen_public_id}
    # Lock the citizen before the household to serialize enrollment in different families.
    citizen = health.CidadaoSaudeMunicipal.objects.select_for_update().filter(
        organization=current_organization(), situacao='ATIVO', **lookup,
    ).first()
    family = primary_rows(actor, health.FamiliaTerritorialSaude, manage=True).select_for_update().filter(
        pk=family_id, ativo=True, unidade_saude__ativo=True,
        unidade_saude__tipo__in=('UBS', 'CENTRO'), unidade_saude__unidade__ativo=True,
    ).select_related('unidade_saude__unidade__setor__departamento').first()
    if citizen is None or family is None:
        raise PermissionDenied('Família ou cidadão indisponível no escopo autorizado.')
    _record_allowed(actor, 'saude.patients.view', citizen)
    _record_allowed(actor, 'saude.primary.manage', citizen)
    if citizen.unidade_id != family.unidade_saude.unidade_id:
        raise ValidationError('O cidadão deve ter a mesma unidade de referência da família.')
    members = health.VinculoFamiliaSaude.objects.filter(organization=current_organization(), cidadao=citizen)
    if members.filter(familia__ativo=True).exclude(familia=family).exists():
        raise ValidationError('O cidadão já está vinculado a outra família ativa.')
    relationship = (relationship or '').strip()
    existing = members.filter(familia=family).first()
    if existing:
        if existing.parentesco != relationship or existing.referencia != reference:
            raise ValidationError('O vínculo existente possui outros dados; não foi alterado.')
        return existing
    if reference and family.membros.filter(referencia=True).exists():
        raise ValidationError('A família já possui um cidadão de referência.')
    member = health.VinculoFamiliaSaude(
        organization=current_organization(), familia=family, cidadao=citizen,
        parentesco=relationship, referencia=reference, **_health_hierarchy(family.unidade_saude),
    )
    member.save()
    _audit(actor, current_organization(), 'VINCULO_FAMILIAR_UBS_CRIADO', member._meta.label_lower,
           member.pk, patient_id=citizen.pk, details={'familia': family.pk})
    return member
