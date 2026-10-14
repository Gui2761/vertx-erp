from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
import uuid

from contas.models import Usuario
from platform_core.context import tenant_context
from platform_core.models import (
    ERPCatalog, MembershipERP, Organization, OrganizationERP,
    OrganizationMembership,
)
from operacao.models import Funcionario, JornadaTrabalho

from .models import (
    AcessoRH, CargoMunicipal, DepartamentoMunicipal, FuncaoMunicipal,
    Secretaria, Servidor, SetorMunicipal, UnidadeMunicipal, VinculoFuncional,
)


class MunicipalFixtures(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(slug='lab-assistencia', razao_social='Lab Assistência')
        self.b = Organization.objects.create(slug='lab-loja', razao_social='Lab Loja Hospitalar')
        self.c = Organization.objects.create(slug='lab-prefeitura', razao_social='Lab Prefeitura')
        self.assistencia = ERPCatalog.objects.get_or_create(code='assistencia', defaults={'name': 'ERP Assistência'})[0]
        self.loja = ERPCatalog.objects.get_or_create(code='loja-hospitalar', defaults={'name': 'ERP Loja'})[0]
        self.publico = ERPCatalog.objects.get_or_create(code='gestao-publica', defaults={'name': 'ERP Gestão Pública'})[0]
        for org, erp in ((self.a, self.assistencia), (self.b, self.loja), (self.c, self.publico)):
            OrganizationERP.objects.create(organization=org, erp=erp)
        self.admin_a = self._user('admin-a', self.a, self.assistencia, 'ADMIN')
        self.admin_b = self._user('admin-b', self.b, self.loja, 'ADMIN')
        self.admin_c = self._user('admin-c', self.c, self.publico, 'ADMIN')
        self.server_user = self._user('servidor-c', self.c, self.publico, 'TECNICO')
        with tenant_context(self.c):
            self.access = AcessoRH.objects.create(membership=self.admin_c, papel=AcessoRH.Papel.ADMIN_MUNICIPAL, atribuido_por=self.admin_c.user)
            self.server_access = AcessoRH.objects.create(membership=self.server_user, papel=AcessoRH.Papel.SERVIDOR, atribuido_por=self.admin_c.user)
            self.structure = self._structure(self.c)
            self.server = self._server(self.server_user.user)
        with tenant_context(self.a):
            schedule = JornadaTrabalho.objects.create(nome='Jornada da Assistência', semana={str(i): {'entrada': '08:00', 'saida': '17:00'} for i in range(5)})
            self.assistance_employee = Funcionario.objects.create(
                usuario=self.admin_a.user, matricula='AST-001', nome='Técnico da Assistência', jornada=schedule,
            )
        self.client.force_login(self.admin_c.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()

    def _user(self, username, org, erp, role):
        user = Usuario.objects.create_user(username=username, password='synthetic-only-password')
        membership = OrganizationMembership.objects.create(user=user, organization=org, role=role)
        MembershipERP.objects.create(membership=membership, erp=erp)
        return membership

    def _structure(self, org):
        secretary = Secretaria.objects.create(organization=org, codigo='SEC-01', nome='Secretaria de Saúde')
        department = DepartamentoMunicipal.objects.create(organization=org, secretaria=secretary, codigo='DEP-01', nome='Atenção Básica')
        sector = SetorMunicipal.objects.create(organization=org, departamento=department, codigo='SET-01', nome='Setor Norte')
        unit = UnidadeMunicipal.objects.create(organization=org, setor=sector, codigo='UNI-01', nome='Unidade Central')
        cargo = CargoMunicipal.objects.create(organization=org, codigo='CAR-01', nome='Agente Municipal')
        funcao = FuncaoMunicipal.objects.create(organization=org, codigo='FUN-01', nome='Atendimento')
        vinculo = VinculoFuncional.objects.create(organization=org, codigo='EFETIVO', nome='Efetivo')
        return secretary, department, sector, unit, cargo, funcao, vinculo

    def _server(self, user, matricula='PM-001'):
        secretary, department, sector, unit, cargo, funcao, vinculo = self.structure
        return Servidor.objects.create(
            organization=self.c, usuario=user, matricula=matricula, nome='Servidor Sintético',
            secretaria=secretary, departamento=department, setor=sector, unidade=unit,
            cargo=cargo, funcao=funcao, vinculo=vinculo,
        )


class MunicipalIsolationTests(MunicipalFixtures):
    def test_three_vertical_lab_is_separated(self):
        self.assertEqual(Funcionario.all_objects.filter(organization=self.a, matricula='AST-001').count(), 1)
        with tenant_context(self.c):
            self.assertEqual(Servidor.objects.filter(organization=self.c).count(), 1)
            self.assertEqual(Funcionario.objects.count(), 0)
            self.assertFalse(Servidor.objects.filter(organization=self.a).exists())
            self.assertFalse(Servidor.objects.filter(organization=self.b).exists())
        self.assertFalse(Servidor.all_objects.filter(organization=self.a).exists())
        self.assertFalse(Servidor.all_objects.filter(organization=self.b).exists())

    def test_membership_with_product_access_but_without_municipal_role_is_denied(self):
        no_role = self._user('sem-papel-municipal', self.c, self.publico, 'ADMIN')
        self.client.force_login(no_role.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal:home')).status_code, 403)

    def test_assistance_and_store_users_cannot_enter_public_rh(self):
        for membership in (self.admin_a, self.admin_b):
            self.client.force_login(membership.user)
            session = self.client.session
            session['organization_id'] = membership.organization_id
            session.save()
            self.assertEqual(self.client.get('/gestao-publica/rh/').status_code, 403)

    def test_public_admin_can_access_municipal_home_and_store_only_own_card(self):
        response = self.client.get(reverse('rh_municipal:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gestão de pessoas')

    def test_structure_page_and_org_id_spoof(self):
        self.assertEqual(self.client.get(reverse('rh_municipal:estrutura')).status_code, 200)
        response = self.client.post(reverse('rh_municipal:estrutura_nova', args=['secretaria']), {
            'organization_id': self.a.pk, 'codigo': 'SEC-POST', 'nome': 'Secretaria sintética', 'descricao': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Secretaria.all_objects.filter(organization=self.a, codigo='SEC-POST').exists())
        self.assertTrue(Secretaria.all_objects.filter(organization=self.c, codigo='SEC-POST').exists())

    def test_organization_and_server_id_tampering_are_blocked(self):
        response = self.client.get(reverse('rh_municipal:servidor', args=[self.server.public_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse('rh_municipal:servidor', args=[self._other_org_server_id()])).status_code, 404)
        response = self.client.post(reverse('rh_municipal:servidores'), {
            'organization_id': self.a.pk, 'matricula': 'PM-SPOOF', 'nome': 'Tentativa',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Servidor.all_objects.filter(matricula='PM-SPOOF').exists())

    def _other_org_server_id(self):
        return uuid.uuid4()

    def test_server_portal_is_self_only(self):
        self.client.force_login(self.server_user.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal:portal')).status_code, 200)
        with tenant_context(self.c):
            other = self._server(None, 'PM-002')
        self.assertEqual(self.client.get(reverse('rh_municipal:servidor', args=[other.public_id])).status_code, 403)

    def test_portal_punch_and_request_are_audited_and_idempotent(self):
        self.client.force_login(self.server_user.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        punch_key = uuid.uuid4()
        payload = {'acao': 'ponto', 'tipo': 'ENTRADA', 'request_id': str(punch_key)}
        self.assertEqual(self.client.post(reverse('rh_municipal:portal'), payload).status_code, 302)
        self.assertEqual(self.client.post(reverse('rh_municipal:portal'), payload).status_code, 302)
        from .models import PontoServidor
        self.assertEqual(PontoServidor.all_objects.filter(servidor=self.server).count(), 1)
        request_key = uuid.uuid4()
        self.assertEqual(self.client.post(reverse('rh_municipal:portal'), {
            'acao': 'solicitacao', 'request_id': str(request_key), 'tipo': 'FERIAS', 'descricao': 'Pedido sintético',
        }).status_code, 302)
        from .models import SolicitacaoServidor
        request_row = SolicitacaoServidor.all_objects.get(request_id=request_key)
        self.client.force_login(self.admin_c.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        decision = self.client.post(reverse('rh_municipal:solicitacoes'), {
            'public_id': str(request_row.public_id), 'aprovada': 'true', 'motivo': 'Análise sintética',
        })
        self.assertEqual(decision.status_code, 302)
        request_row.refresh_from_db()
        with tenant_context(self.c):
            self.assertEqual(request_row.status, 'APROVADA')

    def test_membership_permission_cannot_be_granted_across_tenants(self):
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                AcessoRH.objects.create(membership=self.admin_a, papel=AcessoRH.Papel.RH_OPERADOR, atribuido_por=self.admin_c.user)

    def test_public_vertical_cannot_be_enabled_by_changing_form_organization(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError):
                Secretaria.objects.create(organization=self.a, codigo='SPOOF', nome='Tentativa em ERP Assistência')
