import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership, MembershipERP, PlatformAudit
from contas.models import Usuario, Tecnico
from . import models as m, workforce as w
from .employee_forms import FuncionarioForm
from .employee_services import save_employee
from .test_block2 import Block2Fixtures


class EmployeeFixture(Block2Fixtures):
    password = 'Synthetic!Only-Employee-4837'

    def payload(self, **extra):
        values = {'nome': 'Funcionário de teste', 'matricula': 'RH-001', 'telefone': '82990000000',
                  'email': 'funcionario@example.invalid', 'ativo': 'on', 'cargo': 'Auxiliar Técnico',
                  'conta_modo': 'NOVA', 'username': 'rh-central-test', 'password1': self.password,
                  'password2': self.password, 'perfil': 'TECNICO', 'acesso_assistencia': 'on',
                  'jornada_modo': 'NOVA', 'nova_jornada-nome': 'Jornada RH central',
                  'nova_jornada-ativo': 'on', 'nova_jornada-tolerancia_atraso_minutos': '0',
                  'tecnico_ativo': 'on', 'tecnico_especialidades': 'Autoclaves',
                  'tecnico_conselho': 'CRT', 'tecnico_numero_registro': 'QA-123',
                  'tecnico_competencias': 'Manutenção de teste'}
        for day in range(5):
            values.update({f'nova_jornada-dia_{day}_trabalha': 'on', f'nova_jornada-dia_{day}_entrada': '07:30',
                           f'nova_jornada-dia_{day}_inicio_intervalo': '12:00',
                           f'nova_jornada-dia_{day}_fim_intervalo': '13:00', f'nova_jornada-dia_{day}_saida': '17:00'})
        values.update(extra)
        return values

    def linked_payload(self, user, **extra):
        values = self.payload(conta_modo='EXISTENTE', usuario=user.pk, jornada_modo='EXISTENTE')
        for key in ['username', 'password1', 'password2']:
            values.pop(key)
        values.update(extra)
        return values

    def create_url(self):
        return reverse('operacao:rh_new', args=['funcionarios'])


