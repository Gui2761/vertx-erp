"""Contagens SQL no tenant atual, sem limites comerciais e sem carregar registros."""
from django.utils import timezone
from .access import require_erp
from .models import OrganizationMembership
from .context import current_organization


def assistance_usage(user):
    require_erp(user, roles=['ADMIN', 'GESTOR'])
    from clientes.models import Cliente
    from equipamentos.models import Equipamento
    from ordens.models import OrdemServico, Foto, Assinatura
    now = timezone.localtime()
    memberships = OrganizationMembership.objects.filter(organization=current_organization())
    return {'usuarios': memberships.count(), 'usuarios_ativos': memberships.filter(status='ATIVO', user__is_active=True).count(), 'clientes': Cliente.objects.count(), 'equipamentos': Equipamento.objects.count(), 'ordens': OrdemServico.objects.count(), 'ordens_mes': OrdemServico.objects.filter(abertura__gte=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)).count(), 'fotos': Foto.objects.count(), 'comprovantes_assinados': Assinatura.objects.count()}
