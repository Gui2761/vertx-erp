from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from contas.models import Usuario
from .access import erp_code_for_path
from .context import tenant_context
from .models import (
    ERPCatalog, ERPProductModule, MembershipERP, Organization,
    OrganizationERP, OrganizationMembership,
)
from .modules import analytics_level, product_module_enabled
from .saas_models import (
    AdministradorPlataforma, ContratoSaaS, ItemContratoSaaS,
    PlanoProdutoModulo, PlanoSaaS,
)


class ExplicitProductRouteTests(SimpleTestCase):
    def test_known_routes_have_explicit_product_and_unknown_route_has_none(self):
        self.assertEqual(erp_code_for_path('/gestao-publica/estrutura/'), 'gestao-publica')
        self.assertEqual(erp_code_for_path('/clientes/'), 'assistencia')
        self.assertEqual(erp_code_for_path('/pdv/'), 'assistencia')
        self.assertIsNone(erp_code_for_path('/novo-erp-sem-registro/'))


class MultiErpFoundationTests(TestCase):
    def setUp(self):
        self.assistance = ERPCatalog.objects.get(code='assistencia')
        self.public = ERPCatalog.objects.get(code='gestao-publica')
        self.commerce = ERPCatalog.objects.get(code='comercio-pdv')
        self.organization = Organization.objects.create(slug='multierp-a', razao_social='Multierp A')
        self.other_organization = Organization.objects.create(slug='multierp-b', razao_social='Multierp B')
        self.user = Usuario.objects.create_user('multierp-admin', password='A-Strong-Test-Password-42!')
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, role='ADMIN',
        )
        OrganizationERP.objects.create(organization=self.organization, erp=self.assistance)
        MembershipERP.objects.create(membership=self.membership, erp=self.assistance)
        self.client.force_login(self.user)
        session = self.client.session
        session['organization_id'] = self.organization.pk
        session.save()

    def test_catalog_lists_eight_canonical_products_without_granting_tenants(self):
        codes = set(ERPCatalog.objects.filter(code__in=[
            'erp-empresarial', 'gestao-publica', 'assistencia', 'comercio-pdv',
            'construcao-civil', 'gestao-juridica', 'clinicas-saude', 'distribuidoras',
        ]).values_list('code', flat=True))
        self.assertEqual(len(codes), 8)
        self.assertFalse(OrganizationERP.objects.filter(
            organization=self.organization, erp=self.commerce,
        ).exists())
        self.assertTrue(ERPProductModule.objects.filter(erp=self.public, code='gestao_publica').exists())
        self.assertTrue(ERPProductModule.objects.filter(erp=self.assistance, code='assistencia').exists())

    def test_unknown_protected_route_is_denied_instead_of_falling_back_to_assistance(self):
        self.assertEqual(self.client.get('/novo-erp-sem-registro/').status_code, 403)

    def test_organization_product_without_membership_product_grant_is_denied(self):
        OrganizationERP.objects.create(organization=self.organization, erp=self.public)
        response = self.client.get('/gestao-publica/estrutura/')
        self.assertEqual(response.status_code, 403)

    def test_product_module_requires_same_organization_and_active_grants(self):
        with tenant_context(self.organization):
            self.assertTrue(product_module_enabled(self.user, 'assistencia', 'clientes'))
            self.assertFalse(product_module_enabled(self.user, 'gestao-publica', 'gestao_publica'))
        other_user = Usuario.objects.create_user('multierp-other', password='A-Strong-Test-Password-43!')
        other_membership = OrganizationMembership.objects.create(
            organization=self.other_organization, user=other_user, role='ADMIN',
        )
        OrganizationERP.objects.create(organization=self.other_organization, erp=self.assistance)
        MembershipERP.objects.create(membership=other_membership, erp=self.assistance)
        with tenant_context(self.other_organization):
            self.assertFalse(product_module_enabled(self.user, 'assistencia', 'clientes'))

    def test_membership_with_multiple_products_is_sent_to_product_selector(self):
        OrganizationERP.objects.create(organization=self.organization, erp=self.public)
        MembershipERP.objects.create(membership=self.membership, erp=self.public)
        response = self.client.post(reverse('contas:login'), {
            'username': self.user.username,
            'password': 'A-Strong-Test-Password-42!',
        })
        self.assertRedirects(response, '/vertyx/', fetch_redirect_response=False)

    def test_product_plan_module_must_belong_to_selected_erp(self):
        plan = PlanoSaaS.objects.create(
            slug='multi-erp-plan', nome='Plano de comércio', erp=self.commerce,
            modulos=['pdv'], limites={},
        )
        assistance_module = ERPProductModule.objects.get(erp=self.assistance, code='assistencia')
        assignment = PlanoProdutoModulo(plano=plan, modulo=assistance_module)
        with self.assertRaises(ValidationError):
            assignment.full_clean()

    def test_contract_line_cannot_mix_product_and_plan(self):
        plan = PlanoSaaS.objects.create(
            slug='multi-erp-contract-plan', nome='Plano de comércio', erp=self.commerce,
            modulos=['pdv'], limites={},
        )
        contract = ContratoSaaS.objects.create(organization=self.organization)
        line = ItemContratoSaaS(
            contrato=contract, erp=self.assistance, plano=plan,
            modulos_snapshot=[], limites_snapshot={}, periodicidade_snapshot='MENSAL',
        )
        with self.assertRaises(ValidationError):
            line.full_clean()

    def test_saas_catalog_routes_are_platform_only(self):
        for url in [reverse('platform_core:saas_catalog'), reverse('platform_core:saas_contracts')]:
            self.assertEqual(self.client.get(url).status_code, 403)
        platform_user = Usuario.objects.create_user('multierp-platform')
        AdministradorPlataforma.objects.create(user=platform_user, created_by=platform_user)
        self.client.force_login(platform_user)
        self.assertEqual(self.client.get(reverse('platform_core:saas_catalog')).status_code, 200)
        self.assertContains(self.client.get(reverse('platform_core:saas_catalog')), 'VERTYX Construção Civil')
        self.assertEqual(self.client.get(reverse('platform_core:saas_contracts')).status_code, 200)

    def test_contract_draft_snapshots_product_without_granting_access(self):
        module = ERPProductModule.objects.get(erp=self.commerce, code='pdv')
        plan = PlanoSaaS.objects.create(
            slug='commerce-draft', nome='Comércio homologação', erp=self.commerce,
            modulos=['pdv'], limites={'usuarios': 4}, preco='120.00',
        )
        PlanoProdutoModulo.objects.create(plano=plan, modulo=module)
        platform_user = Usuario.objects.create_user('multierp-platform-contract')
        AdministradorPlataforma.objects.create(user=platform_user, created_by=platform_user)
        self.client.force_login(platform_user)
        response = self.client.post(reverse('platform_core:saas_contracts'), {
            'organization': str(self.organization.pk),
            'inicio_em': '',
            'itens': [f'{self.commerce.pk}:{plan.pk}'],
        })
        self.assertRedirects(response, reverse('platform_core:saas_contracts'), fetch_redirect_response=False)
        contract = ContratoSaaS.objects.get(organization=self.organization)
        line = contract.itens.get()
        self.assertEqual(contract.status, ContratoSaaS.Status.RASCUNHO)
        self.assertEqual(line.modulos_snapshot, ['pdv'])
        self.assertEqual(line.preco_snapshot, plan.preco)
        self.assertEqual(line.nivel_indicadores_snapshot, plan.nivel_indicadores)
        self.assertFalse(OrganizationERP.objects.filter(organization=self.organization, erp=self.commerce).exists())
        self.assertFalse(MembershipERP.objects.filter(membership=self.membership, erp=self.commerce).exists())

    def test_active_contract_snapshots_indicator_level_per_erp_and_fails_closed_on_conflicts(self):
        commerce_module = ERPProductModule.objects.get(erp=self.commerce, code='pdv')
        public_module = ERPProductModule.objects.get(erp=self.public, code='gestao_publica')
        commerce_plan = PlanoSaaS.objects.create(
            slug='commerce-indicator-snapshot', nome='Comércio avançado', erp=self.commerce,
            modulos=['pdv'], limites={}, nivel_indicadores='AVANCADO',
        )
        public_plan = PlanoSaaS.objects.create(
            slug='public-indicator-snapshot', nome='Público completo', erp=self.public,
            modulos=['gestao_publica'], limites={}, nivel_indicadores='COMPLETO',
        )
        PlanoProdutoModulo.objects.get_or_create(plano=commerce_plan, modulo=commerce_module)
        PlanoProdutoModulo.objects.get_or_create(plano=public_plan, modulo=public_module)
        contract = ContratoSaaS.objects.create(organization=self.organization, status=ContratoSaaS.Status.ATIVO)
        commerce_line = ItemContratoSaaS.objects.create(
            contrato=contract, erp=self.commerce, plano=commerce_plan,
            modulos_snapshot=['pdv'], limites_snapshot={}, periodicidade_snapshot='MENSAL',
            nivel_indicadores_snapshot='AVANCADO',
        )
        ItemContratoSaaS.objects.create(
            contrato=contract, erp=self.public, plano=public_plan,
            modulos_snapshot=['gestao_publica'], limites_snapshot={}, periodicidade_snapshot='MENSAL',
            nivel_indicadores_snapshot='COMPLETO',
        )
        commerce_plan.nivel_indicadores = 'BASICO'
        commerce_plan.save()
        self.assertEqual(analytics_level(self.organization, erp_code='comercio-pdv'), 'AVANCADO')
        self.assertEqual(analytics_level(self.organization, erp_code='gestao-publica'), 'COMPLETO')
        self.assertEqual(commerce_line.nivel_indicadores_snapshot, 'AVANCADO')
        commerce_line.nivel_indicadores_snapshot = 'COMPLETO'
        with self.assertRaisesMessage(ValidationError, 'Snapshots comerciais do item são imutáveis'):
            commerce_line.save(update_fields=['nivel_indicadores_snapshot'])

        duplicate = ContratoSaaS.objects.create(organization=self.organization, status=ContratoSaaS.Status.ATIVO)
        ItemContratoSaaS.objects.create(
            contrato=duplicate, erp=self.commerce, plano=commerce_plan,
            modulos_snapshot=['pdv'], limites_snapshot={}, periodicidade_snapshot='MENSAL',
            nivel_indicadores_snapshot='COMPLETO',
        )
        self.assertEqual(analytics_level(self.organization, erp_code='comercio-pdv'), 'BASICO')

    def test_contract_activation_and_suspension_change_product_only_not_membership_grants(self):
        module = ERPProductModule.objects.get(erp=self.commerce, code='pdv')
        plan = PlanoSaaS.objects.create(
            slug='commerce-activation-test', nome='Comércio homologação', erp=self.commerce,
            modulos=['pdv'], limites={'usuarios': 10},
        )
        PlanoProdutoModulo.objects.get_or_create(plano=plan, modulo=module)
        platform_user = Usuario.objects.create_user('multierp-platform-activation')
        AdministradorPlataforma.objects.create(user=platform_user, created_by=platform_user)
        contract = ContratoSaaS.objects.create(organization=self.organization)
        ItemContratoSaaS.objects.create(
            contrato=contract, erp=self.commerce, plano=plan,
            modulos_snapshot=['pdv'], limites_snapshot={'usuarios': 10},
            periodicidade_snapshot='MENSAL',
        )

        action_url = reverse('platform_core:saas_contract_status', kwargs={'pk': contract.pk, 'action': 'ativar'})
        self.assertEqual(self.client.post(action_url, {'confirmar': 'sim'}).status_code, 403)
        self.client.force_login(platform_user)
        contract_page = self.client.get(reverse('platform_core:saas_contracts'))
        self.assertEqual(contract_page.status_code, 200)
        self.assertContains(contract_page, 'Limites:')
        self.assertContains(contract_page, 'Ativar contrato')
        self.assertEqual(self.client.post(action_url, {'confirmar': 'sim'}).status_code, 302)
        activated = ContratoSaaS.objects.get(pk=contract.pk)
        self.assertEqual(activated.status, ContratoSaaS.Status.ATIVO)
        self.assertTrue(OrganizationERP.objects.get(organization=self.organization, erp=self.commerce).enabled)
        self.assertFalse(MembershipERP.objects.filter(membership=self.membership, erp=self.commerce).exists())
        self.assertFalse(product_module_enabled(self.user, 'comercio-pdv', 'pdv', self.organization))

        member_product = MembershipERP.objects.create(membership=self.membership, erp=self.commerce)
        self.assertTrue(product_module_enabled(self.user, 'comercio-pdv', 'pdv', self.organization))
        suspend_url = reverse('platform_core:saas_contract_status', kwargs={'pk': contract.pk, 'action': 'suspender'})
        self.assertEqual(self.client.post(suspend_url, {'confirmar': 'sim'}).status_code, 302)
        suspended = ContratoSaaS.objects.get(pk=contract.pk)
        self.assertEqual(suspended.status, ContratoSaaS.Status.SUSPENSO)
        self.assertFalse(OrganizationERP.objects.get(organization=self.organization, erp=self.commerce).enabled)
        self.assertTrue(MembershipERP.objects.filter(pk=member_product.pk, enabled=True).exists())
        self.assertFalse(product_module_enabled(self.user, 'comercio-pdv', 'pdv', self.organization))

    def test_expired_contract_does_not_continue_granting_modules_or_indicator_tier(self):
        module = ERPProductModule.objects.get(erp=self.commerce, code='pdv')
        plan = PlanoSaaS.objects.create(
            slug='commerce-expired-test', nome='Comércio vencido', erp=self.commerce,
            modulos=['pdv'], limites={}, nivel_indicadores='COMPLETO',
        )
        PlanoProdutoModulo.objects.get_or_create(plano=plan, modulo=module)
        OrganizationERP.objects.create(organization=self.organization, erp=self.commerce)
        MembershipERP.objects.create(membership=self.membership, erp=self.commerce)
        contract = ContratoSaaS.objects.create(
            organization=self.organization, status=ContratoSaaS.Status.ATIVO,
            inicio_em=timezone.localdate() - timedelta(days=20),
            fim_em=timezone.localdate() - timedelta(days=1),
        )
        ItemContratoSaaS.objects.create(
            contrato=contract, erp=self.commerce, plano=plan,
            modulos_snapshot=['pdv'], limites_snapshot={},
            nivel_indicadores_snapshot='COMPLETO', periodicidade_snapshot='MENSAL',
        )
        self.assertFalse(product_module_enabled(self.user, 'comercio-pdv', 'pdv', self.organization))
        self.assertEqual(analytics_level(self.organization, erp_code='comercio-pdv'), 'BASICO')

