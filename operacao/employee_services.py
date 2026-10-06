"""Atomic employee registration using current accounts, memberships and HR models."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from platform_core.access import effective_role
from platform_core.context import current_organization
from platform_core.models import OrganizationMembership, MembershipERP, OrganizationERP, ERPCatalog
from platform_core.modules import require_capability
from contas.models import Usuario, Tecnico
from gestao import services as gs
from . import models as m
from .employee_forms import TECH_FIELDS


def snapshot(row, fields):
    return {field: str(getattr(row, field + '_id', getattr(row, field, ''))) for field in fields}


@transaction.atomic
def save_employee(actor, form, journey_form=None):
    require_capability(actor, 'rh')
    role = effective_role(actor)
    if form.actor.pk != actor.pk or form.instance.organization_id != current_organization().pk:
        raise PermissionDenied('Ficha fora do contexto autorizado.')
    if form.manage_access and role != 'ADMIN' or form.manage_technical and role not in {'ADMIN', 'GESTOR'}:
        raise PermissionDenied('A autorização mudou; recarregue a ficha.')
    if not form.is_valid() or journey_form is not None and not journey_form.is_valid():
        raise ValidationError('Revise os dados da ficha e da jornada.')
    data = form.cleaned_data
    existing = m.Funcionario.objects.select_for_update().get(pk=form.instance.pk) if form.instance.pk else None
    before = snapshot(existing, form._meta.fields) if existing else {}
    if data['conta_modo'] == 'NOVA' and existing is None:
        # Never mutate another company's existing identity or password.
        user = Usuario(username=data['username'], first_name=data['nome'][:150],
                       telefone=data.get('telefone', ''), email=data.get('email', ''), perfil=data['perfil'])
        user.set_password(data['password1'])
        user.full_clean()
        user.save()
        member = OrganizationMembership.objects.create(user=user, organization=current_organization(), role=data['perfil'])
        gs.audit(actor, 'RH_CONTA_CRIADA', member, {'usuario': user.pk, 'perfil': member.role})
    else:
        user = existing.usuario if existing else data['usuario']
        member = OrganizationMembership.objects.select_for_update().get(user=user, organization=current_organization(), status='ATIVO')
    if m.Funcionario.objects.filter(usuario=user).exclude(pk=existing.pk if existing else None).exists():
        raise ValidationError('A pessoa já possui ficha nesta organização. Edite a ficha existente.')
    if form.manage_access:
        if user.pk == actor.pk and data['perfil'] != 'ADMIN':
            raise ValidationError('Seu próprio vínculo administrativo deve permanecer ativo.')
        erp = ERPCatalog.objects.get(code='assistencia', active=True)
        enabled = data.get('acesso_assistencia', False)
        if enabled and not OrganizationERP.objects.filter(organization=current_organization(), erp=erp, enabled=True).exists():
            raise ValidationError('Assistência não está habilitada nesta organização.')
        access, _ = MembershipERP.objects.get_or_create(membership=member, erp=erp, defaults={'enabled': False})
        if user.pk == actor.pk and not enabled:
            raise ValidationError('Seu próprio acesso à Assistência não pode ser desativado.')
        access_before = {'perfil': member.role, 'acesso_assistencia': access.enabled}
        member.role = data['perfil']
        member.save(update_fields=['role'])
        access.enabled = enabled
        access.save(update_fields=['enabled'])
        access_after = {'perfil': member.role, 'acesso_assistencia': access.enabled}
        if access_before != access_after:
            gs.audit(actor, 'RH_ACESSO_ALTERADO', member, {'anterior': access_before, 'posterior': access_after})
    if data.get('jornada_modo') == 'NOVA':
        if journey_form is None:
            raise ValidationError('Preencha a nova jornada.')
        journey = journey_form.save()
        gs.audit(actor, 'RH_JORNADA_CRIADA', journey, {'semana': journey.semana, 'nome': journey.nome})
    else:
        journey = data.get('jornada')
    employee = existing or m.Funcionario(organization=current_organization())
    for field in form._meta.fields:
        if field not in {'usuario', 'jornada'}:
            setattr(employee, field, data.get(field))
    employee.usuario = user
    employee.jornada = journey
    if member.role == 'TECNICO':
        technical = Tecnico.objects.select_for_update().filter(usuario=user).first()
        chosen = data.get('tecnico_existente')
        if chosen:
            chosen = Tecnico.objects.select_for_update().get(pk=chosen.pk)
            if chosen.usuario_id not in {None, user.pk} or technical and technical.pk != chosen.pk:
                raise ValidationError('Já existe uma ficha técnica vinculada a esta conta.')
            technical = chosen
        if employee.tecnico_id and (technical is None or employee.tecnico_id != technical.pk):
            raise ValidationError('Vínculo técnico existente deve ser preservado; revise a ficha.')
        technical = technical or Tecnico(organization=current_organization(), usuario=user, nome=employee.nome)
        tech_before = snapshot(technical, ['usuario', 'nome', 'telefone', 'email'] + TECH_FIELDS) if technical.pk else {}
        technical.usuario = user
        technical.nome = employee.nome
        technical.telefone = employee.telefone
        technical.email = employee.email
        if form.manage_technical:
            for field in TECH_FIELDS:
                key = 'tecnico_' + field
                # A first association must not erase an existing professional sheet.
                if existing or not technical.pk or key in form.data and data.get(key) not in (None, ''):
                    setattr(technical, field, data.get(key))
        technical.save()
        gs.audit(actor, 'RH_TECNICO_VINCULADO', technical,
                 {'anterior': tech_before, 'posterior': snapshot(technical, ['usuario', 'nome', 'telefone', 'email'] + TECH_FIELDS)})
        employee.tecnico = technical
    employee.save()
    gs.audit(actor, 'RH_CADASTRO_SALVO', employee,
             {'anterior': before, 'posterior': snapshot(employee, form._meta.fields + ['tecnico']),
              'membership': member.pk, 'perfil': member.role})
    return employee
