from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from . import test_saas_admin as fixtures
from .saas_services import convidar_avaliador, reemitir_primeiro_acesso
from .saas_models import PrimeiroAcessoSaaS, AuditoriaSaaS
from .models import Organization, MembershipERP, OrganizationMembership


class RestrictedInvitationTests(TestCase):
    company = fixtures.SaaSAdminTests.company
    admin_data = fixtures.SaaSAdminTests.admin_data
    make_tenant = fixtures.SaaSAdminTests.make_tenant

    def setUp(self):
        fixtures.SaaSAdminTests.setUp(self)
        self.initial = self.make_tenant()
        self.org = self.initial['organization']
        self.owner = self.initial['user']

    def invite(self, suffix='one', role='TECNICO', actor=None, organization=None):
        return convidar_avaliador(actor=actor or self.owner, organization=organization or self.org,
                                 nome='Pessoa Fictícia DEMO', email=f'{suffix}@example.test', role=role)

    def url(self, person):
        return reverse('platform_core:saas_first_access', args=[person['token']])

    def password(self):
        return {'new_password1':'Synthetic!LongPass782', 'new_password2':'Synthetic!LongPass782'}

    def test_restricted_first_access_is_single_use_without_admin_grants(self):
        for role in ('TECNICO', 'FINANCEIRO'):
            person = self.invite(role, role)
            user = person['user']
            self.assertFalse(user.has_usable_password())
            row = PrimeiroAcessoSaaS.objects.get(pk=person['token_id'])
            row.full_clean()
            self.assertNotEqual(row.token_digest, person['token'])
            self.assertEqual(self.client.post(self.url(person), self.password()).status_code, 200)
            self.assertEqual(self.client.post(self.url(person), self.password()).status_code, 410)
            user.refresh_from_db()
            self.assertTrue(user.check_password(self.password()['new_password1']))
            self.assertFalse(user.is_staff or user.is_superuser)
            self.assertEqual(person['membership'].role, role)
            self.client.force_login(user)
            for path in ('/admin/', '/vertyx/saas/', '/contas/usuarios/', '/gestao-publica/saude/prontuarios/', '/gestao-publica/licitacoes/'):
                self.assertIn(self.client.get(path).status_code, (302, 403, 404))
            self.client.logout()
            self.assertTrue(AuditoriaSaaS.objects.filter(action='PRIMEIRO_ACESSO_CONCLUIDO', details__user_id=user.pk).exists())
            self.assertFalse(AuditoriaSaaS.objects.filter(details__icontains=person['token']).exists())

    def test_no_cross_organization_invitation_or_privilege_escalation(self):
        other = Organization.objects.create(slug='other-invite', razao_social='Outra DEMO')
        with self.assertRaises(PermissionDenied):
            self.invite(organization=other)
        person = self.invite()
        with self.assertRaises(PermissionDenied):
            self.invite('forbidden', actor=person['user'])
        for role in ('ADMIN', 'GESTOR', 'SERVIDOR_PUBLICO'):
            with self.assertRaises(ValidationError):
                self.invite(role, role)

    def test_revoked_membership_product_and_user_cannot_redeem(self):
        for revoke in ('membership', 'product', 'user', 'organization'):
            person = self.invite(revoke)
            if revoke == 'membership':
                OrganizationMembership.objects.filter(pk=person['membership'].pk).update(status='BLOQUEADO')
            elif revoke == 'product':
                MembershipERP.objects.filter(membership=person['membership']).update(enabled=False)
            elif revoke == 'user':
                person['user'].is_active=False; person['user'].save(update_fields=['is_active'])
            else:
                self.org.status='SUSPENSA'; self.org.save(update_fields=['status'])
            self.assertEqual(self.client.post(self.url(person), self.password()).status_code, 410)
            person['user'].refresh_from_db()
            self.assertFalse(person['user'].has_usable_password())
            self.org.status='ATIVA'; self.org.save(update_fields=['status'])

    def test_expired_changed_organization_or_existing_password_cannot_redeem(self):
        for mode in ('expired', 'organization', 'password'):
            person=self.invite(mode)
            row=PrimeiroAcessoSaaS.objects.get(pk=person['token_id'])
            if mode=='expired':
                row.expira_em=timezone.now()-timedelta(seconds=1); row.save()
            elif mode=='organization':
                row.organization=Organization.objects.create(slug='tampered',razao_social='Outra DEMO'); row.save()
                with self.assertRaises(ValidationError): row.full_clean()
            else:
                person['user'].set_password('Existing!Synthetic783'); person['user'].save()
            self.assertEqual(self.client.post(self.url(person), self.password()).status_code,410)

    def test_invite_preserves_quota_and_never_reuses_existing_email(self):
        self.plan.limites={'usuarios':2}; self.plan.save()
        person=self.invite()
        with self.assertRaises(ValidationError): self.invite()
        with self.assertRaises(ValidationError): self.invite('third')
        self.assertEqual(self.org.memberships.count(),2)
        self.assertFalse(person['user'].has_usable_password())

    def test_owner_reissue_ignores_newer_evaluator_token(self):
        self.invite()
        result=reemitir_primeiro_acesso(actor=self.platform,organization=self.org)
        self.assertEqual(result['user'].pk,self.owner.pk)

    def test_restricted_invitation_enforces_csrf(self):
        person=self.invite()
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url(person),self.password()).status_code,403)
        self.assertEqual(client.get(self.url(person)).status_code,200)
        data={**self.password(),'csrfmiddlewaretoken':client.cookies['csrftoken'].value}
        self.assertEqual(client.post(self.url(person),data,HTTP_ORIGIN='http://testserver').status_code,200)

    def test_reissue_revokes_old_token_and_cannot_reset_activated_or_foreign_user(self):
        from .saas_services import reemitir_convite_avaliador
        person=self.invite()
        other=Organization.objects.create(slug='other-reissue',razao_social='Outra DEMO')
        with self.assertRaises(PermissionDenied):
            reemitir_convite_avaliador(actor=self.owner,organization=other,user_id=person['user'].pk)
        with self.assertRaises(PermissionDenied):
            reemitir_convite_avaliador(actor=person['user'],organization=self.org,user_id=person['user'].pk)
        new=reemitir_convite_avaliador(actor=self.owner,organization=self.org,user_id=person['user'].pk)
        self.assertEqual(self.client.get(self.url(person)).status_code,410)
        self.assertEqual(self.client.post(self.url(new),self.password()).status_code,200)
        with self.assertRaises(ValidationError):
            reemitir_convite_avaliador(actor=self.owner,organization=self.org,user_id=person['user'].pk)


