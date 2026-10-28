from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve

from commercial.models import PlanoComercial
from .context import tenant_context
from .models import (ERPCatalog, MembershipERP, ModuloOrganizacao, Organization,
                     OrganizationERP, OrganizationMembership, PermissaoMembership,
                     FilialEmpresa)
from .modules import has_capability, module_enabled, required_modules_for_path
from .saas_models import AssinaturaSaaS, PlanoSaaS
from .saas_services import aplicar_modulos


class ApprovedCommercialEntitlementTests(TestCase):
    def test_standard_plans_match_approved_products_and_limits_without_touching_prices(self):
        expected = {
            'basico': ({'clientes', 'produtos', 'assistencia', 'estoque_basico', 'financeiro_basico',
                        'documentos_basicos', 'relatorios_basicos', 'pdv', 'fiscal'}, 3, 1, '149.00'),
            'profissional': ({'clientes', 'produtos', 'assistencia', 'estoque_completo', 'compras',
                              'estoque_basico', 'financeiro_basico', 'financeiro_completo', 'pdv', 'fiscal', 'contratos', 'portal',
                              'pwa_tecnico', 'rh_asst_basico', 'documentos_completos',
                              'relatorios_basicos', 'relatorios_completos'}, 10, 3, '249.00'),
            'empresarial': ({'clientes', 'produtos', 'assistencia', 'estoque_completo', 'compras',
                             'estoque_basico', 'financeiro_basico', 'financeiro_completo', 'pdv', 'fiscal', 'contratos', 'portal',
                             'pwa_tecnico', 'rh_asst_completo', 'documentos_completos',
                             'relatorios_basicos', 'relatorios_completos', 'pwa_vendedor'}, 30, 10, '399.00'),
        }
        for slug, (modules, users, branches, price) in expected.items():
            with self.subTest(plan=slug):
                plan = PlanoSaaS.objects.get(slug=slug, publico_ativo=True, ativo=True)
                self.assertEqual(set(plan.modulos), modules)
                self.assertEqual(plan.limites, {
                    'usuarios': users, 'filiais': branches, 'vendas_mes': None,
                    'ordens_mes': None, 'armazenamento_mb': None,
                })
                self.assertEqual(str(plan.preco), price)
                self.assertEqual(str(PlanoComercial.objects.get(slug=slug).preco), price)
                self.assertEqual(plan.nivel_indicadores, {
                    'basico': 'BASICO', 'profissional': 'AVANCADO', 'empresarial': 'COMPLETO'
                }[slug])
        self.assertFalse(PlanoSaaS.objects.filter(plano_comercial__slug='personalizado', publico_ativo=True).exists())
        self.assertFalse(any('gestao_publica' in plan.modulos or 'rh_municipal' in plan.modulos
                             for plan in PlanoSaaS.objects.filter(slug__in=expected)))

    def test_entitlement_distinguishes_basic_complete_pwa_and_rh_tiers(self):
        org = Organization.objects.create(slug='entitlements-local', razao_social='Entitlements Local')
        plan = PlanoSaaS.objects.get(slug='basico')
        AssinaturaSaaS.objects.create(organization=org, plano=plan)
        aplicar_modulos(org, plan)
        with tenant_context(org):
            self.assertTrue(module_enabled('assistencia'))
            self.assertTrue(module_enabled('estoque_basico'))
            self.assertTrue(module_enabled('pdv'))
            self.assertTrue(module_enabled('fiscal'))
            self.assertTrue(module_enabled('financeiro_basico'))
            self.assertTrue(module_enabled('relatorios_basicos'))
            self.assertFalse(module_enabled('estoque_completo'))
            self.assertFalse(module_enabled('financeiro_completo'))
            self.assertFalse(module_enabled('pwa_tecnico'))
            self.assertFalse(module_enabled('pwa_vendedor'))
            self.assertFalse(module_enabled('rh_asst_basico'))
        self.assertEqual(required_modules_for_path('/tecnico/', resolve('/tecnico/')),
                         ('assistencia', 'pwa_tecnico'))
        self.assertEqual(required_modules_for_path('/clientes/', resolve('/clientes/')),
                         ('clientes',))
        self.assertEqual(required_modules_for_path('/estoque/', resolve('/estoque/')),
                         ('produtos', 'estoque_basico'))
        self.assertEqual(required_modules_for_path('/vendedor/', resolve('/vendedor/')),
                         ('pwa_vendedor',))
        self.assertIn('estoque_completo', required_modules_for_path('/estoque/lotes/', resolve('/estoque/lotes/')))

    def test_analytics_access_is_included_and_tiered_per_tenant(self):
        from .modules import analytics_level, analytics_at_least
        basic = Organization.objects.create(slug='analytics-basic', razao_social='Analytics Basic')
        professional = Organization.objects.create(slug='analytics-pro', razao_social='Analytics Pro')
        enterprise = Organization.objects.create(slug='analytics-enterprise', razao_social='Analytics Enterprise')
        for organization, slug in ((basic, 'basico'), (professional, 'profissional'), (enterprise, 'empresarial')):
            plan = PlanoSaaS.objects.get(slug=slug)
            AssinaturaSaaS.objects.create(organization=organization, plano=plan)
            aplicar_modulos(organization, plan)
        self.assertEqual(analytics_level(basic), 'BASICO')
        self.assertEqual(analytics_level(professional), 'AVANCADO')
        self.assertEqual(analytics_level(enterprise), 'COMPLETO')
        for organization in (basic, professional, enterprise):
            with tenant_context(organization):
                self.assertTrue(module_enabled('relatorios_basicos'))
        with tenant_context(basic):
            self.assertFalse(module_enabled('relatorios_completos'))
            self.assertFalse(analytics_at_least('AVANCADO'))
        with tenant_context(professional):
            self.assertTrue(module_enabled('relatorios_completos'))
            self.assertTrue(analytics_at_least('AVANCADO'))
            self.assertFalse(analytics_at_least('COMPLETO'))
        with tenant_context(enterprise):
            self.assertTrue(analytics_at_least('COMPLETO'))
        self.assertEqual(required_modules_for_path('/gestao/executiva/', resolve('/gestao/executiva/')),
                         ('relatorios_completos',))

    def test_basic_plan_blocks_direct_urls_even_for_tenant_admin(self):
        org = Organization.objects.create(slug='basic-url-local', razao_social='Basic URL Local')
        plan = PlanoSaaS.objects.get(slug='basico')
        AssinaturaSaaS.objects.create(organization=org, plano=plan)
        aplicar_modulos(org, plan)
        erp = ERPCatalog.objects.get(code='assistencia')
        OrganizationERP.objects.create(organization=org, erp=erp, enabled=True)
        user = get_user_model().objects.create_user(username='basic-url-admin', password='unused')
        membership = OrganizationMembership.objects.create(organization=org, user=user, role='ADMIN')
        MembershipERP.objects.create(membership=membership, erp=erp, enabled=True)
        self.client.force_login(user)
        for path in ('/compras/', '/portal/', '/tecnico/', '/bancos/caixa/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.get('/clientes/').status_code, 200)
        self.assertEqual(self.client.get('/estoque/').status_code, 200)
        self.assertEqual(self.client.get('/pdv/').status_code, 200)
        self.assertEqual(self.client.get('/fiscal/').status_code, 200)
        dashboard = self.client.get('/assistencia/')
        self.assertEqual(dashboard.status_code, 200)
        self.assertTrue(dashboard.context['executive'])
        self.assertIn('sales_chart', dashboard.context)
        self.assertIn('stock_chart', dashboard.context)
        self.assertContains(dashboard, 'Vendas líquidas')
        self.assertContains(dashboard, 'Estoque disponível por produto')
        self.assertContains(dashboard, 'Fluxo financeiro realizado')
        self.assertEqual(self.client.get('/gestao/executiva/').status_code, 403)

    def test_membership_permission_cannot_grant_a_module_absent_from_the_plan(self):
        org = Organization.objects.create(slug='permission-local', razao_social='Permission Local')
        plan = PlanoSaaS.objects.get(slug='basico')
        AssinaturaSaaS.objects.create(organization=org, plano=plan)
        aplicar_modulos(org, plan)
        erp = ERPCatalog.objects.get(code='assistencia')
        OrganizationERP.objects.create(organization=org, erp=erp, enabled=True)
        user = get_user_model().objects.create_user(username='plan-entitlement-admin', password='unused')
        membership = OrganizationMembership.objects.create(organization=org, user=user, role='ADMIN')
        MembershipERP.objects.create(membership=membership, erp=erp, enabled=True)
        with tenant_context(org):
            PermissaoMembership.objects.create(organization=org, membership=membership,
                                               capacidade='compras', permitido=True)
        with tenant_context(org):
            self.assertFalse(has_capability(user, 'compras'))
            self.assertFalse(module_enabled('compras'))

    def test_core_modules_ignore_stale_tenant_disabled_rows_but_keep_advanced_modules_gated(self):
        org = Organization.objects.create(slug='core-modules-local', razao_social='Core Modules Local')
        plan = PlanoSaaS.objects.get(slug='basico')
        AssinaturaSaaS.objects.create(organization=org, plano=plan)
        aplicar_modulos(org, plan)
        with tenant_context(org):
            for code in ('clientes', 'produtos', 'pdv', 'fiscal', 'assistencia', 'estoque_basico', 'financeiro_basico', 'relatorios_basicos'):
                row = ModuloOrganizacao.objects.get(organization=org, codigo=code)
                row.habilitado = False
                row.save(update_fields=['habilitado'])
            self.assertTrue(all(module_enabled(code) for code in (
                'clientes', 'produtos', 'pdv', 'fiscal', 'assistencia', 'estoque_basico',
                'financeiro_basico', 'relatorios_basicos'
            )))
            self.assertFalse(module_enabled('compras'))

    def test_branch_creation_route_enforces_plan_quota(self):
        org = Organization.objects.create(slug='branch-quota-local', razao_social='Branch Quota Local')
        plan = PlanoSaaS.objects.get(slug='basico')
        AssinaturaSaaS.objects.create(organization=org, plano=plan)
        aplicar_modulos(org, plan)
        erp = ERPCatalog.objects.get(code='assistencia')
        OrganizationERP.objects.create(organization=org, erp=erp, enabled=True)
        user = get_user_model().objects.create_user(username='branch-quota-admin', password='unused')
        membership = OrganizationMembership.objects.create(organization=org, user=user, role='ADMIN')
        MembershipERP.objects.create(membership=membership, erp=erp, enabled=True)
        with tenant_context(org):
            FilialEmpresa.objects.create(codigo='MATRIZ', nome='Matriz')
        self.client.force_login(user)
        response = self.client.post('/vertyx/empresa/filiais/nova/', {
            'codigo': 'FILIAL-2', 'nome': 'Filial excedente', 'cnpj': '', 'endereco': '',
            'inscricao_estadual': '', 'inscricao_municipal': '', 'ativo': 'on',
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Limite de filiais do plano atingido.', status_code=400)
        with tenant_context(org):
            self.assertEqual(FilialEmpresa.objects.filter(organization=org, ativo=True).count(), 1)
