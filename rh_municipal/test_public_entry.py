from django.test import Client, TestCase, override_settings
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ModuloOrganizacao
from .models import AcessoMunicipal
from .tests import MunicipalFixtures


class PublicManagementEntryTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        with tenant_context(self.c):
            AcessoMunicipal.objects.create(
                membership=self.admin_c,
                papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA,
                atribuido_por=self.admin_c.user,
            )

    def test_public_site_links_to_public_management_presentation(self):
        self.client.logout()
        response = self.client.get(reverse('commercial:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('rh_municipal_public:home'))
        self.assertNotContains(response, '/vertyx/saas/')

    def test_anonymous_management_home_is_product_presentation_not_admin(self):
        self.client.logout()
        response = self.client.get(reverse('rh_municipal_public:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gestão inteligente para')
        self.assertContains(response, reverse('rh_municipal_public:login'))
        self.assertNotContains(response, 'bootstrap-inicial')
        self.assertNotContains(response, '/vertyx/saas/')

    def test_authorized_municipal_user_logs_into_its_organization_dashboard(self):
        self.client.logout()
        response = self.client.post(reverse('rh_municipal_public:login'), {
            'username': self.admin_c.user.username,
            'password': 'synthetic-only-password',
            'next': reverse('rh_municipal_public:home'),
        })
        self.assertRedirects(response, reverse('rh_municipal_public:home'))
        self.assertEqual(self.client.session['organization_id'], self.c.pk)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:home')).status_code, 200)

    def test_general_login_routes_explicit_municipal_admin_to_public_dashboard(self):
        # Explicit municipal access is authoritative; generic tenant role does
        # not grant it, and the municipal core does not depend on legacy RH access.
        membership = self._user('municipal-core-admin', self.c, self.publico, 'ADMIN')
        with tenant_context(self.c):
            AcessoMunicipal.objects.create(
                membership=membership,
                papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA,
                atribuido_por=self.admin_c.user,
            )
        self.client.logout()
        response = self.client.post('/login/', {
            'username': membership.user.username,
            'password': 'synthetic-only-password',
            'next': '/vertyx/',
        })
        self.assertRedirects(response, '/gestao-publica/', fetch_redirect_response=False)
        self.assertEqual(self.client.session['organization_id'], self.c.pk)
        self.assertEqual(self.client.get('/gestao-publica/').status_code, 200)

    def test_product_selector_uses_municipal_core_access_not_hr_role(self):
        membership = self._user('municipal-core-selector', self.c, self.publico, 'ADMIN')
        with tenant_context(self.c):
            AcessoMunicipal.objects.create(
                membership=membership,
                papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA,
                atribuido_por=self.admin_c.user,
            )
        self.client.force_login(membership.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.get('/vertyx/')
        self.assertRedirects(response, '/gestao-publica/', fetch_redirect_response=False)

    def test_tenant_admin_without_municipal_access_is_not_authenticated(self):
        self.client.logout()
        response = self.client.post(reverse('rh_municipal_public:login'), {
            'username': self.admin_a.user.username,
            'password': 'synthetic-only-password',
            'next': reverse('rh_municipal_public:home'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'não possui acesso ativo ao ERP Gestão Pública')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_disabled_municipal_module_blocks_login(self):
        with tenant_context(self.c):
            ModuloOrganizacao.objects.create(
                organization=self.c, codigo='gestao_publica', habilitado=False,
            )
        self.client.logout()
        response = self.client.post(reverse('rh_municipal_public:login'), {
            'username': self.admin_c.user.username,
            'password': 'synthetic-only-password',
            'next': reverse('rh_municipal_public:home'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'não possui acesso ativo ao ERP Gestão Pública')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_authenticated_wrong_organization_gets_friendly_denial(self):
        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        response = self.client.get(reverse('rh_municipal_public:home'))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Acesso não disponível', status_code=403)
        self.assertNotContains(response, 'Visão geral', status_code=403)

    def test_tenant_admin_still_cannot_open_platform_saas_or_bootstrap(self):
        self.client.force_login(self.admin_c.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get('/vertyx/saas/').status_code, 403)
        self.assertEqual(self.client.get('/vertyx/saas/bootstrap-inicial/').status_code, 403)

    @override_settings(DEBUG=True, PLATFORM_BOOTSTRAP_TOKEN='')
    def test_logout_is_post_only_and_clears_tenant_session_before_bootstrap(self):
        logout_url = reverse('contas:logout')
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin_c.user)
        session = client.session
        session['organization_id'] = self.c.pk
        session.save()

        public_home = client.get(reverse('rh_municipal_public:home'))
        self.assertContains(public_home, 'method="post"')
        self.assertContains(public_home, f'action="{logout_url}"')
        self.assertEqual(client.get(logout_url).status_code, 405)

        csrf_token = client.cookies['csrftoken'].value
        response = client.post(logout_url, HTTP_X_CSRFTOKEN=csrf_token)
        self.assertRedirects(response, reverse('contas:login'))
        self.assertNotIn('_auth_user_id', client.session)
        self.assertNotIn('organization_id', client.session)
        bootstrap = client.get(reverse('platform_core:saas_first_admin_bootstrap'), REMOTE_ADDR='127.0.0.1')
        self.assertEqual(bootstrap.status_code, 200)
        self.assertContains(bootstrap, 'Configuração inicial')