class EmployeeCentralTests(EmployeeFixture, TestCase):
    def setUp(self):
        self.setup_operations()

    def test_single_sheet_has_visual_week_and_no_json_editor(self):
        response = self.client.get(self.create_url())
        self.assertEqual(response.status_code, 200)
        for label in ['Dados do funcionário', 'Trabalho', 'Acesso ao VERTYX', 'Jornada de trabalho',
                      'Informações do técnico', 'Aplicar horário de segunda a sexta', 'Sábado', 'Domingo']:
            self.assertContains(response, label)
        self.assertNotContains(response, 'name="semana"')
        self.assertNotContains(response, 'name="nova_jornada-semana"')
        self.assertNotContains(response, 'name="cpf"')
        self.assertContains(self.client.get(reverse('operacao:rh_list', args=['funcionarios'])), 'Novo funcionário')
        standalone = self.client.get(reverse('operacao:rh_new', args=['jornadas']))
        self.assertContains(standalone, 'type="time"', count=32)
        self.assertNotContains(standalone, 'name="semana"')

    def test_create_new_technician_account_membership_employee_and_journey(self):
        response = self.client.post(self.create_url(), self.payload())
        self.assertRedirects(response, reverse('operacao:rh_list', args=['funcionarios']))
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get(matricula='RH-001')
            member = OrganizationMembership.objects.get(user=employee.usuario, organization=self.a)
            self.assertEqual(member.role, 'TECNICO')
            self.assertEqual(employee.tecnico.usuario, employee.usuario)
            self.assertEqual(employee.tecnico.especialidades, 'Autoclaves')
            self.assertEqual(employee.tecnico.numero_registro, 'QA-123')
            self.assertEqual(employee.cargo, 'Auxiliar Técnico')
            self.assertNotEqual(employee.cargo, member.role)
            self.assertTrue(employee.usuario.check_password(self.password))
            access = MembershipERP.objects.get(membership=member, erp=self.erp)
            self.assertTrue(access.enabled)
            self.assertFalse(access.visualizar_painel_operacional)
            self.assertFalse(employee.usuario.is_staff)
            self.assertFalse(employee.usuario.is_superuser)
            self.assertEqual(set(employee.jornada.semana), set('01234'))
            self.assertEqual(employee.jornada.semana['0'], {'entrada': '07:30', 'inicio_intervalo': '12:00',
                                                          'fim_intervalo': '13:00', 'saida': '17:00'})
            self.assertEqual(w.expected(employee, date(2026, 10, 5), {})[0], 510)
            self.assertEqual(w.expected(employee, date(2026, 10, 10), {})[0], 0)
            actions = set(PlatformAudit.objects.filter(organization=self.a).values_list('action', flat=True))
            self.assertTrue({'RH_CONTA_CRIADA', 'RH_JORNADA_CRIADA', 'RH_TECNICO_VINCULADO', 'RH_CADASTRO_SALVO'} <= actions)
            self.assertNotIn(self.password, str(list(PlatformAudit.objects.values_list('changes', flat=True))))

    def test_created_technician_login_pwa_and_my_timekeeping_use_new_journey(self):
        self.client.post(self.create_url(), self.payload())
        user = Usuario.objects.get(username='rh-central-test')
        self.client.logout()
        self.assertRedirects(self.client.post('/login/', {'username': user.username, 'password': self.password}), '/tecnico/')
        response = self.client.get('/tecnico/')
        self.assertContains(response, 'Meu atendimento / Atender')
        self.assertNotContains(response, 'Voltar para VERTYX')
        self.assertEqual(self.client.get('/financeiro/').status_code, 403)
        self.assertEqual(self.client.get('/rh/funcionarios/').status_code, 403)
        self.assertEqual(self.client.get('/ponto/').status_code, 200)
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get(usuario=user)
            self.assertEqual(w.employee_for(user).pk, employee.pk)
            monday = next(row for row in w.mirror(user, employee.public_id, 2026, 10)['dias'] if row['data'] == '2026-10-05')
            self.assertEqual(monday['previsto'], 510)
            mark = w.mark(user, 'ENTRADA', uuid.uuid4())
            self.assertEqual(mark.funcionario_id, employee.pk)

    def test_reuses_existing_technical_sheet_without_erasing_professional_data(self):
        with tenant_context(self.a):
            tech = self.da['tech']; tech.especialidades = 'Especialidade anterior'; tech.custo_hora = Decimal('37.13'); tech.ativo = False; tech.save()
            count = Tecnico.objects.count()
        values = self.linked_payload(self.users['TECNICO'])
        for key in list(values):
            if key.startswith('tecnico_'):
                values.pop(key)
        self.assertEqual(self.client.post(self.create_url(), values).status_code, 302)
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get()
            tech.refresh_from_db()
            self.assertEqual(employee.tecnico_id, tech.pk)
            self.assertEqual(Tecnico.objects.count(), count)
            self.assertEqual((tech.especialidades, tech.custo_hora, tech.ativo), ('Especialidade anterior', Decimal('37.13'), False))
            self.assertEqual(self.da['order'].tecnico_id, tech.pk)

    def test_links_unassigned_technical_sheet_when_explicitly_selected(self):
        with tenant_context(self.a):
            tech = Tecnico.objects.create(nome='Ficha antiga sem acesso', especialidades='Calibração')
        values = self.payload(tecnico_existente=tech.pk)
        values.pop('tecnico_especialidades')
        self.assertEqual(self.client.post(self.create_url(), values).status_code, 302)
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get()
            tech.refresh_from_db()
            self.assertEqual(employee.tecnico_id, tech.pk)
            self.assertEqual(tech.usuario_id, employee.usuario_id)
            self.assertEqual(tech.especialidades, 'Calibração')

    def test_existing_journey_is_selected_without_creating_another(self):
        with tenant_context(self.a):
            journey = m.JornadaTrabalho.objects.create(nome='Existente', semana={'0': {'entrada': '08:00', 'saida': '16:00'}})
        values = self.payload(jornada_modo='EXISTENTE', jornada=journey.pk)
        self.assertEqual(self.client.post(self.create_url(), values).status_code, 302)
        with tenant_context(self.a):
            self.assertEqual(m.JornadaTrabalho.objects.count(), 1)
            self.assertEqual(m.Funcionario.objects.get().jornada_id, journey.pk)

    def test_edit_work_contacts_profile_journey_and_preserve_identity_and_history(self):
        self.client.post(self.create_url(), self.payload())
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get(); user = employee.usuario
            department = m.Departamento.objects.create(nome='Oficina')
            technical_id = employee.tecnico_id
            original_user_contact = (user.telefone, user.email, user.perfil)
        values = self.linked_payload(user, nome='Pessoa editada', cargo='Vendedor de campo', perfil='VENDEDOR',
                                     departamento=department.pk, telefone='82980000000', email='novo@example.invalid',
                                     jornada_modo='NOVA', **{'nova_jornada-nome': 'Outra jornada'})
        response = self.client.post(reverse('operacao:rh_edit', args=['funcionarios', employee.pk]), values)
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.a):
            employee.refresh_from_db(); user.refresh_from_db()
            self.assertEqual((employee.usuario_id, employee.tecnico_id), (user.pk, technical_id))
            self.assertEqual(employee.cargo, 'Vendedor de campo')
            self.assertEqual(employee.departamento_id, department.pk)
            self.assertEqual(employee.jornada.nome, 'Outra jornada')
            self.assertEqual(employee.telefone, '82980000000')
            self.assertEqual((user.telefone, user.email, user.perfil), original_user_contact)
            self.assertEqual(OrganizationMembership.objects.get(user=user, organization=self.a).role, 'VENDEDOR')
            self.assertEqual(Tecnico.objects.filter(usuario=user).count(), 1)
        self.client.force_login(user)
        self.assertRedirects(self.client.get('/vertyx/'), '/vendedor/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/financeiro/').status_code, 403)

    def test_seller_pdv_and_financial_roles_use_existing_authorizations(self):
        for index, role in enumerate(['VENDEDOR', 'PDV', 'FINANCEIRO', 'GESTOR', 'ADMIN']):
            self.client.force_login(self.admin)
            values = self.payload(username='employee-role-' + role.lower(), matricula='ROLE-' + str(index),
                                  perfil=role, jornada_modo='EXISTENTE')
            self.assertEqual(self.client.post(self.create_url(), values).status_code, 302)
            user = Usuario.objects.get(username=values['username'])
            with tenant_context(self.a):
                self.assertIsNone(m.Funcionario.objects.get(usuario=user).tecnico_id)
            self.client.logout()
            self.client.post('/login/', {'username': user.username, 'password': self.password})
            if role in ['VENDEDOR', 'PDV']:
                self.assertRedirects(self.client.get('/vertyx/'), '/pdv/' if role=='PDV' else '/vendedor/', fetch_redirect_response=False)
                self.assertEqual(self.client.get('/financeiro/').status_code, 403)
                self.assertEqual(self.client.get('/contas/usuarios/').status_code, 403)
            else:
                self.assertEqual(self.client.get('/financeiro/').status_code, 200)
                self.assertEqual(self.client.get('/contas/usuarios/').status_code, 200 if role == 'ADMIN' else 403)

    def test_duplicate_employee_username_and_matricula_are_rejected(self):
        self.assertEqual(self.client.post(self.create_url(), self.payload()).status_code, 302)
        user = Usuario.objects.get(username='rh-central-test')
        for values in [self.linked_payload(user, matricula='OTHER'),
                       self.payload(username='other-unique'), self.payload(matricula='OTHER')]:
            self.assertEqual(self.client.post(self.create_url(), values).status_code, 400)
        with tenant_context(self.a):
            self.assertEqual(m.Funcionario.objects.count(), 1)
            self.assertEqual(m.JornadaTrabalho.objects.count(), 1)
        self.assertFalse(Usuario.objects.filter(username='other-unique').exists())

    def test_invalid_schedule_or_failure_rolls_back_all_related_writes(self):
        original_users = Usuario.objects.count()
        invalid = self.payload(**{'nova_jornada-dia_0_saida': '07:00'})
        self.assertEqual(self.client.post(self.create_url(), invalid).status_code, 400)
        interval = self.payload(**{'nova_jornada-dia_0_fim_intervalo': ''})
        self.assertEqual(self.client.post(self.create_url(), interval).status_code, 400)
        with patch('operacao.employee_services.Tecnico.save', side_effect=ValidationError('Falha sintética')):
            self.assertEqual(self.client.post(self.create_url(), self.payload()).status_code, 400)
        self.assertEqual(Usuario.objects.count(), original_users)
        self.assertFalse(OrganizationMembership.objects.filter(user__username='rh-central-test').exists())
        with tenant_context(self.a):
            self.assertFalse(m.Funcionario.objects.exists())
            self.assertFalse(m.JornadaTrabalho.objects.exists())
            self.assertFalse(PlatformAudit.objects.filter(action__startswith='RH_').exists())

    def test_cross_organization_choices_and_edit_urls_remain_scoped(self):
        with tenant_context(self.b):
            department = m.Departamento.objects.create(nome='DEPARTAMENTO RESTRITO')
            journey = m.JornadaTrabalho.objects.create(nome='JORNADA RESTRITA', semana={'0': {'entrada': '08:00', 'saida': '16:00'}})
            technical = Tecnico.objects.create(nome='TECNICO RESTRITO SEM CONTA')
            employee = m.Funcionario.objects.create(usuario=self.tech_b, matricula='B', nome='FUNCIONARIO RESTRITO')
        response = self.client.get(self.create_url())
        for text in ['DEPARTAMENTO RESTRITO', 'JORNADA RESTRITA', 'TECNICO RESTRITO SEM CONTA', 'FUNCIONARIO RESTRITO']:
            self.assertNotContains(response, text)
        self.assertEqual(self.client.get(reverse('operacao:rh_edit', args=['funcionarios', employee.pk])).status_code, 404)
        for extra in [dict(departamento=department.pk), dict(gestor=self.admin_b.pk),
                      dict(jornada_modo='EXISTENTE', jornada=journey.pk), dict(tecnico_existente=technical.pk),
                      dict(conta_modo='EXISTENTE', usuario=self.admin_b.pk)]:
            self.assertEqual(self.client.post(self.create_url(), self.payload(**extra)).status_code, 400)
        self.assertFalse(Usuario.objects.filter(username='rh-central-test').exists())

    def test_manager_rh_cannot_grant_access_and_technician_cannot_use_sheet(self):
        hr = self.user('hr-central', self.a, 'RH')
        for user in [self.users['GESTOR'], hr]:
            self.client.force_login(user)
            response = self.client.get(self.create_url())
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'name="perfil"')
            self.assertNotContains(response, 'name="password1"')
            self.assertEqual(self.client.post(self.create_url(), self.linked_payload(self.users['TECNICO'], perfil='ADMIN')).status_code, 400)
            self.assertEqual(OrganizationMembership.objects.get(user=self.users['TECNICO'], organization=self.a).role, 'TECNICO')
        self.client.force_login(self.users['TECNICO'])
        self.assertEqual(self.client.get(self.create_url()).status_code, 403)
        self.assertEqual(self.client.post(self.create_url(), self.payload()).status_code, 403)

    def test_hr_can_register_existing_authorized_person_without_access_changes(self):
        hr = self.user('hr-central', self.a, 'RH')
        values = self.linked_payload(self.users['TECNICO'])
        for key in list(values):
            if key in ['perfil', 'acesso_assistencia'] or key.startswith('tecnico_'):
                values.pop(key)
        self.client.force_login(hr)
        self.assertEqual(self.client.post(self.create_url(), values).status_code, 302)
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get()
            self.assertEqual(employee.tecnico_id, self.da['tech'].pk)
            self.assertEqual(OrganizationMembership.objects.get(user=employee.usuario, organization=self.a).role, 'TECNICO')

    def test_shared_global_account_and_other_membership_are_not_edited(self):
        shared = self.users['TECNICO']
        other_member = OrganizationMembership.objects.create(user=shared, organization=self.b, role='FINANCEIRO')
        MembershipERP.objects.create(membership=other_member, erp=self.erp)
        shared.telefone = 'original'; shared.email = 'global@example.invalid'; shared.save()
        values = self.linked_payload(shared, telefone='local', email='local@example.invalid')
        self.assertEqual(self.client.post(self.create_url(), values).status_code, 302)
        shared.refresh_from_db(); other_member.refresh_from_db()
        self.assertEqual((shared.telefone, shared.email), ('original', 'global@example.invalid'))
        self.assertEqual(other_member.role, 'FINANCEIRO')
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get()
            self.assertEqual((employee.telefone, employee.email), ('local', 'local@example.invalid'))

    def test_employee_user_cannot_be_swapped_and_admin_cannot_remove_own_access(self):
        self.client.post(self.create_url(), self.linked_payload(self.admin, perfil='ADMIN'))
        with tenant_context(self.a):
            employee = m.Funcionario.objects.get()
        url = reverse('operacao:rh_edit', args=['funcionarios', employee.pk])
        for extra in [dict(usuario=self.users['TECNICO'].pk), dict(perfil='TECNICO'), dict(acesso_assistencia='')]:
            self.assertEqual(self.client.post(url, self.linked_payload(self.admin, perfil='ADMIN', **extra) if 'perfil' not in extra else self.linked_payload(self.admin, **extra)).status_code, 400)
        with tenant_context(self.a):
            employee.refresh_from_db()
            self.assertEqual(employee.usuario_id, self.admin.pk)
        self.assertEqual(OrganizationMembership.objects.get(user=self.admin, organization=self.a).role, 'ADMIN')

    def test_standalone_visual_journey_edit_and_weekend_night_shift(self):
        values = {'nome': 'Visual noturna', 'ativo': 'on', 'virada_dia': 'on', 'tolerancia_atraso_minutos': '0',
                  'dia_5_trabalha': 'on', 'dia_5_entrada': '22:00', 'dia_5_saida': '06:00',
                  'dia_5_inicio_intervalo': '01:00', 'dia_5_fim_intervalo': '02:00'}
        self.assertEqual(self.client.post(reverse('operacao:rh_new', args=['jornadas']), values).status_code, 302)
        with tenant_context(self.a):
            journey = m.JornadaTrabalho.objects.get()
            self.assertEqual(set(journey.semana), {'5'})
            self.assertEqual(w.schedule_values(journey.semana['5'], True), (1320, 1800, 1500, 1560))
        url = reverse('operacao:rh_edit', args=['jornadas', journey.pk])
        self.assertContains(self.client.get(url), 'value="22:00"')
        values['dia_5_saida'] = '07:00'
        self.assertEqual(self.client.post(url, values).status_code, 302)
        with tenant_context(self.a):
            journey.refresh_from_db()
            self.assertEqual(journey.semana['5']['saida'], '07:00')


