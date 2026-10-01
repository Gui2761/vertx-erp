"""Dados sintéticos do ensaio dos módulos, exclusivamente no PostgreSQL local."""
import datetime
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
values = json.loads((root / 'tmp/provision/https_test_environment.json').read_text())
assert values['DATABASE_URL'].split('@')[1] == '127.0.0.1:55432/vertyx_homologation'
assert values['S3_ENDPOINT_URL'] == 'https://127.0.0.1:9501'
os.environ.update(values)
os.environ['DJANGO_SETTINGS_MODULE'] = 'tecnolmed.settings'
import django
django.setup()
from django.utils import timezone
from platform_core.models import Organization, OrganizationMembership, OrganizationERP, MembershipERP, ERPCatalog
from platform_core.context import tenant_context
from contas.models import Usuario, Tecnico
from clientes.models import Cliente, Unidade
from equipamentos.models import CategoriaEquipamento, Equipamento

organization, _ = Organization.objects.get_or_create(slug='ensaio-modulos-local', defaults={'razao_social': '[TESTE LOCAL] Módulos'})
erp = ERPCatalog.objects.get(code='assistencia')
OrganizationERP.objects.get_or_create(organization=organization, erp=erp)
user, _ = Usuario.objects.get_or_create(username='ensaio-modulos-local')
user.set_password(values['BROWSER_TEST_PASSWORD'])
user.save()
membership, _ = OrganizationMembership.objects.get_or_create(organization=organization, user=user, defaults={'role': 'ADMIN'})
MembershipERP.objects.get_or_create(membership=membership, erp=erp)
with tenant_context(organization):
    tech, _ = Tecnico.objects.get_or_create(usuario=user, defaults={'nome': '[TESTE LOCAL] Técnico'})
    customer, _ = Cliente.objects.get_or_create(cpf_cnpj='LOCAL-MODULES-TEST', defaults={'nome_razao_social': '[TESTE LOCAL] Hospital'})
    unit, _ = Unidade.objects.get_or_create(cliente=customer, nome='[TESTE LOCAL] Unidade')
    category, _ = CategoriaEquipamento.objects.get_or_create(nome='[TESTE LOCAL] Categoria')
    equipment, _ = Equipamento.objects.get_or_create(cliente=customer, nome='[TESTE LOCAL] Monitor', defaults={'unidade': unit, 'categoria': category})
    today = timezone.localdate()
    data = {'base_url': 'https://127.0.0.1:8765', 'username': user.username, 'password': values['BROWSER_TEST_PASSWORD'], 'organization': organization.display_name, 'cliente': customer.pk, 'unidade': unit.pk, 'equipamento': equipment.pk, 'tecnico': tech.pk, 'today': today.isoformat(), 'validade': (today + datetime.timedelta(days=20)).isoformat(), 'end': (today + datetime.timedelta(days=75)).isoformat()}
output = root / 'tmp/validation'
output.mkdir(parents=True, exist_ok=True)
(output / 'modules-browser.json').write_text(json.dumps(data), encoding='utf-8')
print('Dados sintéticos dos módulos preparados somente na base de ensaio local.')
