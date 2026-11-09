import os
import sys

os.environ['DJANGO_SETTINGS_MODULE'] = 'tecnolmed.test_settings'
import django
django.setup()

from contas.models import Usuario
from platform_core.models import Organization, OrganizationMembership, OrganizationERP, MembershipERP, ERPCatalog, ModuloOrganizacao
from platform_core.saas_models import PlanoSaaS, AssinaturaSaaS, AdministradorPlataforma

# 1. Organization Farmacia
farmacia_org, _ = Organization.objects.get_or_create(
    slug='farmacia-modelo',
    defaults={'razao_social': 'Farmácia Modelo Saúde Ltda', 'nome_fantasia': 'Farmácia Modelo'}
)
erp_assist, _ = ERPCatalog.objects.get_or_create(code='assistencia', defaults={'nome': 'Assistência e Farmácia', 'active': True})
OrganizationERP.objects.get_or_create(organization=farmacia_org, erp=erp_assist, defaults={'enabled': True})

# Plan
plan, _ = PlanoSaaS.objects.get_or_create(
    slug='demo-homologacao',
    defaults={
        'nome': 'DEMO Homologação',
        'preco': 0,
        'descricao': 'Plano piloto com motor FEFO, PDV e financeiro completo.',
        'erp': erp_assist,
        'ativo': True,
        'limites': {'usuarios': 3, 'filiais': 1}
    }
)
AssinaturaSaaS.objects.get_or_create(
    organization=farmacia_org,
    defaults={'plano': plan, 'status': AssinaturaSaaS.Status.ACTIVE}
)

# User farmaceutico
user_farm, _ = Usuario.objects.get_or_create(username='farmaceutico', defaults={'perfil': 'ADMIN', 'email': 'farmacia@modelo.com.br'})
user_farm.set_password('Vertyx#Far2026!X')
user_farm.is_staff = True
user_farm.save()

member_farm, _ = OrganizationMembership.objects.get_or_create(
    organization=farmacia_org, user=user_farm,
    defaults={'role': 'ADMIN', 'status': 'ATIVO'}
)
MembershipERP.objects.get_or_create(membership=member_farm, erp=erp_assist, defaults={'enabled': True})

# 2. Master Admin
master, _ = Usuario.objects.get_or_create(username='vertyx_master', defaults={'is_staff': True, 'is_superuser': True})
master.set_password('virtu@L1')
master.save()
AdministradorPlataforma.objects.get_or_create(user=master, defaults={'active': True, 'created_by': master})

print("Local test users prepared successfully!")
