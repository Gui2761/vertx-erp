from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from django.urls import reverse
from platform_core.context import tenant_context
from platform_core.models import ModuloOrganizacao, PermissaoMembership, OrganizationMembership, FilialEmpresa, ConfiguracaoEmpresa
from platform_core.modules import has_capability
from gestao import services as gs
from .test_block2 import Block2Fixtures

class FoundationTests(Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()

    def test_module_disabled_blocks_route_and_stock_service(self):
        with tenant_context(self.a):
            ModuloOrganizacao.objects.create(codigo='estoque',habilitado=False)
            with self.assertRaises(PermissionDenied):
                gs.movimentar(self.admin,self.part.pk,'ENTRADA',1)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/estoque/').status_code,403)
        with tenant_context(self.b):
            self.assertTrue(has_capability(self.admin_b,'estoque'))

    def test_capability_comes_from_active_membership_not_global_profile(self):
        user=self.user('operador-b3',self.a,'PDV')
        with tenant_context(self.a):
            self.assertTrue(has_capability(user,'pdv'))
            self.assertFalse(has_capability(user,'financeiro_escrever'))
            membership=OrganizationMembership.objects.get(user=user,organization=self.a)
            PermissaoMembership.objects.create(membership=membership,capacidade='pdv',permitido=False)
            self.assertFalse(has_capability(user,'pdv'))

    def test_permission_relationship_cannot_cross_tenant(self):
        with tenant_context(self.a):
            foreign=OrganizationMembership.objects.get(user=self.admin_b,organization=self.b)
            with self.assertRaises(ValidationError):
                PermissaoMembership.objects.create(membership=foreign,capacidade='pdv',permitido=True)

    def test_own_company_branches_are_not_customer_units_and_idor_denied(self):
        with tenant_context(self.a):
            branch=FilialEmpresa.objects.create(codigo='MATRIZ',nome='Filial própria')
            self.assertFalse(hasattr(branch,'cliente'))
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(reverse('platform_core:filial_editar',args=[branch.public_id])).status_code,404)

    def test_company_configuration_is_per_organization_without_fiscal_assumptions(self):
        with tenant_context(self.a):
            config=ConfiguracaoEmpresa.objects.create(limites={'usuarios':10})
            self.assertEqual(config.crt,'')
            with self.assertRaises(ValidationError):
                config.limites={'usuarios':-1};config.save()
        with tenant_context(self.b):
            self.assertFalse(ConfiguracaoEmpresa.objects.exists())

    def test_new_roles_do_not_receive_company_admin_access(self):
        user=self.user('rh-b3',self.a,'RH')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('platform_core:empresa')).status_code,403)
