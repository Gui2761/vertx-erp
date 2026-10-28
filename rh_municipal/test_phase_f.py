import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, ModuloOrganizacao, OrganizationERP
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS

from . import phase_f_models as m
from . import phase_f_services as svc
from .models import AcessoMunicipal, PermissaoMunicipal, Secretaria
from .tests import MunicipalFixtures


PHASE_F_CODES = ('gestao_publica', 'tributos_municipais', 'gestao_territorial', 'nfse_municipal')


class MunicipalPhaseFTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.modules = {}
        for order, code in enumerate(PHASE_F_CODES, 110):
            self.modules[code] = ERPProductModule.objects.get_or_create(
                erp=self.publico, code=code,
                defaults={'name': code.replace('_', ' ').title(), 'active': True, 'sort_order': order},
            )[0]
        self.plan = PlanoSaaS.objects.create(
            slug='fase-f-municipal-test', nome='Plano sintético Fase F', erp=self.publico, modulos=[],
        )
        for module in self.modules.values():
            PlanoProdutoModulo.objects.get_or_create(plano=self.plan, modulo=module)
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.city_access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()

    def _contributor(self, organization=None, **overrides):
        org = organization or self.c
        data = {
            'codigo': f'CT-{uuid.uuid4().hex[:8]}', 'tipo': m.ContribuinteMunicipal.Tipo.PESSOA_FISICA,
            'documento': '11111111111', 'nome': 'Contribuinte Sintético',
        }
        data.update(overrides)
        with tenant_context(org):
            row = m.ContribuinteMunicipal(organization=org, **data)
            row.save()
        return row

    def _rule(self, **overrides):
        data = {
            'codigo': f'RULE-{uuid.uuid4().hex[:6]}', 'tributo': m.RegraTributariaMunicipal.Tributo.ISS,
            'versao': 1, 'vigencia_inicio': timezone.localdate() - timedelta(days=1),
            'parametros': {'aliquota_percentual': '2.5'}, 'ativa': True,
        }
        data.update(overrides)
        with tenant_context(self.c):
            return svc.save_tax_rule(self.admin_c.user, data=data)

    def test_module_contract_and_permission_gate_phase_f_views(self):
        for name in ('tributary_home', 'territory_home', 'nfse_home'):
            response = self.client.get(reverse(f'rh_municipal_public:{name}'))
            self.assertEqual(response.status_code, 200, name)
        limited = PlanoSaaS.objects.create(slug='fase-f-without-tax', nome='Sem tributos', erp=self.publico, modulos=[])
        for code in ('gestao_publica', 'gestao_territorial', 'nfse_municipal'):
            PlanoProdutoModulo.objects.create(plano=limited, modulo=self.modules[code])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=limited)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:tributary_home')).status_code, 403)

    def test_field_pwa_has_own_scope_and_never_caches_authenticated_data(self):
        page = self.client.get(reverse('rh_municipal_public:territory_home'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, reverse('rh_municipal_public:territory_manifest'))
        manifest = self.client.get(reverse('rh_municipal_public:territory_manifest'))
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()['scope'], '/gestao-publica/territorio/')
        worker = self.client.get(reverse('rh_municipal_public:territory_worker'))
        self.assertEqual(worker.status_code, 200)
        self.assertIn('no-store', worker['Cache-Control'])
        self.assertIn('fetch(e.request', worker.content.decode())
        self.assertNotIn('caches.open', worker.content.decode())
        self.assertEqual(ModuloOrganizacao.objects.filter(organization=self.c, codigo__in=(
            'tributos_municipais', 'gestao_territorial', 'nfse_municipal',
        )).count(), 0)

    def test_contributor_and_property_are_tenant_scoped_and_cross_tenant_fk_is_rejected(self):
        with tenant_context(self.c):
            contributor = svc.create_contributor(self.admin_c.user, data={
                'codigo': 'C-001', 'tipo': 'PF', 'documento': '11111111111', 'nome': 'Pessoa Sintética',
            })
        with tenant_context(self.a):
            OrganizationERP.objects.create(organization=self.a, erp=self.publico, enabled=True)
            other_person = self._contributor(self.a, codigo='A-001', documento='22222222222')
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                svc.create_property(self.admin_c.user, data={
                    'inscricao': 'IM-001', 'proprietario': other_person, 'logradouro': 'Rua Sintética',
                })
            prop = svc.create_property(self.admin_c.user, data={
                'inscricao': 'IM-002', 'proprietario': contributor, 'logradouro': 'Rua Sintética',
                'area_terreno': Decimal('100.00'), 'utilizacao': 'RESIDENCIAL',
            })
            self.assertEqual(prop.organization_id, self.c.pk)
        with tenant_context(self.a):
            self.assertFalse(m.ImovelMunicipal.objects.filter(pk=prop.pk, organization=self.a).exists())

    def test_versioned_rule_launch_installments_payment_and_idempotency(self):
        taxpayer = self._contributor()
        rule = self._rule()
        with tenant_context(self.c):
            launch = svc.create_tax_launch(
                self.admin_c.user, taxpayer_id=taxpayer.pk, tax_type='ISS',
                base_amount='1000.00', due_date=timezone.localdate() - timedelta(days=1),
                rule_id=rule.pk, exercise=timezone.localdate().year,
            )
            self.assertEqual(launch.valor_total, Decimal('25.00'))
            installments = svc.create_installments(
                self.admin_c.user, launch_id=launch.pk, count=3,
                first_due=timezone.localdate(), interval_days=30,
            )
            self.assertEqual([row.valor for row in installments], [
                Decimal('8.34'), Decimal('8.33'), Decimal('8.33'),
            ])
            request_id = uuid.uuid4()
            payment = svc.record_manual_payment(
                self.admin_c.user, installment_id=installments[0].pk, amount='8.34', request_id=request_id,
            )
            repeated = svc.record_manual_payment(
                self.admin_c.user, installment_id=installments[0].pk, amount='8.34', request_id=request_id,
            )
            self.assertEqual(payment.pk, repeated.pk)
            self.assertEqual(m.PagamentoArrecadacaoMunicipal.objects.filter(request_id=request_id).count(), 1)
            self.assertEqual(m.AuditoriaTributariaMunicipal.objects.filter(organization=self.c).count(), 4)

    def test_no_rule_rate_or_official_transmission_is_invented(self):
        taxpayer = self._contributor()
        rule = self._rule(parametros={'observacao': 'Sem alíquota oficial definida'})
        with tenant_context(self.c):
            with self.assertRaisesMessage(ValidationError, 'não possui alíquota parametrizada'):
                svc.create_tax_launch(
                    self.admin_c.user, taxpayer_id=taxpayer.pk, tax_type='ISS',
                    base_amount='100.00', due_date=timezone.localdate(),
                    rule_id=rule.pk, exercise=timezone.localdate().year,
                )
            with self.assertRaisesMessage(ValidationError, 'Transmissão NFS-e indisponível'):
                svc.transmit_nfse()

    def test_active_rule_versions_cannot_overlap_and_are_scoped_by_tenant(self):
        code = f'RULE-{uuid.uuid4().hex[:6]}'
        first = self._rule(codigo=code)
        with tenant_context(self.c), self.assertRaisesMessage(ValidationError, 'vigência sobreposta'):
            svc.save_tax_rule(self.admin_c.user, data={
                'codigo': code, 'tributo': 'ISS', 'versao': 2,
                'vigencia_inicio': timezone.localdate(), 'parametros': {'aliquota_percentual': '3'},
                'ativa': True,
            })
        with tenant_context(self.c):
            self.assertTrue(m.RegraTributariaMunicipal.objects.filter(pk=first.pk, organization=self.c).exists())

    def test_subscope_cannot_read_or_write_records_outside_assigned_unit(self):
        person = self._contributor()
        with tenant_context(self.c):
            outside = Secretaria.objects.create(organization=self.c, codigo='F-SEC', nome='Secretaria F')
            scoped = self._user('phase-f-scoped', self.c, self.publico, 'ADMIN')
            access = AcessoMunicipal.objects.create(
                membership=scoped, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='contribuinte.view')
            PermissaoMunicipal.objects.create(acesso=access, capacidade='contribuinte.manage')
            person.secretaria = outside
            person.save()
            from .public_services import scoped_queryset
            self.assertFalse(scoped_queryset(scoped.user, m.ContribuinteMunicipal.objects.filter(pk=person.pk)).exists())
            with self.assertRaises(PermissionDenied):
                svc.create_contributor(scoped.user, data={
                    'codigo': 'OUT-SCOPE', 'tipo': 'PF', 'documento': '33333333333',
                    'nome': 'Fora do escopo',
                })

    def test_nfse_draft_is_saved_without_transmission(self):
        provider = self._contributor(codigo='NF-1', documento='44444444444', tipo='PF')
        customer = self._contributor(codigo='NF-2', documento='55555555555', tipo='PF')
        with tenant_context(self.c):
            draft = svc.create_nfse_draft(self.admin_c.user, data={
                'prestador': provider, 'tomador': customer, 'codigo_servico': 'SERV-LOCAL',
                'descricao': 'Rascunho sem emissão', 'competencia': '2026-10',
                'valor_servico': Decimal('200.00'),
            })
            self.assertEqual(draft.status, m.NotaServicoMunicipal.Status.RASCUNHO)
            self.assertEqual(draft.parametros_snapshot['transmissao'], 'PENDENTE_INTEGRACAO_OFICIAL')
