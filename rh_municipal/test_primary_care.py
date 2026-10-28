import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, OrganizationERP
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS
from . import phase_g_models as health
from . import phase_g_services as health_svc
from . import primary_care_services as svc
from .models import AcessoMunicipal, PermissaoMunicipal, UnidadeMunicipal
from .primary_care_forms import PrimaryFamilyForm
from .tests import MunicipalFixtures


class PrimaryCareTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.health_module = ERPProductModule.objects.get(erp=self.publico, code='saude_sus')
        self.plan = PlanoSaaS.objects.create(slug='ubs-plan', nome='UBS sintética', erp=self.publico)
        for code in ('saude_sus', 'gestao_publica'):
            PlanoProdutoModulo.objects.create(plano=self.plan, modulo=ERPProductModule.objects.get(erp=self.publico, code=code))
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status='ATIVA')
        with tenant_context(self.c):
            self.access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel='ADMIN_PREFEITURA', escopo='PREFEITURA',
                atribuido_por=self.admin_c.user,
            )
            self.unit = health_svc.configure_health_unit(self.admin_c.user, data={'unidade': self.structure[3], 'tipo': 'UBS'})
            second = UnidadeMunicipal.objects.create(organization=self.c, setor=self.structure[2], codigo='UBS-02', nome='UBS Fora do Escopo')
            self.other_unit = health_svc.configure_health_unit(self.admin_c.user, data={'unidade': second, 'tipo': 'UBS'})
            self.team = health_svc.configure_health_team(self.admin_c.user, data={
                'codigo': 'ESF-UBS', 'nome': 'Equipe UBS', 'tipo': 'ESF', 'unidade_saude': self.unit, 'microarea': '01',
            })
        self.url = reverse('rh_municipal_public:saude_primary')

    def family(self, code='F-001', unit=None, team=None):
        return svc.create_family(self.admin_c.user, data={
            'codigo': code, 'endereco': 'ENDERECO_RESTRITO', 'unidade_saude': unit or self.unit,
            'equipe': team, 'microarea': '',
        })

    def citizen(self, name='NOME_PACIENTE_RESTRITO', unit=None):
        return health_svc.create_patient(self.admin_c.user, data={
            'nome': name, 'unidade': (unit or self.unit).unidade,
            'cpf': f'{health.CidadaoSaudeMunicipal.objects.count() + 1:011d}',
        })

    def scoped_actor(self, capabilities):
        access = AcessoMunicipal.objects.create(
            membership=self.server_user, papel='PROFISSIONAL', escopo='UNIDADE',
            unidade=self.unit.unidade, atribuido_por=self.admin_c.user,
        )
        for capability in capabilities:
            PermissaoMunicipal.objects.create(acesso=access, capacidade=capability, permitido=True)
        return access

    def test_family_reuses_existing_model_hierarchy_and_private_audit(self):
        with tenant_context(self.c):
            family = self.family(team=self.team)
            self.assertEqual(family.microarea, '01')
            self.assertEqual(family.unidade_id, self.unit.unidade_id)
            self.assertEqual(family.secretaria_id, self.structure[0].pk)
            audit = health.AuditoriaAcessoSaude.objects.get(acao='FAMILIA_UBS_CADASTRADA')
            self.assertNotIn('ENDERECO_RESTRITO', str(audit.detalhes))
            self.assertEqual(audit.entidade_id, family.pk)

    def test_invalid_team_microarea_and_inactive_unit_are_rejected(self):
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                self.family(unit=self.other_unit, team=self.team)
            with self.assertRaises(ValidationError):
                svc.create_family(self.admin_c.user, data={'codigo': 'F', 'endereco': 'Rua', 'unidade_saude': self.unit,
                                                          'equipe': self.team, 'microarea': '99'})
            self.unit.ativo = False
            self.unit.save()
            with self.assertRaises(PermissionDenied):
                self.family()
            self.assertFalse(health.FamiliaTerritorialSaude.objects.exists())

    def test_member_enrollment_is_audited_idempotent_and_preserves_payload(self):
        with tenant_context(self.c):
            family, citizen = self.family(), self.citizen()
            args = dict(family_id=family.pk, citizen_public_id=citizen.public_id, relationship='Filho', reference=True)
            member = svc.link_family_member(self.admin_c.user, **args)
            self.assertEqual(svc.link_family_member(self.admin_c.user, **args).pk, member.pk)
            self.assertEqual(health.AuditoriaAcessoSaude.objects.filter(acao='VINCULO_FAMILIAR_UBS_CRIADO').count(), 1)
            with self.assertRaises(ValidationError):
                svc.link_family_member(self.admin_c.user, **{**args, 'relationship': 'Outro'})

    def test_duplicate_active_family_and_second_reference_are_rejected(self):
        with tenant_context(self.c):
            family, second = self.family(), self.family('F-002')
            citizen = self.citizen()
            svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_public_id=citizen.public_id, reference=True)
            with self.assertRaises(ValidationError):
                svc.link_family_member(self.admin_c.user, family_id=second.pk, citizen_public_id=citizen.public_id)
            another = self.citizen('Outro cidadão')
            with self.assertRaises(ValidationError):
                svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_public_id=another.public_id, reference=True)

    def test_patient_must_be_active_and_have_matching_reference_unit(self):
        with tenant_context(self.c):
            family, citizen = self.family(), self.citizen(unit=self.other_unit)
            with self.assertRaises(ValidationError):
                svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_public_id=citizen.public_id)
            citizen.situacao = 'INATIVO'
            citizen.save()
            with self.assertRaises(PermissionDenied):
                svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_public_id=citizen.public_id)

    def test_aggregate_page_never_exposes_patient_or_household_data_and_is_audited(self):
        with tenant_context(self.c):
            family, citizen = self.family(team=self.team), self.citizen()
            svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_public_id=citizen.public_id)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Atenção Básica / UBS')
        self.assertNotContains(response, 'ENDERECO_RESTRITO')
        self.assertNotContains(response, 'NOME_PACIENTE_RESTRITO')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(next(row for row in response.context['primary_rows'] if row['pk'] == self.unit.pk)['families'], 1)
        with tenant_context(self.c):
            self.assertTrue(health.AuditoriaAcessoSaude.objects.filter(acao='ATENCAO_BASICA_CONSULTADA').exists())

    def test_real_forms_create_family_and_link_member(self):
        response = self.client.post(self.url, {'action': 'family', 'family-codigo': 'FORM-1',
            'family-unidade_saude': self.unit.pk, 'family-endereco': 'ENDERECO_RESTRITO',
            'family-equipe': self.team.pk, 'family-microarea': '01'})
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.c):
            family = health.FamiliaTerritorialSaude.objects.get(codigo='FORM-1')
            citizen = self.citizen()
        response = self.client.post(self.url, {'action': 'member', 'member-familia': family.pk,
            'member-cidadao': citizen.cpf, 'member-parentesco': 'Filho'})
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.c):
            self.assertEqual(family.membros.count(), 1)

    def test_scoped_read_only_access_cannot_mutate_or_select_other_unit(self):
        with tenant_context(self.c):
            self.scoped_actor(['saude.primary.view'])
        self.client.force_login(self.server_user.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'UBS Fora do Escopo')
        self.assertNotContains(response, 'Cadastrar família na UBS')
        self.assertEqual(self.client.post(self.url, {'action': 'family'}).status_code, 403)
        with tenant_context(self.c):
            with self.assertRaises(PermissionDenied):
                svc.primary_overview(self.server_user.user, unit_id=self.other_unit.pk)
        response = self.client.get(self.url, {'unidade': self.other_unit.pk})
        self.assertEqual(response.context['primary_rows'], [])

    def test_unrelated_broad_access_does_not_expand_primary_permission_scope(self):
        with tenant_context(self.c):
            self.scoped_actor(['saude.primary.manage'])
            broad = AcessoMunicipal.objects.create(
                membership=self.server_user, papel='ADMIN_SECRETARIA', escopo='SECRETARIA',
                secretaria=self.structure[0], atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=broad, capacidade='saude.units.view', permitido=True)
            form = PrimaryFamilyForm(actor=self.server_user.user)
            self.assertEqual(list(form.fields['unidade_saude'].queryset), [self.unit])
            with self.assertRaises(PermissionDenied):
                svc.create_family(self.server_user.user, data={'codigo': 'NO', 'endereco': 'Rua', 'unidade_saude': self.other_unit})

    def test_member_requires_independent_patient_read_permission(self):
        with tenant_context(self.c):
            access = self.scoped_actor(['saude.primary.manage'])
            family, citizen = self.family(), self.citizen()
            with self.assertRaises(PermissionDenied):
                svc.link_family_member(self.server_user.user, family_id=family.pk, citizen_public_id=citizen.public_id)
            PermissaoMunicipal.objects.create(acesso=access, capacidade='saude.patients.view', permitido=True)
            svc.link_family_member(self.server_user.user, family_id=family.pk, citizen_public_id=citizen.public_id)

    def test_other_tenant_and_missing_context_cannot_access_existing_records(self):
        with tenant_context(self.c):
            family, citizen = self.family(), self.citizen()
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied):
                svc.link_family_member(self.admin_a.user, family_id=family.pk, citizen_public_id=citizen.public_id)
            with self.assertRaises(PermissionDenied):
                svc.create_family(self.admin_c.user, data={'codigo': 'NO', 'endereco': 'Rua', 'unidade_saude': self.unit})
        with self.assertRaises(PermissionDenied):
            svc.primary_overview(self.admin_c.user)

    def test_module_revoked_and_anonymous_access_fail_closed(self):
        self.assertEqual(Client().get(self.url).status_code, 302)
        PlanoProdutoModulo.objects.filter(plano=self.plan, modulo=self.health_module).delete()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_unit_filter_loads_only_matching_teams_and_invalid_document_does_not_write(self):
        response = self.client.get(self.url, {'unidade': self.unit.pk})
        self.assertContains(response, 'ESF-UBS')
        response = self.client.post(self.url, {'action': 'member', 'member-familia': '999', 'member-cidadao': 'invalid'})
        self.assertEqual(response.status_code, 200)
        with tenant_context(self.c):
            self.assertFalse(health.VinculoFamiliaSaude.objects.exists())

    def test_unknown_citizen_is_rejected_without_creating_a_record(self):
        with tenant_context(self.c):
            family = self.family()
            with self.assertRaises(PermissionDenied):
                svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_public_id=uuid.uuid4())
            self.assertFalse(health.VinculoFamiliaSaude.objects.exists())

    def test_cross_tenant_ids_are_denied_even_with_health_enabled_in_both_tenants(self):
        OrganizationERP.objects.create(organization=self.b, erp=self.publico)
        other_admin = self._user('ubs-other-prefeitura', self.b, self.publico, 'ADMIN')
        AssinaturaSaaS.objects.create(organization=self.b, plano=self.plan, status='ATIVA')
        with tenant_context(self.b):
            AcessoMunicipal.objects.create(membership=other_admin, papel='ADMIN_PREFEITURA',
                                          escopo='PREFEITURA', atribuido_por=other_admin.user)
            structure = self._structure(self.b)
            other_unit = health_svc.configure_health_unit(other_admin.user, data={'unidade': structure[3], 'tipo': 'UBS'})
            other_citizen = health_svc.create_patient(other_admin.user, data={'nome': 'OUTRA_PREFEITURA_PRIVADO', 'unidade': structure[3]})
        with tenant_context(self.c):
            family = self.family()
            with self.assertRaises(PermissionDenied):
                svc.primary_overview(self.admin_c.user, unit_id=other_unit.pk)
            with self.assertRaises(PermissionDenied):
                svc.create_family(self.admin_c.user, data={'codigo': 'NO', 'endereco': 'Rua', 'unidade_saude': other_unit})
            with self.assertRaises(PermissionDenied):
                svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_public_id=other_citizen.public_id)

    def test_cns_lookup_works_and_duplicate_family_does_not_write_a_second_audit(self):
        with tenant_context(self.c):
            family, citizen = self.family(), self.citizen()
            citizen.cns = '000000000000001'
            citizen.save()
            member = svc.link_family_member(self.admin_c.user, family_id=family.pk, citizen_document=citizen.cns)
            self.assertEqual(member.cidadao_id, citizen.pk)
            with self.assertRaises(ValidationError):
                self.family()
            self.assertEqual(health.AuditoriaAcessoSaude.objects.filter(acao='FAMILIA_UBS_CADASTRADA').count(), 1)
