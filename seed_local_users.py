import os
import sys

os.environ['DJANGO_SETTINGS_MODULE'] = 'tecnolmed.test_settings'
import django
django.setup()

from contas.models import Usuario
from platform_core.models import (
    Organization, OrganizationMembership, OrganizationERP, MembershipERP,
    ERPCatalog, ModuloOrganizacao, ERPProductModule, PlanoProdutoModulo
)
from platform_core.saas_models import PlanoSaaS, AssinaturaSaaS, AdministradorPlataforma
from platform_core.context import tenant_context

# 1. Master Admin
master, _ = Usuario.objects.get_or_create(username='vertyx_master', defaults={'is_staff': True, 'is_superuser': True})
master.set_password('virtu@L1')
master.save()
AdministradorPlataforma.objects.get_or_create(user=master, defaults={'active': True, 'created_by': master})

# ERPs
erp_assist, _ = ERPCatalog.objects.get_or_create(code='assistencia', defaults={'nome': 'Assistência e Farmácia', 'active': True})
erp_gestao, _ = ERPCatalog.objects.get_or_create(code='gestao_publica', defaults={'nome': 'Gestão Pública Municipal', 'active': True})

# 2. Org Farmacia Modelo
farmacia_org, _ = Organization.objects.get_or_create(
    slug='farmacia-modelo',
    defaults={'razao_social': 'Farmácia Modelo Saúde Ltda', 'nome_fantasia': 'Farmácia Modelo'}
)
OrganizationERP.objects.get_or_create(organization=farmacia_org, erp=erp_assist, defaults={'enabled': True})
plan_demo, _ = PlanoSaaS.objects.get_or_create(
    slug='demo-homologacao',
    defaults={
        'nome': 'DEMO Homologação',
        'preco': 0,
        'descricao': 'Plano piloto com motor FEFO, PDV e vendas.',
        'erp': erp_assist,
        'ativo': True,
        'limites': {'usuarios': 3, 'filiais': 1}
    }
)
sub_farm, _ = AssinaturaSaaS.objects.get_or_create(
    organization=farmacia_org,
    defaults={'plano': plan_demo, 'status': AssinaturaSaaS.Status.ACTIVE}
)
if sub_farm.status != AssinaturaSaaS.Status.ACTIVE:
    sub_farm.status = AssinaturaSaaS.Status.ACTIVE
    sub_farm.save()

user_farm, _ = Usuario.objects.get_or_create(username='farmaceutico', defaults={'perfil': 'ADMIN', 'email': 'farmacia@modelo.com.br'})
user_farm.set_password('Vertyx#Far2026!X')
user_farm.is_staff = True
user_farm.save()
member_farm, _ = OrganizationMembership.objects.get_or_create(
    organization=farmacia_org, user=user_farm,
    defaults={'role': 'ADMIN', 'status': 'ATIVO'}
)
MembershipERP.objects.get_or_create(membership=member_farm, erp=erp_assist, defaults={'enabled': True})

# 3. Org Prefeitura Ensaio
pref_org, _ = Organization.objects.get_or_create(
    slug='prefeitura-ensaio',
    defaults={'razao_social': 'Prefeitura Municipal Modelo', 'nome_fantasia': 'Prefeitura Ensaio'}
)
OrganizationERP.objects.get_or_create(organization=pref_org, erp=erp_gestao, defaults={'enabled': True})
plan_prof = PlanoSaaS.objects.filter(slug='profissional').first()
if not plan_prof:
    plan_prof = PlanoSaaS.objects.create(slug='profissional', nome='Profissional', preco=249, ativo=True)
sub_pref, _ = AssinaturaSaaS.objects.get_or_create(
    organization=pref_org,
    defaults={'plano': plan_prof, 'status': AssinaturaSaaS.Status.ACTIVE}
)
if sub_pref.status != AssinaturaSaaS.Status.ACTIVE:
    sub_pref.status = AssinaturaSaaS.Status.ACTIVE
    sub_pref.save()

user_pref, _ = Usuario.objects.get_or_create(username='gestorprefeitura', defaults={'perfil': 'ADMIN', 'email': 'gestor@prefeitura.gov.br'})
user_pref.set_password('Vertyx#Pub2026!X')
user_pref.is_staff = True
user_pref.save()
member_pref, _ = OrganizationMembership.objects.get_or_create(
    organization=pref_org, user=user_pref,
    defaults={'role': 'ADMIN', 'status': 'ATIVO'}
)
MembershipERP.objects.get_or_create(membership=member_pref, erp=erp_gestao, defaults={'enabled': True})

# 4. Org TECNOLMED
tec_org, _ = Organization.objects.get_or_create(
    slug='tecnolmed',
    defaults={'razao_social': 'TecnolMed Engenharia Clínica', 'nome_fantasia': 'TECNOLMED'}
)
plan_emp = PlanoSaaS.objects.filter(slug='empresarial').first()
if not plan_emp:
    plan_emp = PlanoSaaS.objects.create(slug='empresarial', nome='Empresarial', preco=399, ativo=True)
sub_tec, _ = AssinaturaSaaS.objects.get_or_create(
    organization=tec_org,
    defaults={'plano': plan_emp, 'status': AssinaturaSaaS.Status.ACTIVE}
)
if sub_tec.status != AssinaturaSaaS.Status.ACTIVE:
    sub_tec.status = AssinaturaSaaS.Status.ACTIVE
    sub_tec.save()

# 5. Org VERTYX Full 360 (All 22 Modules)
org_full, _ = Organization.objects.get_or_create(
    slug='vertyx-full',
    defaults={'razao_social': 'VERTYX Tecnologia e Gestão 360 Ltda', 'nome_fantasia': 'VERTYX Full 360'}
)
OrganizationERP.objects.get_or_create(organization=org_full, erp=erp_assist, defaults={'enabled': True})
all_modules = list(ERPProductModule.objects.filter(erp=erp_assist))
from platform_core.saas_models import MODULES
valid_codes = [m.code for m in all_modules if m.code in MODULES]
plan_full, _ = PlanoSaaS.objects.get_or_create(
    slug='plano-enterprise-full',
    defaults={
        'nome': 'Plano Enterprise Full 360',
        'preco': 999,
        'descricao': 'Plano integral corporativo com todos os módulos ativados.',
        'erp': erp_assist,
        'ativo': True,
        'modulos': valid_codes,
        'limites': {'usuarios': 50, 'filiais': 10, 'vendas_mes': 50000, 'ordens_mes': 5000}
    }
)
for m in all_modules:
    PlanoProdutoModulo.objects.get_or_create(plano=plan_full, modulo=m, defaults={'enabled': True})

sub_full, _ = AssinaturaSaaS.objects.get_or_create(
    organization=org_full,
    defaults={'plano': plan_full, 'status': AssinaturaSaaS.Status.ACTIVE}
)
if sub_full.status != AssinaturaSaaS.Status.ACTIVE:
    sub_full.status = AssinaturaSaaS.Status.ACTIVE
    sub_full.save()

user_full, _ = Usuario.objects.get_or_create(username='auditor_full', defaults={'perfil': 'ADMIN', 'email': 'auditor@vertyx.com.br'})
user_full.set_password('Vertyx#Full2026!X')
user_full.is_staff = True
user_full.save()
member_full, _ = OrganizationMembership.objects.get_or_create(
    organization=org_full, user=user_full,
    defaults={'role': 'ADMIN', 'status': 'ATIVO'}
)
MembershipERP.objects.get_or_create(membership=member_full, erp=erp_assist, defaults={'enabled': True})

print("All 4 organizations, subscriptions, and users seeded successfully!")