@override_settings(COMMERCIAL_DEMO_ENABLED=True)
class CommercialDemoTests(TestCase):
    def accounts(self):
        return [{'nome':f'Pessoa DEMO {i}','email':f'demo{i}@example.test'} for i in range(3)]

    def test_demo_seeds_three_scoped_accounts_and_fictitious_operations_once(self):
        from .commercial_demo import preparar_demo
        from .context import tenant_context
        from .modules import has_capability
        from clientes.models import Cliente
        from ordens.models import OrdemServico
        from gestao.models import Contrato, Peca, Lancamento, Orcamento
        from operacao.models import Venda
        org,people=preparar_demo(self.accounts())
        self.assertEqual(org.memberships.count(),3)
        self.assertEqual([p['membership'].role for p in people],['ADMIN','TECNICO','FINANCEIRO'])
        self.assertEqual(list(org.erp_accesses.values_list('erp__code',flat=True)),['assistencia'])
        with tenant_context(org):
            for person in people:
                self.assertFalse(person['user'].is_staff or person['user'].is_superuser)
                self.assertFalse(person['user'].has_usable_password())
                self.assertFalse(has_capability(person['user'],'fiscal_emitir'))
                PrimeiroAcessoSaaS.objects.get(pk=person['token_id']).full_clean()
            self.assertEqual(Cliente.objects.count(),1)
            self.assertEqual(OrdemServico.objects.count(),1)
            self.assertEqual(Contrato.objects.count(),1)
            self.assertEqual(Peca.objects.get().quantidade_atual,9)
            self.assertEqual(Venda.objects.count(),1)
            self.assertGreater(Lancamento.objects.count(),0)
            self.assertEqual(Orcamento.objects.count(),1)
        with self.assertRaises(ValidationError): preparar_demo(self.accounts())
        self.assertEqual(org.memberships.count(),3)

    @override_settings(COMMERCIAL_DEMO_ENABLED=False)
    def test_demo_blocked_outside_homologation(self):
        from .commercial_demo import preparar_demo
        with self.assertRaises(ValidationError): preparar_demo(self.accounts())

    def test_demo_rolls_back_when_an_account_already_exists(self):
        from .commercial_demo import preparar_demo
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user('existing',email='demo1@example.test')
        before=Organization.objects.count()
        with self.assertRaises(ValidationError): preparar_demo(self.accounts())
        self.assertEqual(Organization.objects.count(),before)

    def test_operator_command_checks_identity_and_keeps_invitations_private(self):
        import io, json, tempfile
        from pathlib import Path
        from django.core.management import call_command, CommandError
        from django.db import connection
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'accounts.json'; target=Path(folder)/'links.json'
            source.write_text(json.dumps(self.accounts()),encoding='utf-8')
            options={'accounts_json':str(source),'private_output':str(target),
                     'expected_host':connection.settings_dict['HOST'],
                     'expected_database':connection.settings_dict['NAME'],
                     'confirm_demo_database':True}
            with self.assertRaises(CommandError):
                call_command('prepare_commercial_demo',**{**options,'expected_database':'wrong'})
            self.assertFalse(target.exists())
            output=io.StringIO()
            call_command('prepare_commercial_demo',stdout=output,**options)
            data=json.loads(target.read_text())
            self.assertEqual(len(data['invitations']),3)
            self.assertNotIn('https://',output.getvalue())
            original=target.read_bytes()
            with self.assertRaises(CommandError):
                call_command('prepare_commercial_demo',stdout=output,**options)
            self.assertEqual(target.read_bytes(),original)
