from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import (
    ERPProductModule, MembershipERP, Organization, OrganizationERP,
)
from platform_core.modules import product_module_enabled
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS

from . import phase_a_models as civic
from .models import AcessoMunicipal, Secretaria
from .public_services import scoped_queryset
from .tests import MunicipalFixtures


class PublicFoundationIsolationTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        with tenant_context(self.c):
            self.access = AcessoMunicipal.objects.create(
                membership=self.admin_c,
                papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA,
                atribuido_por=self.admin_c.user,
            )

    def test_foundation_modules_are_catalogued_but_not_implicitly_contracted(self):
        for code in (
            'planejamento_publico', 'orcamento_publico',
            'contabilidade_pub', 'tesouraria_publica',
        ):
            module = ERPProductModule.objects.get(erp=self.publico, code=code)
            self.assertTrue(module.active)
            with tenant_context(self.c):
                self.assertFalse(product_module_enabled(self.admin_c.user, 'gestao-publica', code))
        response = self.client.get(reverse('rh_municipal_public:planejamento'))
        self.assertEqual(response.status_code, 403)

    def test_explicit_plan_entitlement_and_municipal_admin_open_module(self):
        codes = ['gestao_publica', 'planejamento_publico']
        plan = PlanoSaaS.objects.create(
            slug='municipal-planejamento-fase-a-test', nome='Plano municipal sintético',
            erp=self.publico, modulos=[], limites={},
        )
        for code in codes:
            PlanoProdutoModulo.objects.create(
                plano=plan, modulo=ERPProductModule.objects.get(erp=self.publico, code=code),
            )
        AssinaturaSaaS.objects.create(organization=self.c, plano=plan)
        with tenant_context(self.c):
            self.assertTrue(product_module_enabled(self.admin_c.user, 'gestao-publica', 'planejamento_publico'))
        response = self.client.get(reverse('rh_municipal_public:planejamento'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Planejamento Público')
        self.assertContains(response, 'PPA, LDO e LOA')
        form_url = reverse('rh_municipal_public:planejamento') + '?novo=exercicio'
        form_response = self.client.get(form_url)
        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, 'name="ano"')
        created = self.client.post(reverse('rh_municipal_public:planejamento'), {
            'acao': 'exercicio', 'ano': '2034', 'descricao': 'Exercício sintético',
            'status': 'PLANEJAMENTO',
        })
        self.assertEqual(created.status_code, 302)
        self.assertTrue(civic.ExercicioMunicipal.all_objects.filter(
            organization=self.c, ano=2034, criado_por=self.admin_c.user,
        ).exists())

    def test_user_without_municipal_permission_cannot_manage_module_by_direct_post(self):
        plan = PlanoSaaS.objects.create(
            slug='municipal-budget-fase-a-test', nome='Plano municipal sintético orçamento',
            erp=self.publico, modulos=[], limites={},
        )
        for code in ('gestao_publica', 'orcamento_publico'):
            PlanoProdutoModulo.objects.create(
                plano=plan, modulo=ERPProductModule.objects.get(erp=self.publico, code=code),
            )
        AssinaturaSaaS.objects.create(organization=self.c, plano=plan)
        user = self._user('gestor-sem-orcamento', self.c, self.publico, 'SERVIDOR_PUBLICO')
        with tenant_context(self.c):
            AcessoMunicipal.objects.create(
                membership=user, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
        self.client.force_login(user.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.post(
            reverse('rh_municipal_public:orcamento'),
            {'acao': 'orgao', 'codigo': 'ORG-POST', 'nome': 'Tentativa direta', 'ativo': 'on'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(civic.OrgaoOrcamentarioMunicipal.all_objects.filter(organization=self.c, codigo='ORG-POST').exists())

    def test_all_phase_a_module_screens_render_with_explicit_entitlements(self):
        codes = (
            'gestao_publica', 'planejamento_publico', 'orcamento_publico',
            'contabilidade_pub', 'tesouraria_publica',
        )
        plan = PlanoSaaS.objects.create(
            slug='municipal-fase-a-all-screens-test', nome='Plano municipal sintético completo',
            erp=self.publico, modulos=[], limites={},
        )
        for code in codes:
            PlanoProdutoModulo.objects.create(
                plano=plan, modulo=ERPProductModule.objects.get(erp=self.publico, code=code),
            )
        AssinaturaSaaS.objects.create(organization=self.c, plano=plan)
        screens = (
            ('planejamento', 'Planejamento Público'),
            ('orcamento', 'Orçamento Público'),
            ('contabilidade', 'Contabilidade Pública'),
            ('tesouraria', 'Tesouraria'),
        )
        for route, title in screens:
            with self.subTest(route=route):
                response = self.client.get(reverse(f'rh_municipal_public:{route}'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)
                self.assertTemplateUsed(response, 'rh_municipal/phase_a_module.html')

    def test_cross_tenant_exercise_reference_is_rejected(self):
        another_city = Organization.objects.create(slug='outra-prefeitura-fase-a', razao_social='Outra Prefeitura')
        OrganizationERP.objects.create(organization=another_city, erp=self.publico)
        city_admin = self._user('admin-outra-prefeitura-fase-a', another_city, self.publico, 'ADMIN')
        with tenant_context(self.c):
            exercise_a = civic.ExercicioMunicipal.objects.create(
                organization=self.c, ano=2031, criado_por=self.admin_c.user,
            )
        with tenant_context(another_city):
            exercise_b = civic.ExercicioMunicipal.objects.create(
                organization=another_city, ano=2031, criado_por=city_admin.user,
            )
        program = civic.ProgramaPlanejamentoMunicipal(
            organization=self.c, exercicio=exercise_b, codigo='PRG-X', nome='Programa cruzado',
            criado_por=self.admin_c.user,
        )
        with tenant_context(self.c), self.assertRaises(ValidationError):
            program.full_clean()
        self.assertTrue(civic.ExercicioMunicipal.all_objects.filter(pk=exercise_a.pk, organization=self.c).exists())

    def test_programme_scope_filters_rows_by_secretariat(self):
        with tenant_context(self.c):
            exercise = civic.ExercicioMunicipal.objects.create(
                organization=self.c, ano=2032, criado_por=self.admin_c.user,
            )
            first = civic.ProgramaPlanejamentoMunicipal.objects.create(
                organization=self.c, exercicio=exercise, secretaria=self.structure[0],
                codigo='P-01', nome='Programa visível', criado_por=self.admin_c.user,
            )
            other_secretary = Secretaria.objects.create(
                organization=self.c, codigo='SEC-SCOPE', nome='Secretaria fora do escopo',
            )
            second = civic.ProgramaPlanejamentoMunicipal.objects.create(
                organization=self.c, exercicio=exercise, secretaria=other_secretary,
                codigo='P-02', nome='Programa sigiloso', criado_por=self.admin_c.user,
            )
        scoped_access = self._user('admin-secretaria-fase-a', self.c, self.publico, 'SERVIDOR_PUBLICO')
        with tenant_context(self.c):
            AcessoMunicipal.objects.create(
                membership=scoped_access, papel=AcessoMunicipal.Papel.ADMIN_SECRETARIA,
                escopo=AcessoMunicipal.Escopo.SECRETARIA, secretaria=self.structure[0],
                atribuido_por=self.admin_c.user,
            )
        with tenant_context(self.c):
            visible = set(scoped_queryset(scoped_access.user, civic.ProgramaPlanejamentoMunicipal.objects.all()).values_list('pk', flat=True))
        self.assertEqual(visible, {first.pk})
        self.assertNotIn(second.pk, visible)

    def test_budget_relations_reject_inconsistent_classification(self):
        with tenant_context(self.c):
            exercise = civic.ExercicioMunicipal.objects.create(
                organization=self.c, ano=2033, criado_por=self.admin_c.user,
            )
            function_a = civic.FuncaoOrcamentariaMunicipal.objects.create(organization=self.c, codigo='01', nome='Função 1')
            function_b = civic.FuncaoOrcamentariaMunicipal.objects.create(organization=self.c, codigo='02', nome='Função 2')
            subfunction = civic.SubfuncaoOrcamentariaMunicipal.objects.create(
                organization=self.c, funcao=function_b, codigo='001', nome='Subfunção de 2',
            )
            orgao = civic.OrgaoOrcamentarioMunicipal.objects.create(organization=self.c, codigo='ORG-1', nome='Órgão teste')
            unit = civic.UnidadeOrcamentariaMunicipal.objects.create(
                organization=self.c, orgao=orgao, codigo='UO-1', nome='Unidade teste',
            )
            nature = civic.NaturezaDespesaMunicipal.objects.create(organization=self.c, codigo='N-1', nome='Natureza')
            source = civic.FonteDestinacaoRecursoMunicipal.objects.create(organization=self.c, codigo='F-1', nome='Fonte')
            dotation = civic.DotacaoOrcamentariaMunicipal(
                organization=self.c, exercicio=exercise, unidade_orcamentaria=unit,
                funcao=function_a, subfuncao=subfunction, natureza_despesa=nature,
                fonte_recurso=source, criado_por=self.admin_c.user,
            )
        with tenant_context(self.c), self.assertRaises(ValidationError):
            dotation.full_clean()

    def test_dashboard_only_exposes_foundation_links_after_module_entitlement(self):
        response = self.client.get(reverse('rh_municipal_public:home'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('rh_municipal_public:planejamento'))
        plan = PlanoSaaS.objects.create(
            slug='municipal-dashboard-fase-a-test', nome='Plano municipal sintético dashboard',
            erp=self.publico, modulos=[], limites={},
        )
        for code in ('gestao_publica', 'planejamento_publico'):
            PlanoProdutoModulo.objects.create(
                plano=plan, modulo=ERPProductModule.objects.get(erp=self.publico, code=code),
            )
        AssinaturaSaaS.objects.create(organization=self.c, plano=plan)
        response = self.client.get(reverse('rh_municipal_public:home'))
        self.assertContains(response, reverse('rh_municipal_public:planejamento'))
