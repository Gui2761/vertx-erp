from django.core.exceptions import PermissionDenied
from .context import current_organization
from .models import OrganizationMembership, OrganizationERP, MembershipERP


def membership_for(user, organization=None):
    organization = organization or current_organization()
    if organization is None or not user.is_authenticated or not user.is_active or organization.status != 'ATIVA':
        return None
    return OrganizationMembership.objects.filter(user=user, organization=organization, status='ATIVO').first()


def has_erp_access(user, organization=None, code='assistencia'):
    membership = membership_for(user, organization)
    if membership is None:
        return False
    return OrganizationERP.objects.filter(organization=membership.organization, erp__code=code, erp__active=True, enabled=True).exists() and MembershipERP.objects.filter(membership=membership, erp__code=code, erp__active=True, enabled=True).exists()


def require_erp(user, organization=None, roles=None):
    membership = membership_for(user, organization)
    if membership is None or not has_erp_access(user, organization) or roles is not None and membership.role not in roles:
        raise PermissionDenied('Organização, acesso ao ERP ou permissão insuficiente.')
    return membership


def effective_role(user):
    membership = membership_for(user)
    return membership.role if membership else ''
