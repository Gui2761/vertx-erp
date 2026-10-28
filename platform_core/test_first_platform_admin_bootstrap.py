import secrets

from django.test import TestCase, override_settings
from django.urls import reverse

from contas.models import Usuario
from platform_core.models import Organization, OrganizationMembership
from platform_core.saas_models import AdministradorPlataforma, AuditoriaSaaS


@override_settings(DEBUG=True, PLATFORM_BOOTSTRAP_TOKEN='')
class FirstPlatformAdminBootstrapTests(TestCase):
    def setUp(self):
        self.url = reverse('platform_core:saas_first_admin_bootstrap')
        self.complete_url = reverse('platform_core:saas_first_admin_complete')
        self.password = secrets.token_urlsafe(32)

    def payload(self, **overrides):
        data = {
            'nome': 'Administradora Inicial',
            'username': 'plataforma-inicial',
            'email': 'plataforma-inicial@example.test',
            'senha': self.password,
            'confirmar_senha': self.password,
        }
        data.update(overrides)
        return data

    def test_bootstrap_is_available_without_active_platform_admin_on_loopback(self):
        response = self.client.get(self.url, REMOTE_ADDR='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Este acesso é exclusivo para administração da plataforma VERTYX.')

    def test_creates_first_platform_admin_without_tenant_or_django_admin_privileges(self):
        response = self.client.post(self.url, self.payload(), REMOTE_ADDR='127.0.0.1')
        self.assertRedirects(response, self.complete_url)
        user = Usuario.objects.get(username='plataforma-inicial')
        self.assertTrue(user.check_password(self.password))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.memberships.exists())
        self.assertTrue(AdministradorPlataforma.objects.filter(user=user, active=True, created_by=user).exists())
        audit = AuditoriaSaaS.objects.get(action='BOOTSTRAP_PRIMEIRO_ADMINISTRADOR_PLATAFORMA')
        self.assertEqual(audit.actor_id, user.pk)
        self.assertNotIn('senha', str(audit.details).lower())
        self.assertNotContains(self.client.get(self.complete_url), self.password)
        login = self.client.post(reverse('contas:login'), {
            'username': user.email,
            'password': self.password,
        })
        self.assertRedirects(login, reverse('platform_core:saas_home'))
        self.assertEqual(self.client.get(reverse('platform_core:saas_home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('platform_core:saas_municipal_new')).status_code, 200)

    def test_bootstrap_closes_after_first_active_admin_and_rejects_second_submission(self):
        self.client.post(self.url, self.payload(), REMOTE_ADDR='127.0.0.1')
        self.assertEqual(self.client.get(self.url, REMOTE_ADDR='127.0.0.1').status_code, 410)
        second = self.payload(username='second-platform-admin', email='second@example.test')
        self.assertEqual(self.client.post(self.url, second, REMOTE_ADDR='127.0.0.1').status_code, 410)
        self.assertEqual(AdministradorPlataforma.objects.filter(active=True).count(), 1)

    def test_authenticated_tenant_admin_cannot_use_bootstrap(self):
        organization = Organization.objects.create(slug='empresa-boot-test', razao_social='Empresa Teste')
        tenant_admin = Usuario.objects.create_user('tenant-admin-bootstrap')
        tenant_admin.set_unusable_password()
        tenant_admin.save(update_fields=['password'])
        OrganizationMembership.objects.create(user=tenant_admin, organization=organization, role='ADMIN')
        self.client.force_login(tenant_admin)
        response = self.client.post(self.url, self.payload(), REMOTE_ADDR='127.0.0.1')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Usuario.objects.filter(username='plataforma-inicial').exists())
        self.assertFalse(AdministradorPlataforma.objects.exists())

    @override_settings(DEBUG=False, PLATFORM_BOOTSTRAP_TOKEN='operator-held-test-token')
    def test_non_debug_requires_operator_token_and_rejects_invalid_token(self):
        self.assertEqual(self.client.get(self.url, REMOTE_ADDR='198.51.100.12').status_code, 200)
        bad = self.client.post(self.url, self.payload(chave_bootstrap='wrong'), REMOTE_ADDR='198.51.100.12')
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, 'Chave de ativação inválida.')
        self.assertFalse(AdministradorPlataforma.objects.exists())
        good = self.client.post(
            self.url,
            self.payload(chave_bootstrap='operator-held-test-token'),
            REMOTE_ADDR='198.51.100.12',
        )
        self.assertRedirects(good, self.complete_url)
        self.assertEqual(AdministradorPlataforma.objects.filter(active=True).count(), 1)

    @override_settings(DEBUG=False, PLATFORM_BOOTSTRAP_TOKEN='')
    def test_non_debug_without_operator_token_fails_closed(self):
        response = self.client.get(self.url, REMOTE_ADDR='198.51.100.12')
        self.assertEqual(response.status_code, 404)

    def test_platform_admin_login_routes_to_saas_home(self):
        user = Usuario.objects.create_user(
            'platform-login', email='platform-login@example.test', password=self.password,
        )
        AdministradorPlataforma.objects.create(user=user, created_by=user)
        response = self.client.post(reverse('contas:login'), {
            'username': user.email,
            'password': self.password,
        })
        self.assertRedirects(response, reverse('platform_core:saas_home'))
