import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, ModuloOrganizacao
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS
from . import phase_h_models as m
from . import phase_h_services as svc
from .models import AcessoMunicipal, PermissaoMunicipal
from .tests import MunicipalFixtures


class MunicipalPhaseHTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.education = ERPProductModule.objects.get_or_create(
            erp=self.publico, code=m.EDUCATION_MODULE,
            defaults={'name': 'Educação Municipal', 'active': True, 'sort_order': 140},
        )[0]
        self.gp = ERPProductModule.objects.get_or_create(
            erp=self.publico, code='gestao_publica',
            defaults={'name': 'Gestão Pública', 'active': True, 'sort_order': 1},
        )[0]
        plan = PlanoSaaS.objects.create(slug=f'phase-h-{uuid.uuid4().hex[:8]}', nome='Plano sintético Educação', erp=self.publico, modulos=[])
        PlanoProdutoModulo.objects.get_or_create(plano=plan, modulo=self.gp)
        PlanoProdutoModulo.objects.get_or_create(plano=plan, modulo=self.education)
        AssinaturaSaaS.objects.create(organization=self.c, plano=plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.municipal_access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )

    def _school_year_and_class(self, *, capacity=2):
        with tenant_context(self.c):
            school = svc.configure_school(self.admin_c.user, unit_id=self.structure[3].pk, data={
                'codigo_inep': '', 'tipo': 'FUNDAMENTAL', 'etapas': ['Fundamental I'], 'ativa': True,
            })
            year = m.AnoLetivoMunicipal.objects.create(
                organization=self.c, nome='Ano letivo sintético',
                inicio=date(2026, 2, 1), fim=date(2026, 12, 15),
            )
            group = m.TurmaMunicipal.objects.create(
                organization=self.c, escola=school, ano_letivo=year,
                codigo='T-1A', etapa='1º ano', turno='MANHA', capacidade=capacity,
            )
            return school, year, group

    def _student(self, name='Estudante Sintético'):
        with tenant_context(self.c):
            return svc.create_student_identity(self.admin_c.user, data={
                'nome': name, 'cpf': '', 'cns': '', 'data_nascimento': date(2018, 3, 12),
                'telefone': '', 'email': '', 'cep': '', 'endereco': '', 'bairro': '',
                'municipio': '', 'uf': '',
            })

    def test_home_and_pwa_require_the_contracted_module_and_never_auto_grant(self):
        self.assertEqual(self.client.get(reverse('rh_municipal_public:educacao_home')).status_code, 200)
        manifest = self.client.get(reverse('rh_municipal_public:educacao_manifest'))
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()['scope'], '/gestao-publica/educacao/')
        worker = self.client.get(reverse('rh_municipal_public:educacao_worker'))
        self.assertIn('no-store', worker['Cache-Control'])
        self.assertNotIn('caches.open', worker.content.decode())
        self.assertFalse(ModuloOrganizacao.objects.filter(organization=self.c, codigo=m.EDUCATION_MODULE).exists())
        PlanoProdutoModulo.objects.filter(plano__assinaturas__organization=self.c, modulo=self.education).delete()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:educacao_home')).status_code, 403)

    def test_registration_reuses_existing_unit_and_links_shared_citizen_without_cross_tenant_data(self):
        school, year, group = self._school_year_and_class()
        citizen = self._student()
        with tenant_context(self.c):
            enrollment = svc.enroll_student(
                self.admin_c.user, citizen_id=citizen.pk, school_id=school.pk,
                class_id=group.pk, school_year_id=year.pk, enrollment_number='EDU-001',
            )
            self.assertEqual(enrollment.unidade_id, self.structure[3].pk)
            self.assertEqual(m.EscolaMunicipal.objects.filter(organization=self.c).count(), 1)
        with tenant_context(self.a):
            self.assertFalse(m.EscolaMunicipal.objects.filter(pk=school.pk).exists())
            self.assertFalse(m.MatriculaAlunoMunicipal.objects.filter(pk=enrollment.pk).exists())
            with self.assertRaises(PermissionDenied):
                svc.enroll_student(self.admin_c.user, citizen_id=citizen.pk, school_id=school.pk,
                                   class_id=group.pk, school_year_id=year.pk, enrollment_number='SPOOF')

    def test_capacity_duplicate_enrollment_attendance_and_grade_rules(self):
        school, year, group = self._school_year_and_class(capacity=1)
        citizen = self._student()
        with tenant_context(self.c):
            enrollment = svc.enroll_student(self.admin_c.user, citizen_id=citizen.pk, school_id=school.pk,
                class_id=group.pk, school_year_id=year.pk, enrollment_number='EDU-002')
            with self.assertRaisesMessage(ValidationError, 'Já existe matrícula'):
                svc.enroll_student(self.admin_c.user, citizen_id=citizen.pk, school_id=school.pk,
                    class_id=group.pk, school_year_id=year.pk, enrollment_number='EDU-003')
            second = self._student('Outra Estudante Sintética')
            with self.assertRaisesMessage(ValidationError, 'capacidade'):
                svc.enroll_student(self.admin_c.user, citizen_id=second.pk, school_id=school.pk,
                    class_id=group.pk, school_year_id=year.pk, enrollment_number='EDU-004')
            first_attendance = svc.record_attendance(self.admin_c.user, enrollment_id=enrollment.pk,
                date=date(2026, 3, 2), status='PRESENTE')
            updated_attendance = svc.record_attendance(self.admin_c.user, enrollment_id=enrollment.pk,
                date=date(2026, 3, 2), status='JUSTIFICADA', note='Documento conferido')
            self.assertEqual(first_attendance.pk, updated_attendance.pk)
            self.assertEqual(m.EventoEducacaoMunicipal.objects.filter(acao='FREQUENCIA_REGISTRADA').count(), 2)
            assessment = m.AvaliacaoEscolarMunicipal.objects.create(
                organization=self.c, turma=group, disciplina='Matemática', descricao='Avaliação sintética',
                realizada_em=date(2026, 3, 5), valor_maximo=Decimal('10'), criada_por=self.admin_c.user,
            )
            note = svc.record_grade(self.admin_c.user, assessment_id=assessment.pk,
                enrollment_id=enrollment.pk, value=Decimal('8.50'))
            self.assertEqual(note.valor, Decimal('8.50'))
            with self.assertRaises(ValidationError):
                svc.record_grade(self.admin_c.user, assessment_id=assessment.pk,
                    enrollment_id=enrollment.pk, value=Decimal('10.50'))

    def test_direct_access_denied_without_municipal_permission_or_with_another_tenant(self):
        stranger = self._user('education-no-access', self.c, self.publico, 'ADMIN')
        self.client.force_login(stranger.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:educacao_home')).status_code, 403)

    def test_dashboard_permission_does_not_expose_school_or_student_rows(self):
        school, year, group = self._school_year_and_class()
        citizen = self._student('Identidade Escolar Protegida')
        with tenant_context(self.c):
            svc.enroll_student(self.admin_c.user, citizen_id=citizen.pk, school_id=school.pk,
                class_id=group.pk, school_year_id=year.pk, enrollment_number='PRIVATE-1')
            viewer = self._user('education-dashboard-only', self.c, self.publico, 'TECNICO')
            access = AcessoMunicipal.objects.create(
                membership=viewer, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(
                acesso=access, capacidade='educacao.dashboard.view', permitido=True,
            )
        self.client.force_login(viewer.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.get(reverse('rh_municipal_public:educacao_home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lista de escolas restrita.')
        self.assertContains(response, 'Lista de matrículas restrita.')
        self.assertNotContains(response, 'Identidade Escolar Protegida')
        self.assertEqual(self.client.get(reverse('rh_municipal_public:educacao_student_register')).status_code, 403)
        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:educacao_home')).status_code, 403)

