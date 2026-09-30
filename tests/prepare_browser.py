"""Cria uma OS de demonstração somente no banco isolado de validação."""
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
os.environ['DJANGO_SETTINGS_MODULE'] = 'tecnolmed.test_settings'
import django
django.setup()
from django.test import Client
from clientes.models import Cliente, Unidade
from contas.models import Usuario, Tecnico
from equipamentos.models import CategoriaEquipamento, Equipamento
from ordens.models import OrdemServico
from platform_core.models import Organization, OrganizationMembership, OrganizationERP, MembershipERP, ERPCatalog
from platform_core.context import tenant_context

slug = sys.argv[1] if len(sys.argv) > 1 else 'tecnolmed'
organization, _ = Organization.objects.get_or_create(slug=slug, defaults={'razao_social': '[TESTE] Empresa B', 'nome_fantasia': '[TESTE] Empresa B'})
erp = ERPCatalog.objects.get(code='assistencia')
OrganizationERP.objects.get_or_create(organization=organization, erp=erp)
user, _ = Usuario.objects.get_or_create(username='browser-' + slug, defaults={'perfil': 'TECNICO'})
membership, _ = OrganizationMembership.objects.get_or_create(organization=organization, user=user, defaults={'role': 'TECNICO'})
MembershipERP.objects.get_or_create(membership=membership, erp=erp)
with tenant_context(organization):
    tecnico, _ = Tecnico.objects.get_or_create(usuario=user, defaults={'nome': '[TESTE] Técnico João', 'registro_profissional': 'CRT demonstração'})
    cliente, _ = Cliente.objects.get_or_create(cpf_cnpj='TESTE-BROWSER', defaults={'nome_razao_social': '[TESTE] Hospital Modelo', 'endereco': 'Rua de demonstração', 'numero': '100', 'cidade': 'Maceió', 'uf': 'AL'})
    unidade, _ = Unidade.objects.get_or_create(cliente=cliente, nome='Unidade de demonstração')
    categoria, _ = CategoriaEquipamento.objects.get_or_create(nome='[TESTE] Hospitalar')
    equipamento, _ = Equipamento.objects.get_or_create(cliente=cliente, nome='[TESTE] Monitor multiparâmetro', defaults={'unidade': unidade, 'categoria': categoria, 'codigo_interno': 'PAT-001', 'numero_serie': 'SER-001', 'fabricante': 'Fabricante demonstrativo', 'modelo': 'Modelo demonstrativo'})
    ordem = OrdemServico.objects.create(cliente=cliente, unidade=unidade, equipamento=equipamento, tecnico=tecnico, defeito='Equipamento não liga. Cliente solicita avaliação da alimentação elétrica.')
client = Client()
client.force_login(user)
out = root / 'tmp' / 'validation'
out.mkdir(parents=True, exist_ok=True)
(out / 'browser.json').write_text(json.dumps({'ordem': ordem.pk, 'cookie': client.cookies['sessionid'].value, 'organization': organization.display_name}), encoding='utf-8')
print('Dados isolados preparados para validação no navegador.')
