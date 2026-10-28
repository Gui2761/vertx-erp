import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from platform_core.models import ERPCatalog, MembershipERP, Organization, OrganizationERP, OrganizationMembership


class EmailOrUsernameLoginTests(TestCase):
    def create_user(self, *, email, password='Synthetic!Pass9321'):
        User = get_user_model()
        return User.objects.create_user(
            username=f'login_{uuid.uuid4().hex[:16]}',
            email=email,
            password=password,
        )

    def test_login_accepts_email_and_existing_username(self):
        user = self.create_user(email=f'{uuid.uuid4().hex}@example.test')
        for identity in (user.email, user.username):
            client = self.client_class()
            response = client.post(reverse('contas:login'), {
                'username': identity,
                'password': 'Synthetic!Pass9321',
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.session.get('_auth_user_id'), str(user.pk))

    def test_duplicate_email_is_rejected_without_selecting_an_account(self):
        email = f'{uuid.uuid4().hex}@example.test'
        self.create_user(email=email)
        self.create_user(email=email)

        client = self.client_class()
        response = client.post(reverse('contas:login'), {
            'username': email,
            'password': 'Synthetic!Pass9321',
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', client.session)


class TenantProductRoutingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username=f'tenant_admin_{uuid.uuid4().hex[:12]}',
            email=f'{uuid.uuid4().hex}@example.test',
            password='Synthetic!Pass9321',
        )
        self.organization = Organization.objects.create(
            slug=f'tenant-{uuid.uuid4().hex[:12]}', razao_social='Tenant Sintético Ltda.',
        )
        self.assistance = ERPCatalog.objects.get(code='assistencia')
        OrganizationERP.objects.create(organization=self.organization, erp=self.assistance, enabled=True)
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, role='ADMIN', status='ATIVO',
        )
        MembershipERP.objects.create(membership=self.membership, erp=self.assistance, enabled=True)

    def test_tenant_admin_single_product_lands_in_erp_and_is_denied_saas_admin(self):
        client = self.client_class()
        response = client.post(reverse('contas:login'), {
            'username': self.user.email,
            'password': 'Synthetic!Pass9321',
        })
        self.assertRedirects(response, '/assistencia/', fetch_redirect_response=False)
        self.assertEqual(client.get('/vertyx/saas/').status_code, 403)

    def test_multiple_products_show_only_tenant_product_selector(self):
        other, _ = ERPCatalog.objects.get_or_create(
            code='gestao-publica',
            defaults={'name': 'VERTYX Gestão Pública', 'active': True},
        )
        OrganizationERP.objects.create(organization=self.organization, erp=other, enabled=True)
        MembershipERP.objects.create(membership=self.membership, erp=other, enabled=True)

        client = self.client_class()
        client.force_login(self.user)
        response = client.get(reverse('platform_core:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'VERTYX Assistência')
        self.assertContains(response, 'VERTYX Gestão Pública')
        self.assertNotContains(response, 'Selecionar organização')
        self.assertNotContains(response, 'Administração da plataforma')
