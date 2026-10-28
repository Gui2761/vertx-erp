import uuid

from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS

from .models import AcessoMunicipal, PermissaoMunicipal
from .tests import MunicipalFixtures


class MunicipalPhaseKTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.codes = ('gestao_publica', 'rh_municipal', 'orcamento_publico')
        self.modules = {
            code: ERPProductModule.objects.get_or_create(
                erp=self.publico, code=code,
                defaults={'name': code.replace('_', ' ').title(), 'active': True, 'sort_order': 1},
            )[0]
            for code in self.codes
        }
        self.plan = PlanoSaaS.objects.create(
            slug=f'phase-k-{uuid.uuid4().hex[:10]}', nome='Plano sintético painel executivo',
            erp=self.publico, modulos=[],
        )
        for code in ('gestao_publica', 'rh_municipal'):
            PlanoProdutoModulo.objects.create(plano=self.plan, modulo=self.modules[code])
        AssinaturaSaaS.objects.create(
            organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE,
        )
        with tenant_context(self.c):
            self.admin_access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )

    def test_executive_dashboard_aggregates_only_contracted_tenant_data(self):
        response = self.client.get(reverse('rh_municipal_public:executive_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Servidores ativos')
        self.assertContains(response, '>1<')
        self.assertNotContains(response, 'Dotações orçamentárias ativas')
        self.assertContains(response, 'não calcula execução orçamentária')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_executive_dashboard_requires_municipal_access_and_executive_permission(self):
        stranger = self._user('phase-k-no-access', self.c, self.publico, 'ADMIN')
        self.client.force_login(stranger.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:executive_dashboard')).status_code, 403)

        with tenant_context(self.c):
            access = AcessoMunicipal.objects.create(
                membership=stranger, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(
                acesso=access, capacidade='dashboard.view', permitido=True,
            )
        self.assertEqual(self.client.get(reverse('rh_municipal_public:executive_dashboard')).status_code, 403)

    def test_each_metric_requires_its_own_module_and_permission(self):
        viewer = self._user('phase-k-limited-viewer', self.c, self.publico, 'TECNICO')
        with tenant_context(self.c):
            access = AcessoMunicipal.objects.create(
                membership=viewer, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            for code in ('dashboard.view', 'executive.dashboard.view'):
                PermissaoMunicipal.objects.create(acesso=access, capacidade=code, permitido=True)
        self.client.force_login(viewer.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()

        response = self.client.get(reverse('rh_municipal_public:executive_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Servidores ativos')

        PlanoProdutoModulo.objects.create(plano=self.plan, modulo=self.modules['orcamento_publico'])
        with tenant_context(self.c):
            PermissaoMunicipal.objects.create(
                acesso=access, capacidade='budget.view', permitido=True,
            )
        response = self.client.get(reverse('rh_municipal_public:executive_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dotações orçamentárias ativas')
        self.assertNotContains(response, 'Servidores ativos')
