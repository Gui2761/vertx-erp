import json
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from platform_core.context import tenant_context
from platform_core.models import (
    MembershipERP, ModuloOrganizacao, OrganizationERP, OrganizationMembership, PlatformAudit,
)

from .models import (
    AcessoMunicipal, ConviteMunicipal, DepartamentoMunicipal, PermissaoMunicipal,
    Secretaria, Servidor, SetorMunicipal, UnidadeMunicipal,
)
from .public_services import (
    INITIAL_SECRETARY_CATALOG, assign_municipal_access, create_municipal_invite, has_municipal_permission,
    scoped_queryset,
)
from .tests import MunicipalFixtures


class PublicCoreTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        with tenant_context(self.c):
            self.prefeitura_admin = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )

    def _membership(self, username, role='SERVIDOR_PUBLICO'):
        user = type(self.admin_c.user).objects.create_user(
            username=username, email=f'{username}@example.test', password='synthetic-only-password',
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=self.c, role=role,
            status=OrganizationMembership.Status.ACTIVE,
        )
        MembershipERP.objects.create(membership=membership, erp=self.publico, enabled=True)
        return membership

    def _as(self, membership):
        self.client.force_login(membership.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()

    def test_membership_admin_is_not_implicitly_municipal_admin(self):
        self.client.force_login(self.server_user.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:home')).status_code, 403)

    def test_tenant_admin_is_not_platform_saas_admin(self):
        self.assertEqual(self.client.get('/vertyx/saas/').status_code, 403)

    def test_prefeitura_admin_can_open_home_and_manage_profile(self):
        response = self.client.get(reverse('rh_municipal_public:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gestão Pública')
        self.assertEqual(self.client.get(reverse('rh_municipal_public:profile')).status_code, 200)
        self.assertContains(response, 'Módulos da Prefeitura')

    def test_department_scope_hides_other_secretariat_and_access(self):
        with tenant_context(self.c):
            other_secretary = Secretaria.objects.create(
                organization=self.c, codigo='SEC-02', nome='Secretaria Sigilosa',
            )
            other_department = DepartamentoMunicipal.objects.create(
                organization=self.c, secretaria=other_secretary, codigo='DEP-02', nome='Outro departamento',
            )
            other_sector = SetorMunicipal.objects.create(
                organization=self.c, departamento=other_department, codigo='SET-02', nome='Outro setor',
            )
            other_unit = UnidadeMunicipal.objects.create(
                organization=self.c, setor=other_sector, codigo='UNI-02', nome='Outra unidade',
            )
        target = self._membership('gestor-departamento')
        with tenant_context(self.c):
            scoped = assign_municipal_access(
                self.admin_c.user, membership=target, papel=AcessoMunicipal.Papel.GESTOR_DEPARTAMENTO,
                escopo=AcessoMunicipal.Escopo.DEPARTAMENTO, secretaria=None,
                departamento=self.structure[1], permissions={'dashboard.view', 'access.view'},
            )
            other_access_membership = self._membership('usuario-fora-escopo')
            other_access = AcessoMunicipal.objects.create(
                membership=other_access_membership, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=other_unit,
                atribuido_por=self.admin_c.user,
            )
        self._as(target)
        home = self.client.get(reverse('rh_municipal_public:home'))
        self.assertEqual(home.status_code, 200)
        self.assertNotContains(home, 'Secretaria Sigilosa')
        access_page = self.client.get(reverse('rh_municipal_public:accesses'))
        self.assertEqual(access_page.status_code, 200)
        self.assertNotContains(access_page, 'usuario-fora-escopo')
        denied = self.client.post(reverse('rh_municipal_public:access_revoke', args=[other_access.pk]))
        self.assertEqual(denied.status_code, 403)
        other_access.refresh_from_db()
        self.assertTrue(other_access.ativo)
        with tenant_context(self.c):
            self.assertTrue(scoped_queryset(target.user, Servidor.objects.all()).exists())

    def test_professional_needs_explicit_permission_and_cannot_manage_access(self):
        professional = self._membership('profissional')
        with tenant_context(self.c):
            access = AcessoMunicipal.objects.create(
                membership=professional, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='dashboard.view')
        self._as(professional)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:accesses')).status_code, 403)
        self.assertFalse(has_municipal_permission(professional.user, 'access.manage'))

    def test_structure_create_reuses_existing_tenant_models_and_audits(self):
        response = self.client.post(reverse('rh_municipal_public:structure'), {
            'tipo': 'secretaria', 'codigo': 'SEC-NOVA', 'nome': 'Secretaria de Teste', 'descricao': 'Cadastro sintético',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Secretaria.all_objects.filter(organization=self.c, codigo='SEC-NOVA').exists())
        self.assertTrue(PlatformAudit.objects.filter(action='ESTRUTURA_MUNICIPAL_CRIADA').exists())
        self.assertFalse(Secretaria.all_objects.filter(organization=self.a, codigo='SEC-NOVA').exists())

    def test_initial_secretariat_catalog_is_inactive_idempotent_and_tenant_scoped(self):
        url = reverse('rh_municipal_public:structure') + '?tipo=secretaria'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(url), 'Adicionar catálogo inicial')
        response = self.client.post(url, {'tipo': 'secretaria', 'acao': 'catalogo_inicial'})
        self.assertEqual(response.status_code, 302)
        rows = list(Secretaria.all_objects.filter(organization=self.c).order_by('codigo'))
        catalog_codes = {code for code, _ in INITIAL_SECRETARY_CATALOG}
        seeded = [row for row in rows if row.codigo in catalog_codes]
        self.assertEqual(len(seeded), 16)
        self.assertTrue(all(not row.ativo for row in seeded))
        self.assertEqual(len(rows), 17)  # SEC-01 from the shared municipal fixture remains untouched.
        self.assertTrue(next(row for row in rows if row.codigo == 'SEC-01').ativo)
        self.assertEqual(Secretaria.all_objects.filter(organization=self.a).count(), 0)
        audit_count = PlatformAudit.objects.filter(
            organization=self.c, action='SECRETARIA_CATALOGO_INICIAL_ADICIONADA',
        ).count()
        self.assertEqual(audit_count, 16)

        response = self.client.post(url, {'tipo': 'secretaria', 'acao': 'catalogo_inicial'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Secretaria.all_objects.filter(organization=self.c).count(), 17)
        self.assertEqual(PlatformAudit.objects.filter(
            organization=self.c, action='SECRETARIA_CATALOGO_INICIAL_ADICIONADA',
        ).count(), audit_count)

    def test_prefeitura_admin_can_rename_activate_and_deactivate_without_deleting_history(self):
        with tenant_context(self.c):
            secretary = Secretaria.objects.create(
                organization=self.c, codigo='SEC-OBRAS', nome='Obras', ativo=False,
            )
            department = DepartamentoMunicipal.objects.create(
                organization=self.c, secretaria=secretary, codigo='DEP-OBRAS', nome='Infraestrutura',
            )
        url = reverse('rh_municipal_public:structure') + '?tipo=secretaria'
        payload = {
            'tipo': 'secretaria', 'acao': 'renomear_secretaria',
            'secretaria_id': str(secretary.pk),
            f'secretaria-{secretary.pk}-codigo': 'SEC-OBRAS-INFRA',
            f'secretaria-{secretary.pk}-nome': 'Obras e Infraestrutura',
            f'secretaria-{secretary.pk}-descricao': 'Secretaria municipal',
        }
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        secretary.refresh_from_db()
        self.assertEqual(secretary.nome, 'Obras e Infraestrutura')
        self.assertFalse(secretary.ativo)

        toggle = {
            'tipo': 'secretaria', 'acao': 'alternar_secretaria',
            'secretaria_id': str(secretary.pk), 'ativo': 'true',
        }
        self.assertEqual(self.client.post(url, toggle).status_code, 302)
        secretary.refresh_from_db()
        self.assertTrue(secretary.ativo)
        self.assertEqual(self.client.post(url, {**toggle, 'ativo': 'false'}).status_code, 302)
        secretary.refresh_from_db()
        department.refresh_from_db()
        self.assertFalse(secretary.ativo)
        self.assertTrue(department.ativo)
        self.assertEqual(department.secretaria_id, secretary.pk)
        self.assertTrue(PlatformAudit.objects.filter(
            organization=self.c,
            action__in={'SECRETARIA_ATUALIZADA', 'SECRETARIA_ATIVADA', 'SECRETARIA_DESATIVADA'},
        ).exists())

    def test_secretariat_catalog_cannot_be_changed_outside_tenant_or_by_scoped_manager(self):
        with tenant_context(self.a):
            OrganizationERP.objects.get_or_create(organization=self.a, erp=self.publico)
            foreign = Secretaria.objects.create(
                organization=self.a, codigo='SEC-FOREIGN', nome='Secretaria alheia', ativo=False,
            )
        url = reverse('rh_municipal_public:structure') + '?tipo=secretaria'
        response = self.client.post(url, {
            'tipo': 'secretaria', 'acao': 'alternar_secretaria',
            'secretaria_id': str(foreign.pk), 'ativo': 'true',
        })
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.ativo)

        manager = self._membership('catalog-scoped-manager')
        with tenant_context(self.c):
            AcessoMunicipal.objects.create(
                membership=manager, papel=AcessoMunicipal.Papel.ADMIN_SECRETARIA,
                escopo=AcessoMunicipal.Escopo.SECRETARIA, secretaria=self.structure[0],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(
                acesso=AcessoMunicipal.objects.get(membership=manager),
                capacidade='structure.manage',
            )
        self._as(manager)
        denied = self.client.post(url, {'tipo': 'secretaria', 'acao': 'catalogo_inicial'})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(Secretaria.all_objects.filter(organization=self.c).count(), 1)

    def test_secretary_admin_can_create_only_inside_its_scope(self):
        manager = self._membership('secretary-admin')
        with tenant_context(self.c):
            other_secretary = Secretaria.objects.create(
                organization=self.c, codigo='SEC-FORA', nome='Secretaria Fora do Escopo',
            )
            access = AcessoMunicipal.objects.create(
                membership=manager, papel=AcessoMunicipal.Papel.ADMIN_SECRETARIA,
                escopo=AcessoMunicipal.Escopo.SECRETARIA, secretaria=self.structure[0],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='structure.manage')
        self._as(manager)
        allowed = self.client.post(reverse('rh_municipal_public:structure') + '?tipo=departamento', {
            'tipo': 'departamento', 'codigo': 'DEP-NOVO', 'nome': 'Novo departamento',
            'descricao': '', 'secretaria': str(self.structure[0].pk),
        })
        self.assertEqual(allowed.status_code, 302)
        self.assertTrue(DepartamentoMunicipal.all_objects.filter(secretaria=self.structure[0], codigo='DEP-NOVO').exists())
        denied = self.client.post(reverse('rh_municipal_public:structure') + '?tipo=departamento', {
            'tipo': 'departamento', 'codigo': 'DEP-INVASAO', 'nome': 'Não autorizado',
            'descricao': '', 'secretaria': str(other_secretary.pk),
        })
        self.assertNotEqual(denied.status_code, 302)
        self.assertFalse(DepartamentoMunicipal.all_objects.filter(organization=self.c, codigo='DEP-INVASAO').exists())

    def test_product_and_module_are_checked_on_backend(self):
        with tenant_context(self.c):
            ModuloOrganizacao.objects.create(
                organization=self.c, codigo='gestao_publica', habilitado=False,
            )
        response = self.client.get(reverse('rh_municipal_public:home'))
        self.assertEqual(response.status_code, 403)
        with tenant_context(self.a):
            self.assertFalse(has_municipal_permission(self.admin_c.user, 'dashboard.view'))

    def test_foreign_organization_cannot_open_public_management_or_revoke(self):
        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:home')).status_code, 403)
        self.assertEqual(self.client.post(reverse(
            'rh_municipal_public:access_revoke', args=[self.prefeitura_admin.pk],
        )).status_code, 403)
        self.prefeitura_admin.refresh_from_db()
        self.assertTrue(self.prefeitura_admin.ativo)

    def test_secretary_manager_cannot_grant_permissions_the_actor_does_not_have(self):
        manager = self._membership('admin-secretaria')
        with tenant_context(self.c):
            access = AcessoMunicipal.objects.create(
                membership=manager, papel=AcessoMunicipal.Papel.ADMIN_SECRETARIA,
                escopo=AcessoMunicipal.Escopo.SECRETARIA, secretaria=self.structure[0],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='access.manage')
            target = self._membership('novo-gestor')
            with self.assertRaises(PermissionDenied):
                assign_municipal_access(
                    manager.user, membership=target, papel=AcessoMunicipal.Papel.GESTOR_DEPARTAMENTO,
                    escopo=AcessoMunicipal.Escopo.DEPARTAMENTO, departamento=self.structure[1],
                    permissions={'dashboard.view'},
                )

    def test_invitation_hash_expiry_revoke_and_one_time_acceptance(self):
        with tenant_context(self.c):
            invite, token = create_municipal_invite(self.admin_c.user, data={
                'email': 'convidado@example.test', 'papel': AcessoMunicipal.Papel.PROFISSIONAL,
                'escopo': AcessoMunicipal.Escopo.UNIDADE, 'unidade': self.structure[3],
                'permissoes': ['dashboard.view'],
            })
        self.assertNotEqual(invite.token_digest, token)
        self.assertEqual(invite.token_digest, ConviteMunicipal.digest(token))
        self.assertTrue(invite.valido)
        self.assertGreater(invite.expira_em, timezone.now() + timedelta(hours=47))

        self.client.logout()
        url = reverse('rh_municipal_public:invite_accept', args=[token])
        payload = {
            'email': 'convidado@example.test', 'username': 'servidor-convidado',
            'first_name': 'Servidor', 'last_name': 'Convidado',
            'password1': 'Synthetic-Strong-Password!28',
            'password2': 'Synthetic-Strong-Password!28',
        }
        accepted = self.client.post(url, payload)
        self.assertEqual(accepted.status_code, 200)
        self.assertContains(accepted, 'Cadastro concluído')
        invite.refresh_from_db()
        self.assertIsNotNone(invite.usado_em)
        user = type(self.admin_c.user).objects.get(username='servidor-convidado')
        membership = OrganizationMembership.objects.get(user=user, organization=self.c)
        self.assertEqual(membership.role, 'SERVIDOR_PUBLICO')
        self.assertEqual(user.perfil, 'SERVIDOR_PUBLICO')
        self.assertTrue(AcessoMunicipal.all_objects.filter(membership=membership, papel='PROFISSIONAL', ativo=True).exists())
        duplicate = self.client.post(url, payload)
        self.assertEqual(duplicate.status_code, 404)

    def test_invite_revoke_is_audited_and_token_stops_working(self):
        with tenant_context(self.c):
            invite, token = create_municipal_invite(self.admin_c.user, data={
                'email': 'revogado@example.test', 'papel': AcessoMunicipal.Papel.PROFISSIONAL,
                'escopo': AcessoMunicipal.Escopo.UNIDADE, 'unidade': self.structure[3],
                'permissoes': [],
            })
        response = self.client.post(reverse('rh_municipal_public:invite_revoke', args=[invite.pk]))
        self.assertEqual(response.status_code, 302)
        invite.refresh_from_db()
        self.assertIsNotNone(invite.revogado_em)
        self.assertTrue(PlatformAudit.objects.filter(action='CONVITE_MUNICIPAL_REVOGADO').exists())
        self.client.logout()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:invite_accept', args=[token])).status_code, 404)

    def test_expired_invitation_cannot_be_accepted(self):
        with tenant_context(self.c):
            invite, token = create_municipal_invite(self.admin_c.user, data={
                'email': 'expirado@example.test', 'papel': AcessoMunicipal.Papel.PROFISSIONAL,
                'escopo': AcessoMunicipal.Escopo.UNIDADE, 'unidade': self.structure[3],
                'permissoes': [],
            })
            invite.expira_em = timezone.now() - timedelta(minutes=1)
            invite.save(update_fields=['expira_em'])
        self.client.logout()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:invite_accept', args=[token])).status_code, 404)

    def test_pwa_manifest_and_worker_do_not_cache_authenticated_pages(self):
        manifest = self.client.get(reverse('rh_municipal_public:manifest'))
        self.assertEqual(manifest.status_code, 200)
        data = json.loads(manifest.content)
        self.assertEqual(data['start_url'], '/gestao-publica/')
        self.assertEqual(data['scope'], '/gestao-publica/')
        worker = self.client.get(reverse('rh_municipal_public:worker'))
        self.assertEqual(worker.status_code, 200)
        self.assertContains(worker, 'Network-only by design')
        self.assertContains(worker, "fetch(request, { cache: 'no-store' })")