@skipUnless(connection.vendor == 'postgresql', 'Row-lock concurrency requires PostgreSQL')
class EmployeeConcurrencyTests(EmployeeFixture, TransactionTestCase):
    def test_simultaneous_registration_preserves_one_person_and_one_technical_sheet(self):
        self.setup_operations()
        barrier = Barrier(2)
        def worker(index):
            try:
                with tenant_context(self.a):
                    actor = Usuario.objects.get(pk=self.admin.pk)
                    values = self.linked_payload(self.users['TECNICO'], matricula='RACE-' + str(index))
                    form = FuncionarioForm(values, actor=actor)
                    if not form.is_valid():
                        return 'unexpected invalid form'
                    barrier.wait(timeout=20)
                    try:
                        save_employee(actor, form)
                        return 'ok'
                    except ValidationError:
                        return 'duplicate'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertCountEqual(results, ['ok', 'duplicate'])
        with tenant_context(self.a):
            self.assertEqual(m.Funcionario.objects.filter(usuario=self.users['TECNICO']).count(), 1)
            self.assertEqual(Tecnico.objects.filter(usuario=self.users['TECNICO']).count(), 1)


@skipUnless(connection.vendor == 'postgresql', 'Migration preservation requires PostgreSQL')
class EmployeeMigrationTests(EmployeeFixture, TransactionTestCase):
    def test_additive_contact_migration_preserves_existing_person_and_links(self):
        self.setup_operations()
        user = self.users['TECNICO']; user.telefone = '82991112222'; user.email = 'migration@example.invalid'; user.save()
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('operacao', '0014_piloto_jornada_contratual')])
            apps = executor.loader.project_state([('operacao', '0014_piloto_jornada_contratual')]).apps
            old = apps.get_model('operacao', 'Funcionario')
            employee = old.objects.create(organization_id=self.a.pk, usuario_id=user.pk, tecnico_id=self.da['tech'].pk,
                                          matricula='LEGACY-RH', nome='Pessoa preservada')
            before = {'user': (user.pk, user.email, user.telefone, user.perfil),
                      'members': list(OrganizationMembership.objects.values_list('pk', 'organization_id', 'user_id', 'role')),
                      'order': (self.da['order'].pk, self.da['order'].tecnico_id, self.da['order'].status)}
            executor = MigrationExecutor(connection); executor.migrate(latest)
            with tenant_context(self.a):
                current = m.Funcionario.objects.get(pk=employee.pk)
                self.assertEqual((current.nome, current.usuario_id, current.tecnico_id), ('Pessoa preservada', user.pk, self.da['tech'].pk))
                self.assertEqual((current.telefone, current.email), (user.telefone, user.email))
                self.da['order'].refresh_from_db()
                self.assertEqual((self.da['order'].pk, self.da['order'].tecnico_id, self.da['order'].status), before['order'])
            user.refresh_from_db()
            self.assertEqual((user.pk, user.email, user.telefone, user.perfil), before['user'])
            self.assertEqual(list(OrganizationMembership.objects.values_list('pk', 'organization_id', 'user_id', 'role')), before['members'])
        finally:
            MigrationExecutor(connection).migrate(latest)
