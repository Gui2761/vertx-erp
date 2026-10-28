from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import (
    ERPCatalog, MembershipERP, ModuloOrganizacao, Organization,
    OrganizationERP, OrganizationMembership,
)
from platform_core.saas_models import (
    AdministradorPlataforma, AssinaturaSaaS, AuditoriaSaaS, PlanoSaaS,
    PrimeiroAcessoSaaS,
)
from platform_core.saas_services import bootstrap_administrador_prefeitura, criar_prefeitura_homologacao
from rh_municipal.models import AcessoMunicipal


class MunicipalBootstrapTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.platform_user = User.objects.create_user(
            username='saas-bootstrap-admin', email='saas-bootstrap@example.test', password='synthetic-pass-9876',
        )
        AdministradorPlataforma.objects.create(
            user=self.platform_user, created_by=self.platform_user,
        )
        self.org = Organization.objects.create(slug='bootstrap-prefeitura-a', razao_social='Prefeitura A')
        self.other_org = Organization.objects.create(slug='bootstrap-prefeitura-b', razao_social='Prefeitura B')
        self.erp, _ = ERPCatalog.objects.get_or_create(
            code='gestao-publica', defaults={'name': 'ERP Gestão Pública', 'active': True},
        )
        OrganizationERP.objects.create(organization=self.org, erp=self.erp, enabled=True)
        OrganizationERP.objects.create(organization=self.other_org, erp=self.erp, enabled=True)
        self.plan = PlanoSaaS.objects.create(
            slug='municipal-bootstrap-test', nome='Municipal Teste',
            modulos=['gestao_publica'], limites={},
        )
        AssinaturaSaaS.objects.create(organization=self.org, plano=self.plan)
        AssinaturaSaaS.objects.create(organization=self.other_org, plano=self.plan)
        self.membership = self._membership(self.org, 'prefeitura-admin')
        self.other_membership = self._membership(self.other_org, 'admin-outra-prefeitura')

    def _membership(self, organization, username):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(
            username=username, email=f'{username}@example.test', password='synthetic-pass-9876',
        )
        membership = OrganizationMembership.objects.create(
            organization=organization, user=user, role='ADMIN',
            status=OrganizationMembership.Status.ACTIVE,
        )
        MembershipERP.objects.create(membership=membership, erp=self.erp, enabled=True)
        return membership

    def _post_bootstrap(self, *, organization=None, membership=None):
        return self.client.post(reverse('platform_core:saas_municipal_bootstrap'), {
            'organization': (organization or self.org).pk,
            'membership': (membership or self.membership).pk,
        })

    def test_platform_admin_bootstraps_existing_active_admin_membership_and_home(self):
        self.client.force_login(self.platform_user)
        page = self.client.get(reverse('platform_core:saas_municipal_bootstrap'), {'organization': self.org.pk})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Primeiro acesso da Prefeitura')
        self.assertContains(page, 'Produto na organização')

        response = self._post_bootstrap()
        self.assertEqual(response.status_code, 302)
        access = AcessoMunicipal.all_objects.get(membership=self.membership)
        self.assertEqual(access.papel, AcessoMunicipal.Papel.ADMIN_PREFEITURA)
        self.assertEqual(access.escopo, AcessoMunicipal.Escopo.PREFEITURA)
        self.assertEqual(access.atribuido_por, self.platform_user)
        self.assertTrue(AuditoriaSaaS.objects.filter(
            actor=self.platform_user, organization=self.org,
            action='BOOTSTRAP_ADMIN_PREFEITURA', record=f'acesso-municipal:{access.pk}',
        ).exists())

        self.client.force_login(self.membership.user)
        session = self.client.session
        session['organization_id'] = self.org.pk
        session.save()
        home = self.client.get('/gestao-publica/')
        self.assertEqual(home.status_code, 200)

    def test_tenant_admin_cannot_bootstrap_or_self_promote(self):
        self.client.force_login(self.membership.user)
        response = self._post_bootstrap()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AcessoMunicipal.all_objects.exists())
        session = self.client.session
        session['organization_id'] = self.org.pk
        session.save()
        self.assertEqual(self.client.get('/gestao-publica/').status_code, 403)

    def test_membership_from_another_organization_is_rejected(self):
        self.client.force_login(self.platform_user)
        response = self._post_bootstrap(membership=self.other_membership)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AcessoMunicipal.all_objects.exists())

    def test_disabled_organization_product_blocks_without_creating_access(self):
        OrganizationERP.objects.filter(organization=self.org, erp=self.erp).update(enabled=False)
        with self.assertRaisesMessage(ValidationError, 'produto Gestão Pública não está habilitado'):
            bootstrap_administrador_prefeitura(
                actor=self.platform_user, organization_id=self.org.pk, membership_id=self.membership.pk,
            )
        self.assertFalse(AcessoMunicipal.all_objects.exists())
        self.assertFalse(AuditoriaSaaS.objects.filter(action='BOOTSTRAP_ADMIN_PREFEITURA').exists())

    def test_uncontracted_or_disabled_module_blocks_without_access(self):
        with tenant_context(self.org):
            ModuloOrganizacao.objects.create(
                organization=self.org, codigo='gestao_publica', habilitado=False,
            )
        with self.assertRaisesMessage(ValidationError, 'não está contratado/ativo'):
            bootstrap_administrador_prefeitura(
                actor=self.platform_user, organization_id=self.org.pk, membership_id=self.membership.pk,
            )
        self.assertFalse(AcessoMunicipal.all_objects.exists())

    def test_membership_product_entitlement_is_required(self):
        MembershipERP.objects.filter(membership=self.membership, erp=self.erp).update(enabled=False)
        with self.assertRaisesMessage(ValidationError, 'MembershipERP'):
            bootstrap_administrador_prefeitura(
                actor=self.platform_user, organization_id=self.org.pk, membership_id=self.membership.pk,
            )
        self.assertFalse(AcessoMunicipal.all_objects.exists())

    def test_bootstrap_refuses_existing_municipal_access_without_duplication(self):
        with tenant_context(self.org):
            AcessoMunicipal.all_objects.create(
                membership=self.membership,
                papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA,
                atribuido_por=self.membership.user,
            )
        self.client.force_login(self.platform_user)
        response = self._post_bootstrap()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'já possui um AcessoMunicipal')
        self.assertEqual(AcessoMunicipal.all_objects.filter(membership__organization=self.org).count(), 1)

    def test_superuser_is_allowed_but_admin_tenant_role_is_not_a_platform_capability(self):
        from django.contrib.auth import get_user_model
        superuser = get_user_model().objects.create_superuser(
            username='bootstrap-superuser', email='root@example.test', password='synthetic-pass-9876',
        )
        access = bootstrap_administrador_prefeitura(
            actor=superuser, organization_id=self.org.pk, membership_id=self.membership.pk,
        )
        self.assertEqual(access.atribuido_por, superuser)

    def test_route_requires_platform_authority_for_get_and_post(self):
        url = reverse('platform_core:saas_municipal_bootstrap')
        self.client.force_login(self.membership.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'organization': self.org.pk, 'membership': self.membership.pk}).status_code, 403)
        self.assertFalse(AcessoMunicipal.all_objects.exists())

    def test_create_municipal_tenant_grants_only_explicit_municipal_access_and_first_access(self):
        result = criar_prefeitura_homologacao(
            actor=self.platform_user,
            razao_social='Prefeitura Municipal Sintética',
            nome_fantasia='Prefeitura Sintética',
            administrador_nome='Admin Teste Municipal',
            administrador_email='admin-prefeitura-sintetica@example.test',
        )
        organization = result['organization']
        membership = result['membership']
        self.assertEqual(organization.cnpj, '')
        self.assertFalse(AssinaturaSaaS.objects.filter(organization=organization).exists())
        self.assertEqual(membership.role, 'SERVIDOR_PUBLICO')
        self.assertFalse(membership.user.has_usable_password())
        self.assertEqual(result['access'].papel, AcessoMunicipal.Papel.ADMIN_PREFEITURA)
        self.assertEqual(result['access'].escopo, AcessoMunicipal.Escopo.PREFEITURA)
        self.assertTrue(OrganizationERP.objects.filter(
            organization=organization, erp__code='gestao-publica', enabled=True,
        ).exists())
        self.assertTrue(MembershipERP.objects.filter(
            membership=membership, erp__code='gestao-publica', enabled=True,
        ).exists())
        self.assertTrue(ModuloOrganizacao.all_objects.filter(
            organization=organization, codigo='gestao_publica', habilitado=True,
        ).exists())
        token_row = PrimeiroAcessoSaaS.objects.get(pk=result['token_id'])
        self.assertEqual(token_row.token_digest, PrimeiroAcessoSaaS.digest(result['token']))
        self.assertNotEqual(token_row.token_digest, result['token'])
        self.assertEqual(token_row.user_id, membership.user_id)

    def test_municipal_first_access_sets_password_and_login_redirects_to_home(self):
        from django.urls import reverse
        result = criar_prefeitura_homologacao(
            actor=self.platform_user,
            razao_social='Prefeitura Login Sintética',
            nome_fantasia='Prefeitura Login',
            administrador_nome='Admin Login Municipal',
            administrador_email='admin-login-municipal@example.test',
        )
        token_url = reverse('platform_core:saas_first_access', args=[result['token']])
        get_response = self.client.get(token_url)
        self.assertEqual(get_response.status_code, 200)
        password = 'A-temporary-test-password-8392!'
        response = self.client.post(token_url, {
            'new_password1': password,
            'new_password2': password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(result['user'].__class__.objects.get(pk=result['user'].pk).has_usable_password())
        self.client.logout()
        response = self.client.post('/contas/login/', {
            'username': result['user'].email,
            'password': password,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/gestao-publica/')
        self.assertEqual(self.client.get('/gestao-publica/').status_code, 200)

    def test_non_platform_user_cannot_create_municipal_tenant(self):
        with self.assertRaises(PermissionDenied):
            criar_prefeitura_homologacao(
                actor=self.membership.user,
                razao_social='Prefeitura Não Autorizada',
                nome_fantasia='',
                administrador_nome='Usuário',
                administrador_email='unauthorized-prefeitura@example.test',
            )
        self.assertFalse(Organization.objects.filter(razao_social='Prefeitura Não Autorizada').exists())

