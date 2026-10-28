import uuid
from datetime import date, timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, ModuloOrganizacao, OrganizationERP
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS
from . import phase_i_models as m
from . import phase_i_services as svc
from .models import AcessoMunicipal, PermissaoMunicipal, Servidor
from .tests import MunicipalFixtures


class MunicipalPhaseITests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.governance = ERPProductModule.objects.get_or_create(
            erp=self.publico, code=m.GOVERNANCE_MODULE,
            defaults={'name': 'Controle Interno', 'active': True, 'sort_order': 150},
        )[0]
        self.gp = ERPProductModule.objects.get_or_create(
            erp=self.publico, code='gestao_publica',
            defaults={'name': 'Gestão Pública', 'active': True, 'sort_order': 1},
        )[0]
        self.plan = PlanoSaaS.objects.create(
            slug=f'phase-i-{uuid.uuid4().hex[:8]}', nome='Plano sintético Controle Interno',
            erp=self.publico, modulos=[],
        )
        PlanoProdutoModulo.objects.get_or_create(plano=self.plan, modulo=self.gp)
        PlanoProdutoModulo.objects.get_or_create(plano=self.plan, modulo=self.governance)
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )

    def _risk(self, code='R-001', title='Risco sintético'):
        with tenant_context(self.c):
            return svc.create_risk(self.admin_c.user, data={
                'codigo': code, 'titulo': title, 'descricao': 'Descrição de teste',
                'categoria': 'Operacional', 'probabilidade': 3, 'impacto': 4,
                'responsavel': self.server, 'secretaria': self.structure[0],
                'departamento': self.structure[1], 'setor': self.structure[2],
                'unidade': self.structure[3],
            })

    def test_module_entitlement_and_url_require_module_permission_and_tenant(self):
        self.assertEqual(self.client.get(reverse('rh_municipal_public:governance_home')).status_code, 200)
        PlanoProdutoModulo.objects.filter(plano=self.plan, modulo=self.governance).delete()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:governance_home')).status_code, 403)
        with tenant_context(self.c):
            with self.assertRaises(PermissionDenied):
                self._risk()
        self.assertFalse(ModuloOrganizacao.objects.filter(organization=self.c, codigo=m.GOVERNANCE_MODULE).exists())

    def test_risk_finding_recommendation_action_plan_and_audit_workflow(self):
        with tenant_context(self.c):
            risk = self._risk()
            control = m.ControleInternoMunicipal.objects.create(
                organization=self.c, codigo='C-1', titulo='Conferência mensal',
                descricao='Verificar conciliação', risco=risk, responsavel=self.server,
                criado_por=self.admin_c.user, frequencia='MENSAL',
            )
            finding = svc.create_finding(self.admin_c.user, data={
                'codigo': 'A-1', 'titulo': 'Achado sintético', 'descricao': 'Descrição do achado',
                'origem': 'Revisão interna', 'risco': risk, 'controle': control,
                'severidade': m.AchadoControleInterno.Severidade.MODERADA,
                'prazo': date.today() + timedelta(days=20), 'responsavel': self.server,
            })
            recommendation = svc.create_recommendation(self.admin_c.user, finding_id=finding.pk, text='Documentar a conferência.')
            plan = svc.create_action_plan(self.admin_c.user, recommendation_id=recommendation.pk, data={
                'titulo': 'Formalizar conferência', 'descricao': 'Criar evidência mensal',
                'responsavel': self.server, 'prazo': date.today() + timedelta(days=10),
            })
            svc.update_action_plan(self.admin_c.user, plan_id=plan.pk, status=m.PlanoAcaoInterno.Status.EM_ANDAMENTO, description='Iniciado')
            svc.update_action_plan(self.admin_c.user, plan_id=plan.pk, status=m.PlanoAcaoInterno.Status.AGUARDANDO_VALIDACAO, description='Concluído pelo responsável')
            svc.update_action_plan(self.admin_c.user, plan_id=plan.pk, status=m.PlanoAcaoInterno.Status.CONCLUIDO, description='Validado', approve=True)
            plan.refresh_from_db()
            finding.refresh_from_db()
            self.assertEqual(plan.status, m.PlanoAcaoInterno.Status.CONCLUIDO)
            self.assertIsNotNone(plan.concluido_em)
            self.assertEqual(finding.status, m.AchadoControleInterno.Status.EM_ACAO)
            self.assertEqual(plan.historico.count(), 3)
            self.assertGreaterEqual(m.EventoControleInterno.objects.count(), 7)
            svc.close_finding(self.admin_c.user, finding_id=finding.pk, reason='Ação validada pelo responsável autorizado.')
            finding.refresh_from_db()
            self.assertEqual(finding.status, m.AchadoControleInterno.Status.ENCERRADO)

    def test_scope_and_cross_tenant_references_are_denied(self):
        with tenant_context(self.c):
            risk = self._risk()
            control = svc.create_control(self.admin_c.user, data={
                'codigo': 'C-X', 'titulo': 'Controle válido', 'descricao': 'x',
                'risco': risk, 'responsavel': None, 'frequencia': 'MENSAL', 'ativo': True,
            })
            self.assertEqual(control.unidade_id, risk.unidade_id)
        with tenant_context(self.a):
            self.assertFalse(m.RiscoControleInterno.objects.filter(pk=risk.pk).exists())
            with self.assertRaises(PermissionDenied):
                svc.create_recommendation(self.admin_c.user, finding_id=999999, text='cross tenant')
            OrganizationERP.objects.create(organization=self.a, erp=self.publico)
            from .models import Secretaria
            foreign_secretary = Secretaria.objects.create(organization=self.a, codigo='FOREIGN-SEC', nome='Secretaria alheia')
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                svc.create_control(self.admin_c.user, data={
                    'codigo': 'C-FOREIGN', 'titulo': 'Controle inválido', 'descricao': 'x',
                    'risco': risk, 'responsavel': None, 'frequencia': 'MENSAL', 'ativo': True,
                    'secretaria': foreign_secretary,
                })

    def test_private_evidence_is_tenant_owned_audited_and_cannot_be_deleted(self):
        with tenant_context(self.c):
            finding = svc.create_finding(self.admin_c.user, data={
                'codigo': 'A-EVID-1', 'titulo': 'Achado com evidência', 'descricao': 'Descrição',
                'origem': '', 'risco': None, 'controle': None, 'severidade': 'BAIXA',
                'prazo': None, 'responsavel': None,
            })
            upload = SimpleUploadedFile('evidencia.txt', b'conteudo sintetico', content_type='text/plain')
            with patch.object(m.private_storage, '_save', side_effect=lambda name, content: name):
                evidence = svc.upload_evidence(self.admin_c.user, finding_id=finding.pk,
                    title='Documento sintético', uploaded_file=upload, content_type='text/plain')
            self.assertIn(str(self.c.public_id), evidence.arquivo.name)
            self.assertEqual(len(evidence.sha256), 64)
            with self.assertRaises(ValidationError):
                evidence.delete()
            self.assertTrue(m.EventoControleInterno.objects.filter(acao='EVIDENCIA_ANEXADA').exists())
        with tenant_context(self.a):
            self.assertFalse(m.EvidenciaControleInterno.objects.filter(pk=evidence.pk).exists())

    def test_user_without_municipal_access_and_wrong_tenant_cannot_open_governance(self):
        stranger = self._user('governance-no-access', self.c, self.publico, 'ADMIN')
        self.client.force_login(stranger.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:governance_home')).status_code, 403)
        self.assertEqual(self.client.post(reverse('rh_municipal_public:governance_risk_create')).status_code, 403)
        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:governance_home')).status_code, 403)

    def test_unit_scoped_dashboard_does_not_list_records_outside_unit_scope(self):
        self._risk(code='R-UNIT', title='Risco da unidade autorizada')
        self._risk(code='R-ORG', title='Risco da Prefeitura sem unidade')
        # Remove the unit from a second synthetic record using a same-tenant service write.
        with tenant_context(self.c):
            global_risk = m.RiscoControleInterno.objects.get(codigo='R-ORG')
            global_risk.unidade = None
            global_risk.setor = None
            global_risk.departamento = None
            global_risk.secretaria = None
            global_risk.save()
            viewer = self._user('governance-unit-viewer', self.c, self.publico, 'ADMIN')
            access = AcessoMunicipal.objects.create(
                membership=viewer, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='governance.dashboard.view', permitido=True)
            PermissaoMunicipal.objects.create(acesso=access, capacidade='governance.risks.view', permitido=True)
        self.client.force_login(viewer.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.get(reverse('rh_municipal_public:governance_home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Risco da unidade autorizada')
        self.assertNotContains(response, 'Risco da Prefeitura sem unidade')
