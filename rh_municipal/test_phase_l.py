import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS
from . import phase_l_models as m
from . import phase_l_services as service
from .models import AcessoMunicipal, PermissaoMunicipal
from .tests import MunicipalFixtures


class MunicipalPhaseLTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.codes = ('gestao_publica', 'compras_publicas', 'contabilidade_pub', 'rh_municipal', 'saude_sus')
        self.modules = {
            code: ERPProductModule.objects.get_or_create(
                erp=self.publico, code=code,
                defaults={'name': code.replace('_', ' ').title(), 'active': True, 'sort_order': 10},
            )[0] for code in self.codes
        }
        self.plan = PlanoSaaS.objects.create(
            slug=f'phase-l-{uuid.uuid4().hex[:10]}', nome='Plano sintético integrações',
            erp=self.publico, modulos=[],
        )
        for module in self.modules.values():
            PlanoProdutoModulo.objects.get_or_create(plano=self.plan, modulo=module)
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )

    def _config(self):
        with tenant_context(self.c):
            return service.create_configuration(
                self.admin_c.user, provider='PNCP', name='Ambiente de homologação',
                endpoint='https://pncp.example.invalid/api', api_version='v1',
                credential_reference='cofre://00000000-0000-4000-8000-000000000001',
            )

    def test_configuration_is_tenant_scoped_and_requires_entitlement_and_permission(self):
        config = self._config()
        self.assertFalse(config.habilitada)
        self.assertEqual(config.organization_id, self.c.pk)
        with tenant_context(self.a):
            self.assertFalse(m.ConfiguracaoIntegracaoMunicipal.objects.filter(pk=config.pk).exists())
            with self.assertRaises((PermissionDenied, ValidationError)):
                service.request_transmission(
                    self.admin_a.user, config_id=config.pk,
                    idempotency_key='foreign', request_body={'synthetic': True},
                )
        unsupported = self._user('phase-l-no-integration-module', self.c, self.publico, 'ADMIN')
        with tenant_context(self.c):
            with self.assertRaises(PermissionDenied):
                service.create_configuration(
                    unsupported.user, provider='PNCP', name='Sem acesso',
                    endpoint='https://pncp.example.invalid',
                )
            PlanoProdutoModulo.objects.filter(plano=self.plan, modulo=self.modules['compras_publicas']).delete()
            with self.assertRaises(PermissionDenied):
                service.create_configuration(
                    self.admin_c.user, provider='PNCP', name='Módulo removido',
                    endpoint='https://pncp.example.invalid',
                )

    def test_secrets_and_insecure_endpoint_are_rejected_and_configuration_stays_disabled(self):
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                service.create_configuration(
                    self.admin_c.user, provider='PNCP', name='HTTP inválido',
                    endpoint='http://pncp.example.invalid/api',
                )
            with self.assertRaises(ValidationError):
                service.create_configuration(
                    self.admin_c.user, provider='PNCP', name='Senha indevida',
                    endpoint='https://pncp.example.invalid', credential_reference='senha-secreta-de-teste',
                )
            config = self._config()
            with self.assertRaises(ValidationError):
                config.habilitada = True
                config.full_clean()
            config.refresh_from_db()
            self.assertFalse(config.habilitada)

    def test_attempt_is_blocked_idempotent_and_stores_only_digest(self):
        config = self._config()
        body = {'identificador_sintetico': 'conteudo-nao-persistido'}
        with tenant_context(self.c):
            first = service.request_transmission(
                self.admin_c.user, config_id=config.pk,
                idempotency_key='phase-l-idempotency-001', request_body=body,
            )
            second = service.request_transmission(
                self.admin_c.user, config_id=config.pk,
                idempotency_key='phase-l-idempotency-001', request_body=body,
            )
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(m.TentativaIntegracaoMunicipal.objects.filter(organization=self.c).count(), 1)
            self.assertEqual(first.status, m.TentativaIntegracaoMunicipal.Status.BLOQUEADA)
            self.assertEqual(first.codigo_erro, 'ADAPTADOR_PENDENTE')
            self.assertEqual(len(first.digest_requisicao), 64)
            self.assertNotIn('conteudo-nao-persistido', repr(first.__dict__))
            with self.assertRaises(ValidationError):
                service.request_transmission(
                    self.admin_c.user, config_id=config.pk,
                    idempotency_key='phase-l-idempotency-001', request_body={'outro': 'conteudo'},
                )
            with self.assertRaises(ValidationError):
                first.delete()

    def test_integration_screen_requires_product_module_and_permission(self):
        response = self.client.get(reverse('rh_municipal_public:integrations'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Transmissões desativadas')
        stranger = self._user('phase-l-no-access', self.c, self.publico, 'ADMIN')
        self.client.force_login(stranger.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:integrations')).status_code, 403)

    def test_admin_can_prepare_configuration_without_exposing_secret_reference(self):
        reference = 'cofre://00000000-0000-4000-8000-000000000002'
        response = self.client.post(reverse('rh_municipal_public:integrations'), {
            'provedor': 'PNCP', 'nome': 'PNCP Homologação',
            'endpoint': 'https://pncp.example.invalid/api', 'versao_api': 'v1',
            'ambiente': 'HOMOLOGACAO', 'referencia_credencial': reference,
        })
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.c):
            config = m.ConfiguracaoIntegracaoMunicipal.objects.get(nome='PNCP Homologação')
            self.assertFalse(config.habilitada)
            self.assertTrue(config.eventos.filter(acao='CONFIGURACAO_CRIADA').exists())
        response = self.client.get(reverse('rh_municipal_public:integrations'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Referência registrada')
        self.assertNotContains(response, reference)
