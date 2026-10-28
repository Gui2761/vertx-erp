import uuid
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule
from platform_core.modules import product_module_enabled
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS

from .models import (
    AcessoMunicipal, CompetenciaFolhaMunicipal, DecisaoPontoMunicipal,
    DepartamentoMunicipal,
    EventoFolhaMunicipal, EventoPontoDigital, JustificativaPontoMunicipal,
    MovimentacaoBancoHorasMunicipal, PermissaoMunicipal, PeriodoPontoMunicipal,
    PontoServidor, RemuneracaoBaseServidorMunicipal, Secretaria, Servidor,
    SetorMunicipal, UnidadeMunicipal,
    SnapshotFechamentoPontoMunicipal, SolicitacaoHoraExtraMunicipal,
)
from .phase_c_services import (
    bank_balance_minutes, decide_request, post_bank_movement,
    register_manual_punch, register_punch, request_justification,
    request_overtime, transition_period,
)
from .public_services import scoped_queryset
from .tests import MunicipalFixtures


PHASE_C_MODULES = ('gestao_publica', 'rh_municipal', 'ponto_digital')


class MunicipalPhaseCTests(MunicipalFixtures):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.modules = {}
        for index, code in enumerate(PHASE_C_MODULES, start=50):
            self.modules[code] = ERPProductModule.objects.get_or_create(
                erp=self.publico, code=code,
                defaults={'name': code.replace('_', ' ').title(), 'active': True, 'sort_order': index},
            )[0]
        self.plan = PlanoSaaS.objects.create(
            slug='fase-c-municipal-test', nome='Plano sintético RH e Ponto',
            erp=self.publico, modulos=[], limites={},
        )
        for module in self.modules.values():
            PlanoProdutoModulo.objects.create(plano=self.plan, modulo=module)
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.city_access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )
            self.server_access = AcessoMunicipal.objects.create(
                membership=self.server_user, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=self.server_access, capacidade='servidor.portal')
        self.client.force_login(self.admin_c.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()

    def _login_server(self):
        self.client.force_login(self.server_user.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()

    def test_point_module_is_in_product_catalog_but_not_granted_to_another_tenant(self):
        with tenant_context(self.c):
            self.assertTrue(product_module_enabled(self.admin_c.user, 'gestao-publica', 'ponto_digital'))
            self.assertFalse(product_module_enabled(self.admin_a.user, 'gestao-publica', 'ponto_digital'))

    def test_routes_require_product_module_and_municipal_permission(self):
        for route in ('ponto_home', 'rh_municipal_home', 'rh_municipal_employees', 'folha_home'):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(f'rh_municipal_public:{route}')).status_code, 200)

        restricted = PlanoSaaS.objects.create(
            slug='fase-c-sem-ponto-test', nome='Plano sem Ponto Digital', erp=self.publico,
        )
        for code in ('gestao_publica', 'rh_municipal'):
            PlanoProdutoModulo.objects.create(plano=restricted, modulo=self.modules[code])
        AssinaturaSaaS.objects.filter(organization=self.c).update(plano=restricted)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:ponto_home')).status_code, 403)

    def test_server_portal_is_only_self_and_other_employee_record_is_denied(self):
        self._login_server()
        own = self.client.get(reverse('rh_municipal_public:ponto_home'))
        self.assertEqual(own.status_code, 200)
        self.assertContains(own, 'Meu Ponto')
        with tenant_context(self.c):
            other = self._server(None, matricula='PM-OTHER')
        response = self.client.get(reverse('rh_municipal_public:folha_mirror', args=[other.public_id]))
        self.assertEqual(response.status_code, 403)

    def test_point_registration_is_idempotent_and_immutable(self):
        request_id = uuid.uuid4()
        with tenant_context(self.c):
            first, created = register_punch(self.server_user.user, 'ENTRADA', request_id)
            second, duplicate = register_punch(self.server_user.user, 'ENTRADA', request_id)
            self.assertTrue(created)
            self.assertFalse(duplicate)
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(PontoServidor.all_objects.filter(organization=self.c).count(), 1)
            self.assertEqual(EventoPontoDigital.all_objects.filter(organization=self.c).count(), 1)
            with self.assertRaises(ValidationError):
                first.save()
            with self.assertRaises(ValidationError):
                first.delete()

    def test_registration_sequence_and_closed_period_are_enforced(self):
        with tenant_context(self.c):
            register_punch(self.server_user.user, 'ENTRADA', uuid.uuid4())
            with self.assertRaises(ValidationError):
                register_punch(self.server_user.user, 'RETORNO_INTERVALO', uuid.uuid4())
            now = timezone.localtime(timezone.now())
            period = PeriodoPontoMunicipal.objects.create(
                organization=self.c, ano=now.year, mes=now.month, aberto_por=self.admin_c.user,
            )
            for action in ('conferir', 'enviar_aprovacao', 'aprovar', 'fechar'):
                transition_period(self.admin_c.user, period_id=period.pk, action=action)
            with self.assertRaises(ValidationError):
                register_punch(self.server_user.user, 'SAIDA_INTERVALO', uuid.uuid4())
            self.assertEqual(SnapshotFechamentoPontoMunicipal.all_objects.filter(periodo=period).count(), 4)

    def test_period_reopen_requires_reason_and_preserves_snapshot_versions(self):
        with tenant_context(self.c):
            period = PeriodoPontoMunicipal.objects.create(
                organization=self.c, ano=2032, mes=2, aberto_por=self.admin_c.user,
            )
            for action in ('conferir', 'enviar_aprovacao', 'aprovar', 'fechar'):
                transition_period(self.admin_c.user, period_id=period.pk, action=action)
            with self.assertRaises(ValidationError):
                transition_period(self.admin_c.user, period_id=period.pk, action='reabrir')
            transition_period(self.admin_c.user, period_id=period.pk, action='reabrir', reason='Correção autorizada em teste')
            self.assertEqual(SnapshotFechamentoPontoMunicipal.all_objects.filter(periodo=period).count(), 5)
            period.refresh_from_db()
            self.assertEqual(period.status, PeriodoPontoMunicipal.Status.EM_CONFERENCIA)

    def test_justification_and_overtime_requests_are_decided_and_audited(self):
        now = timezone.now()
        with tenant_context(self.c):
            justification = request_justification(
                self.server_user.user, start=now, end=now + timedelta(hours=1),
                reason='CONSULTA', description='Justificativa de teste sintético',
            )
            overtime = request_overtime(
                self.server_user.user, start=now, end=now + timedelta(minutes=90),
                justification='Atividade extraordinária de teste',
            )
            self.assertEqual(overtime.quantidade_minutos, 90)
            decide_request(self.admin_c.user, request_type='justificativa', request_id=justification.pk, approve=True, reason='Conferida')
            decide_request(self.admin_c.user, request_type='hora_extra', request_id=overtime.pk, approve=False, reason='Não aprovada em teste')
            justification.refresh_from_db(); overtime.refresh_from_db()
            self.assertEqual(justification.status, 'APROVADA')
            self.assertEqual(overtime.status, 'REJEITADA')
            self.assertEqual(DecisaoPontoMunicipal.all_objects.filter(organization=self.c).count(), 2)

    def test_rendered_server_forms_submit_justification_and_overtime(self):
        self._login_server()
        page = self.client.get(reverse('rh_municipal_public:ponto_home'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="inicio"')
        start = timezone.localtime(timezone.now()).replace(second=0, microsecond=0)
        start_value = start.strftime('%Y-%m-%dT%H:%M')
        end_value = (start + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M')
        justification = self.client.post(reverse('rh_municipal_public:ponto_home'), {
            'action': 'justification', 'inicio': start_value, 'fim': end_value,
            'motivo': 'CONSULTA', 'descricao': 'Justificativa postada pelo formulário renderizado',
        })
        self.assertEqual(justification.status_code, 302)
        overtime = self.client.post(reverse('rh_municipal_public:ponto_home'), {
            'action': 'overtime', 'inicio': start_value, 'fim': end_value,
            'justificativa': 'Solicitação postada pelo formulário renderizado',
        })
        self.assertEqual(overtime.status_code, 302)
        self.assertEqual(JustificativaPontoMunicipal.all_objects.filter(servidor=self.server).count(), 1)
        self.assertEqual(SolicitacaoHoraExtraMunicipal.all_objects.filter(servidor=self.server).count(), 1)

    def test_scoped_manager_sees_only_its_department_requests(self):
        with tenant_context(self.c):
            secretary = Secretaria.objects.create(organization=self.c, codigo='SEC-OUT', nome='Secretaria fora do escopo')
            department = DepartamentoMunicipal.objects.create(organization=self.c, secretaria=secretary, codigo='DEP-OUT', nome='Departamento externo')
            sector = SetorMunicipal.objects.create(organization=self.c, departamento=department, codigo='SET-OUT', nome='Setor externo')
            unit = UnidadeMunicipal.objects.create(organization=self.c, setor=sector, codigo='UNI-OUT', nome='Unidade externa')
            other = Servidor.objects.create(
                organization=self.c, matricula='PM-OTHER-SCOPE', nome='Servidor fora do escopo',
                secretaria=secretary, departamento=department, setor=sector, unidade=unit,
                cargo=self.structure[4], vinculo=self.structure[6],
            )
            outside = SolicitacaoHoraExtraMunicipal.objects.create(
                organization=self.c, servidor=other, inicio=timezone.now(), fim=timezone.now() + timedelta(minutes=30),
                quantidade_minutos=30, justificativa='Fora do escopo', solicitado_por=self.admin_c.user,
            )
            inside = SolicitacaoHoraExtraMunicipal.objects.create(
                organization=self.c, servidor=self.server, inicio=timezone.now(), fim=timezone.now() + timedelta(minutes=30),
                quantidade_minutos=30, justificativa='Dentro do escopo', solicitado_por=self.admin_c.user,
            )
            manager_membership = self._user('gestor-phase-c-scope', self.c, self.publico, 'GESTOR')
            manager = AcessoMunicipal.objects.create(
                membership=manager_membership, papel=AcessoMunicipal.Papel.GESTOR_DEPARTAMENTO,
                escopo=AcessoMunicipal.Escopo.DEPARTAMENTO, departamento=self.structure[1],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=manager, capacidade='ponto.approve')
            visible = scoped_queryset(manager_membership.user, SolicitacaoHoraExtraMunicipal.objects.filter(status='PENDENTE'))
            self.assertIn(inside.pk, set(visible.values_list('pk', flat=True)))
            self.assertNotIn(outside.pk, set(visible.values_list('pk', flat=True)))

    def test_manual_correction_is_a_separate_audited_point_event(self):
        with tenant_context(self.c):
            occurred = timezone.now() - timedelta(hours=1)
            point = register_manual_punch(
                self.admin_c.user, server_id=self.server.pk, kind='ENTRADA',
                occurred_at=occurred, reason='Ajuste autorizado para teste',
            )
            self.assertEqual(point.origem, 'MANUAL')
            self.assertEqual(point.observacao, 'Ajuste autorizado para teste')
            self.assertEqual(EventoPontoDigital.all_objects.filter(servidor=self.server).count(), 1)

    def test_bank_balance_uses_immutable_ledger_only(self):
        with tenant_context(self.c):
            post_bank_movement(
                self.admin_c.user, servidor_id=self.server.pk, kind='CREDITO', minutes=75,
                origin='AJUSTE_AUTORIZADO', justification='Crédito sintético auditado',
            )
            post_bank_movement(
                self.admin_c.user, servidor_id=self.server.pk, kind='DEBITO', minutes=15,
                origin='COMPENSACAO', justification='Débito sintético auditado',
            )
            self.assertEqual(bank_balance_minutes(self.server), 60)
            self.assertEqual(MovimentacaoBancoHorasMunicipal.all_objects.filter(servidor=self.server).count(), 2)

    def test_payroll_foundation_records_are_informative_not_calculated(self):
        response = self.client.get(reverse('rh_municipal_public:folha_home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Não calcula folha')
        with tenant_context(self.c):
            competency = CompetenciaFolhaMunicipal.objects.create(
                organization=self.c, ano=2032, mes=3, criado_por=self.admin_c.user,
            )
            event = EventoFolhaMunicipal.objects.create(
                organization=self.c, codigo='INFO-01', nome='Referência informativa', natureza='PROVENTO',
            )
            self.assertEqual(competency.status, CompetenciaFolhaMunicipal.Status.PREPARACAO)
            self.assertEqual(event.natureza, EventoFolhaMunicipal.Natureza.PROVENTO)
            self.assertFalse(hasattr(event, 'calculo'))

    def test_scope_and_tenant_foreign_keys_fail_closed(self):
        other_org = self.a
        with tenant_context(self.c):
            foreign_server = Servidor.all_objects.filter(organization=other_org).first()
            self.assertIsNone(foreign_server)
            with self.assertRaises(PermissionDenied):
                register_manual_punch(
                    self.server_user.user, server_id=999999, kind='ENTRADA',
                    occurred_at=timezone.now(), reason='ID adulterado',
                )

    def test_pwa_manifest_and_worker_are_separate_and_do_not_cache_private_pages(self):
        manifest = self.client.get(reverse('rh_municipal_public:ponto_manifest'))
        self.assertEqual(manifest.status_code, 200)
        self.assertContains(manifest, 'VERTYX Ponto Digital')
        self.assertContains(manifest, '"scope": "/gestao-publica/ponto/"')
        worker = self.client.get(reverse('rh_municipal_public:ponto_worker'))
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker['Service-Worker-Allowed'], '/gestao-publica/ponto/')
        self.assertNotContains(worker, 'caches.open')
        self.assertNotContains(worker, 'addEventListener(\'fetch\'')
        self.assertContains(worker, 'skipWaiting')

    @override_settings(MUNICIPAL_POINT_LOCATION_ENABLED=False)
    def test_location_data_is_ignored_when_location_is_not_configured(self):
        self._login_server()
        response = self.client.post(reverse('rh_municipal_public:ponto_home'), {
            'action': 'punch', 'tipo': 'ENTRADA', 'request_id': str(uuid.uuid4()),
            'latitude': '-23.550520', 'longitude': '-46.633308',
        })
        self.assertEqual(response.status_code, 302)
        point = PontoServidor.all_objects.get(servidor=self.server)
        self.assertIsNone(point.latitude)
        self.assertIsNone(point.longitude)
