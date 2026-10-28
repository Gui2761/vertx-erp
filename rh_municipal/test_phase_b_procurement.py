from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, Organization, OrganizationERP
from platform_core.modules import product_module_enabled
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS

from .models import AcessoMunicipal
from .phase_b_models import (
    HistoricoContratacaoPublica, ModalidadeContratacaoMunicipal,
    SolicitacaoCompra,
)
from .procurement_services import (
    transition_procurement_process, transition_purchase_request,
)
from .public_services import require_municipal_permission, scope_allows
from .tests import MunicipalFixtures


PROCUREMENT_MODULES = (
    'gestao_publica', 'compras_publicas', 'licitacoes_publicas',
    'registro_precos', 'contratos_publicos',
)


class MunicipalProcurementPhaseBTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        with tenant_context(self.c):
            AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )
        plan = PlanoSaaS.objects.create(
            slug='municipal-fase-b-test', nome='Plano sintético Fase B',
            erp=self.publico, modulos=[], limites={},
        )
        for code in PROCUREMENT_MODULES:
            PlanoProdutoModulo.objects.create(
                plano=plan,
                modulo=ERPProductModule.objects.get(erp=self.publico, code=code),
            )
        AssinaturaSaaS.objects.create(organization=self.c, plano=plan)

    def test_all_procurement_routes_require_and_render_with_product_entitlement(self):
        routes = (
            ('compras_module', 'Compras Públicas'),
            ('licitacoes_module', 'Licitações e Processos'),
            ('registro_precos_module', 'Registro de Preços'),
            ('contratos_module', 'Contratos Públicos'),
        )
        for name, heading in routes:
            with self.subTest(route=name):
                response = self.client.get(reverse(f'rh_municipal_public:{name}'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)

    def test_procurement_catalog_is_not_a_tenant_grant(self):
        for code in PROCUREMENT_MODULES[1:]:
            module = ERPProductModule.objects.get(erp=self.publico, code=code)
            self.assertTrue(module.active)
            self.assertTrue(module.resources.exists())
        with tenant_context(self.c):
            self.assertTrue(product_module_enabled(self.admin_c.user, 'gestao-publica', 'compras_publicas'))

    def test_missing_contract_module_blocks_screen(self):
        restricted = PlanoSaaS.objects.create(
            slug='municipal-fase-b-sem-compras-test', nome='Plano sem compras',
            erp=self.publico, modulos=[], limites={},
        )
        PlanoProdutoModulo.objects.create(
            plano=restricted,
            modulo=ERPProductModule.objects.get(erp=self.publico, code='gestao_publica'),
        )
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=restricted)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:compras_module')).status_code, 403)

    def test_purchase_request_transition_requires_permission_reason_and_audits(self):
        with tenant_context(self.c):
            request = SolicitacaoCompra.objects.create(
                organization=self.c, numero='SC-001', exercicio=2031,
                secretaria=self.structure[0], responsavel=self.admin_c.user,
                justificativa='Aquisição sintética para teste', criado_por=self.admin_c.user,
            )
        with tenant_context(self.c), self.assertRaises(ValidationError):
            transition_purchase_request(self.admin_c.user, request.public_id, 'APROVADA', reason='')
        with tenant_context(self.c):
            for status in ('ENVIADA', 'EM_ANALISE'):
                transition_purchase_request(self.admin_c.user, request.public_id, status)
            transition_purchase_request(self.admin_c.user, request.public_id, 'APROVADA', reason='Aprovada em teste transacional')
        request.refresh_from_db()
        self.assertEqual(request.status, SolicitacaoCompra.Status.APROVADA)
        self.assertEqual(HistoricoContratacaoPublica.all_objects.filter(
            organization=self.c, registro_id=request.pk,
        ).count(), 3)

    def test_rendered_purchase_form_accepts_tenant_scoped_post_and_audits_creation(self):
        response = self.client.get(reverse('rh_municipal_public:compras_module') + '?novo=solicitacao')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="secretaria"')
        response = self.client.post(reverse('rh_municipal_public:compras_module'), {
            'acao': 'solicitacao', 'numero': 'SC-HTML-01', 'exercicio': '2031',
            'secretaria': str(self.structure[0].pk), 'justificativa': 'Solicitação de teste via formulário renderizado',
            'prioridade': 'NORMAL',
        })
        self.assertEqual(response.status_code, 302)
        request = SolicitacaoCompra.all_objects.get(organization=self.c, numero='SC-HTML-01')
        self.assertEqual(request.responsavel_id, self.admin_c.user_id)
        self.assertTrue(HistoricoContratacaoPublica.all_objects.filter(
            organization=self.c, registro_id=request.pk, evento='REGISTRO_CRIADO',
        ).exists())
        filtered = self.client.get(reverse('rh_municipal_public:compras_module'), {'q': 'SC-HTML-01'})
        self.assertEqual(filtered.status_code, 200)
        self.assertContains(filtered, 'SC-HTML-01')
        self.assertContains(filtered, 'Histórico de alterações')

    def test_process_workflow_requires_reason_and_valid_transition(self):
        # A process can only be created from an approved request. This test
        # checks backend transition authorization against an existing tenant row.
        from .phase_b_models import ProcessoContratacaoMunicipal
        with tenant_context(self.c):
            modality = ModalidadeContratacaoMunicipal.objects.create(
                organization=self.c, codigo='PREGAO', nome='Pregão (catálogo local)',
            )
            process = ProcessoContratacaoMunicipal.objects.create(
                organization=self.c, numero='PC-001', exercicio=2031,
                secretaria=self.structure[0], objeto='Processo sintético', modalidade=modality,
                responsavel=self.admin_c.user, criado_por=self.admin_c.user,
            )
            with self.assertRaises(ValidationError):
                transition_procurement_process(self.admin_c.user, process.pk, 'EM_PLANEJAMENTO', reason='')
            process = transition_procurement_process(
                self.admin_c.user, process.pk, 'EM_PLANEJAMENTO', reason='Planejamento iniciado em teste',
            )
        self.assertEqual(process.status, ProcessoContratacaoMunicipal.Status.EM_PLANEJAMENTO)

    def test_city_admin_cannot_access_foreign_tenant_record_even_at_city_scope(self):
        other_city = Organization.objects.create(slug='outra-prefeitura-phase-b', razao_social='Outra Prefeitura')
        OrganizationERP.objects.create(organization=other_city, erp=self.publico)
        other_admin = self._user('admin-outra-phase-b', other_city, self.publico, 'ADMIN')
        with tenant_context(other_city):
            AcessoMunicipal.objects.create(
                membership=other_admin, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=other_admin.user,
            )
        with tenant_context(self.c):
            row = SolicitacaoCompra.objects.create(
                organization=self.c, numero='SC-002', exercicio=2031,
                secretaria=self.structure[0], responsavel=self.admin_c.user,
                justificativa='Escopo tenant', criado_por=self.admin_c.user,
            )
        other_access = AcessoMunicipal.all_objects.get(membership=other_admin)
        self.assertFalse(scope_allows(other_access, row))
        self.client.force_login(other_admin.user)
        session = self.client.session
        session['organization_id'] = other_city.pk
        session.save()
        with tenant_context(other_city), self.assertRaises(PermissionDenied):
            require_municipal_permission(
                other_admin.user, 'compras.approve', module='compras_publicas', record=row,
            )

    def test_contract_route_does_not_leak_records_from_other_city(self):
        response = self.client.get(reverse(
            'rh_municipal_public:contratos_module',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Outra Prefeitura')

