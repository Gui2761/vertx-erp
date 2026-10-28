import uuid
from datetime import timedelta
from decimal import Decimal

from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, OrganizationERP
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS
from . import phase_g_models as m
from . import phase_g_services as svc
from .phase_g_forms import HealthFieldVisitForm, PatientForm
from .models import AcessoMunicipal, PermissaoMunicipal, Secretaria, DepartamentoMunicipal, SetorMunicipal, UnidadeMunicipal
from .tests import MunicipalFixtures


class MunicipalPhaseGTests(MunicipalFixtures):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def setUp(self):
        super().setUp()
        self.health = ERPProductModule.objects.get_or_create(
            erp=self.publico, code='saude_sus',
            defaults={'name': 'Saúde SUS', 'active': True, 'sort_order': 130},
        )[0]
        self.gp = ERPProductModule.objects.get_or_create(
            erp=self.publico, code='gestao_publica',
            defaults={'name': 'Gestão Pública', 'active': True, 'sort_order': 1},
        )[0]
        self.plan = PlanoSaaS.objects.create(slug=f'phase-g-{uuid.uuid4().hex[:8]}', nome='Plano sintético Saúde', erp=self.publico, modulos=[])
        PlanoProdutoModulo.objects.get_or_create(plano=self.plan, modulo=self.gp)
        PlanoProdutoModulo.objects.get_or_create(plano=self.plan, modulo=self.health)
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status=AssinaturaSaaS.Status.ACTIVE)
        with tenant_context(self.c):
            self.access = AcessoMunicipal.objects.create(
                membership=self.admin_c, papel=AcessoMunicipal.Papel.ADMIN_PREFEITURA,
                escopo=AcessoMunicipal.Escopo.PREFEITURA, atribuido_por=self.admin_c.user,
            )

    def _health_unit(self):
        with tenant_context(self.c):
            return m.UnidadeSaudeMunicipal.objects.create(
                organization=self.c, unidade=self.structure[3], cnes='',
            )

    def _citizen(self):
        with tenant_context(self.c):
            return svc.create_patient(self.admin_c.user, data={
                'nome': 'Pessoa Saúde Sintética', 'cpf': '', 'cns': '',
                'telefone': '', 'email': '', 'cep': '', 'endereco': '',
                'bairro': '', 'municipio': '', 'uf': '',
            })

    def _field_agent(self, kind='ACS'):
        health_unit = self._health_unit()
        unit = health_unit.unidade
        sector = unit.setor
        department = sector.departamento
        with tenant_context(self.c):
            team = m.EquipeSaudeMunicipal.objects.create(
                organization=self.c, codigo=f'T-{uuid.uuid4().hex[:8]}', nome='Equipe de campo sintética',
                tipo=kind, unidade_saude=health_unit, microarea='01',
                secretaria=department.secretaria, departamento=department, setor=sector, unidade=unit,
            )
            agent = m.ProfissionalSaudeMunicipal.objects.create(
                organization=self.c, servidor=self.server, unidade_saude=health_unit,
                equipe=team, ocupacao='Agente de campo', ativo=True,
                secretaria=department.secretaria, departamento=department, setor=sector, unidade=unit,
            )
        return health_unit, team, agent

    def test_health_home_and_own_scope_pwa_are_gated_and_network_only(self):
        response = self.client.get(reverse('rh_municipal_public:saude_home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Somente unidades no seu escopo')
        manifest = self.client.get(reverse('rh_municipal_public:saude_manifest'))
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()['start_url'], '/gestao-publica/saude/')
        self.assertEqual(manifest.json()['scope'], '/gestao-publica/saude/')
        worker = self.client.get(reverse('rh_municipal_public:saude_worker'))
        self.assertIn('no-store', worker['Cache-Control'])
        self.assertNotIn('caches.open', worker.content.decode())
        item = PlanoProdutoModulo.objects.get(plano=self.plan, modulo=self.health)
        item.delete()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:saude_home')).status_code, 403)

    def test_patient_creation_and_tenant_isolation(self):
        patient = self._citizen()
        with tenant_context(self.a):
            self.assertFalse(m.CidadaoSaudeMunicipal.objects.filter(pk=patient.pk).exists())
        with tenant_context(self.c):
            other_unit = m.UnidadeSaudeMunicipal.objects.create(organization=self.c, unidade=self.structure[3])
            other = self._user('health-no-municipal-access', self.c, self.publico, 'ADMIN')
            with self.assertRaises(PermissionDenied):
                svc._require(other.user, 'saude.patients.view')
            self.assertTrue(m.CidadaoSaudeMunicipal.objects.filter(pk=patient.pk, organization=self.c).exists())

    def test_clinical_content_is_encrypted_and_each_read_is_audited(self):
        health_unit = self._health_unit()
        with tenant_context(self.c):
            team = m.EquipeSaudeMunicipal.objects.create(organization=self.c, codigo='EQ-1', nome='Equipe 1', tipo='ESF', unidade_saude=health_unit)
            professional = m.ProfissionalSaudeMunicipal.objects.create(
                organization=self.c, servidor=self.server, unidade_saude=health_unit,
                equipe=team, ocupacao='Profissional sintético',
            )
            agenda = m.AgendaSaudeMunicipal.objects.create(
                organization=self.c, unidade_saude=health_unit, profissional=professional,
                inicio=timezone.now()+timedelta(days=1), fim=timezone.now()+timedelta(days=1, minutes=30),
                capacidade=2,
            )
            patient = self._citizen()
            appointment = svc.create_appointment(self.admin_c.user, agenda_id=agenda.pk, citizen_id=patient.pk)
            with self.assertRaisesMessage(ValidationError, 'atendimento em andamento'):
                svc.create_clinical_entry(
                    self.admin_c.user, appointment_id=appointment.pk,
                    content='Não deve gravar antes de iniciar',
                )
            svc.transition_appointment(
                self.admin_c.user, appointment_id=appointment.pk, status='EM_ATENDIMENTO',
            )
            key = Fernet.generate_key().decode()
            with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=key):
                entry = svc.create_clinical_entry(self.admin_c.user, appointment_id=appointment.pk,
                                                  content='CONTEUDO CLINICO PRIVADO', justification='Continuidade assistencial')
                self.assertNotIn(b'CONTEUDO CLINICO PRIVADO', bytes(entry.conteudo_cifrado))
                self.assertEqual(svc.read_clinical_entry(self.admin_c.user, entry_id=entry.pk,
                                                        justification='Atendimento autorizado'), 'CONTEUDO CLINICO PRIVADO')
            self.assertTrue(m.AuditoriaAcessoSaude.objects.filter(
                organization=self.c, acao='PRONTUARIO_ACESSADO', entidade_id=entry.pk,
            ).exists())
            with self.assertRaisesMessage(ValidationError, 'justificativa'):
                svc.read_clinical_entry(self.admin_c.user, entry_id=entry.pk, justification='')

    def test_missing_encryption_key_fails_closed_without_saving_note(self):
        health_unit = self._health_unit()
        with tenant_context(self.c):
            team = m.EquipeSaudeMunicipal.objects.create(organization=self.c, codigo='EQ-2', nome='Equipe 2', tipo='ESF', unidade_saude=health_unit)
            professional = m.ProfissionalSaudeMunicipal.objects.create(organization=self.c, servidor=self.server, unidade_saude=health_unit, equipe=team, ocupacao='Profissional')
            agenda = m.AgendaSaudeMunicipal.objects.create(organization=self.c, unidade_saude=health_unit, profissional=professional, inicio=timezone.now()+timedelta(days=2), fim=timezone.now()+timedelta(days=2, minutes=30))
            patient = self._citizen()
            appointment = svc.create_appointment(self.admin_c.user, agenda_id=agenda.pk, citizen_id=patient.pk)
            svc.transition_appointment(
                self.admin_c.user, appointment_id=appointment.pk, status='EM_ATENDIMENTO',
            )
            with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=''):
                with self.assertRaisesMessage(ValidationError, 'chave de cifragem'):
                    svc.create_clinical_entry(self.admin_c.user, appointment_id=appointment.pk, content='Nunca salvar em aberto')
            self.assertFalse(m.EvolucaoClinicaMunicipal.objects.filter(atendimento=appointment).exists())

    def test_clinical_record_screen_only_returns_plaintext_after_audited_read(self):
        health_unit = self._health_unit()
        patient = self._citizen()
        with tenant_context(self.c):
            professional = m.ProfissionalSaudeMunicipal.objects.create(
                organization=self.c, servidor=self.server, unidade_saude=health_unit,
                ocupacao='Profissional sintético',
            )
            start = timezone.now() + timedelta(days=1)
            agenda = m.AgendaSaudeMunicipal.objects.create(
                organization=self.c, unidade_saude=health_unit, profissional=professional,
                inicio=start, fim=start + timedelta(minutes=30), capacidade=1,
            )
            appointment = svc.create_appointment(
                self.admin_c.user, agenda_id=agenda.pk, citizen_id=patient.pk,
            )
            svc.transition_appointment(
                self.admin_c.user, appointment_id=appointment.pk, status='EM_ATENDIMENTO',
            )
            with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=Fernet.generate_key().decode()):
                url = reverse('rh_municipal_public:saude_clinical_record', args=[appointment.pk])
                create = self.client.post(url, {
                    'action': 'create', 'content': 'Evolução clínica sintética protegida',
                })
                self.assertEqual(create.status_code, 302)
                entry = m.EvolucaoClinicaMunicipal.objects.get(atendimento=appointment)
                self.assertNotIn(b'Evolu', bytes(entry.conteudo_cifrado))
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, 'Evolução clínica sintética protegida')
                self.assertIn('no-store', page['Cache-Control'])
                read = self.client.post(url, {
                    'action': 'read', 'entry_id': entry.pk,
                    'justification': 'Continuidade assistencial sintética',
                })
                self.assertEqual(read.status_code, 200)
                self.assertContains(read, 'Evolução clínica sintética protegida')
                self.assertTrue(m.AuditoriaAcessoSaude.objects.filter(
                    organization=self.c, acao='PRONTUARIO_ACESSADO', entidade_id=entry.pk,
                    justificativa='Continuidade assistencial sintética',
                ).exists())

            self.client.force_login(self.server_user.user)
            session = self.client.session
            session['organization_id'] = self.c.pk
            session.save()
            denied = self.client.get(url)
            self.assertEqual(denied.status_code, 403)

    def test_fefo_dispensing_is_atomic_idempotent_and_never_negative(self):
        health_unit = self._health_unit()
        patient = self._citizen()
        with tenant_context(self.c):
            medicine = m.MedicamentoMunicipal.objects.create(organization=self.c, codigo='MED-1', nome='Medicamento sintético', apresentacao='unidade', unidade_medida='UN')
            early = m.LoteMedicamentoMunicipal.objects.create(organization=self.c, medicamento=medicine, unidade_saude=health_unit, lote='L-1', validade=timezone.localdate()+timedelta(days=5), saldo=Decimal('2'))
            late = m.LoteMedicamentoMunicipal.objects.create(organization=self.c, medicamento=medicine, unidade_saude=health_unit, lote='L-2', validade=timezone.localdate()+timedelta(days=10), saldo=Decimal('4'))
            expired = m.LoteMedicamentoMunicipal.objects.create(organization=self.c, medicamento=medicine, unidade_saude=health_unit, lote='L-OLD', validade=timezone.localdate()-timedelta(days=1), saldo=Decimal('9'))
            operation = uuid.uuid4()
            params = {'citizen_id': patient.pk, 'health_unit_id': health_unit.pk,
                      'items': [{'medicine_id': medicine.pk, 'quantity': '5'}], 'request_id': operation}
            first = svc.dispense_fefo(self.admin_c.user, **params)
            replay = svc.dispense_fefo(self.admin_c.user, **params)
            self.assertEqual(first.pk, replay.pk)
            early.refresh_from_db(); late.refresh_from_db(); expired.refresh_from_db()
            self.assertEqual(early.saldo, Decimal('0'))
            self.assertEqual(late.saldo, Decimal('1'))
            self.assertEqual(expired.saldo, Decimal('9'))
            self.assertEqual(m.ItemDispensacaoSaude.objects.filter(dispensacao=first).count(), 2)
            self.assertEqual(m.DispensacaoMedicamentoMunicipal.objects.filter(request_id=operation).count(), 1)
            with self.assertRaisesMessage(ValidationError, 'chave de operação'):
                svc.dispense_fefo(self.admin_c.user, **{**params, 'items': [{'medicine_id': medicine.pk, 'quantity': '3'}]})

    def test_pharmacy_screen_catalog_lot_and_dispense_flow_is_idempotent(self):
        health_unit = self._health_unit()
        patient = self._citizen()
        pharmacy_url = reverse('rh_municipal_public:saude_pharmacy')
        response = self.client.post(pharmacy_url, {
            'action': 'medication', 'codigo': 'FAR-001', 'nome': 'Medicamento sintético',
            'apresentacao': 'Comprimido', 'unidade_medida': 'UN',
            'estoque_minimo': '2.000', 'ativo': 'on',
        })
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.c):
            medicine = m.MedicamentoMunicipal.objects.get(organization=self.c, codigo='FAR-001')

        lot_payload = {
            'action': 'lot', 'medicamento': medicine.pk, 'unidade_saude': health_unit.pk,
            'lot': 'LOTE-FAR-01', 'expires_on': (timezone.localdate()+timedelta(days=60)).isoformat(),
            'quantity': '5.000',
        }
        self.assertEqual(self.client.post(pharmacy_url, lot_payload).status_code, 302)
        operation = uuid.uuid4()
        dispense_payload = {
            'action': 'dispense', 'request_id': str(operation), 'cidadao': patient.pk,
            'unidade_saude': health_unit.pk, 'medicamento': medicine.pk, 'quantidade': '2.000',
        }
        self.assertEqual(self.client.post(pharmacy_url, dispense_payload).status_code, 302)
        self.assertEqual(self.client.post(pharmacy_url, dispense_payload).status_code, 302)
        with tenant_context(self.c):
            lot = m.LoteMedicamentoMunicipal.objects.get(
                organization=self.c, medicamento=medicine, unidade_saude=health_unit,
                lote='LOTE-FAR-01',
            )
            self.assertEqual(lot.saldo, Decimal('3.000'))
            self.assertEqual(m.DispensacaoMedicamentoMunicipal.objects.filter(
                organization=self.c, request_id=operation,
            ).count(), 1)
            self.assertEqual(m.ItemDispensacaoSaude.objects.filter(
                dispensacao__request_id=operation,
            ).aggregate(total=Sum('quantidade'))['total'], Decimal('2.000'))

        duplicate = self.client.post(pharmacy_url, lot_payload)
        self.assertEqual(duplicate.status_code, 200)
        with tenant_context(self.c):
            lot.refresh_from_db()
            self.assertEqual(lot.saldo, Decimal('3.000'))
            self.assertTrue(m.AuditoriaAcessoSaude.objects.filter(
                organization=self.c, acao='MEDICAMENTO_DISPENSADO',
            ).exists())

    def test_acs_field_visit_is_encrypted_audited_and_idempotent(self):
        key = Fernet.generate_key().decode()
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=key):
            health_unit, team, agent = self._field_agent('ACS')
            unit = health_unit.unidade
            sector = unit.setor
            department = sector.departamento
            with tenant_context(self.c):
                family = m.FamiliaTerritorialSaude.objects.create(
                    organization=self.c, codigo='FAM-ACS-01', referencia='Referência sintética',
                    endereco='Rua Sintética, 10', microarea=team.microarea, equipe=team,
                    unidade_saude=health_unit, secretaria=department.secretaria,
                    departamento=department, setor=sector, unidade=unit,
                )
            url = reverse('rh_municipal_public:saude_field_visits')
            operation_id = uuid.uuid4()
            notes = 'Acompanhamento familiar sintético; encaminhamento para retorno.'
            payload = {
                'action': 'record_visit', 'request_id': str(operation_id), 'tipo': 'ACS',
                'agente': str(agent.pk), 'familia': str(family.pk), 'cidadao': '', 'imovel': '',
                'realizada_em': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
                'observacoes': notes,
            }
            response = self.client.post(url, payload)
            self.assertEqual(response.status_code, 302)
            with tenant_context(self.c):
                visit = m.VisitaTerritorialSaude.objects.get(organization=self.c, public_id=operation_id)
                self.assertEqual(visit.status, 'REALIZADA')
                self.assertNotIn(notes.encode(), bytes(visit.observacoes_cifradas))
                self.assertEqual(Fernet(key.encode()).decrypt(bytes(visit.observacoes_cifradas)).decode(), notes)
                audit = m.AuditoriaAcessoSaude.objects.get(
                    organization=self.c, acao='VISITA_TERRITORIAL_REGISTRADA', entidade_id=visit.pk,
                )
                self.assertEqual(audit.detalhes['request_id'], str(operation_id))
                self.assertNotIn('observacoes', audit.detalhes)

            self.assertEqual(self.client.post(url, payload).status_code, 302)
            with tenant_context(self.c):
                self.assertEqual(m.VisitaTerritorialSaude.objects.filter(
                    organization=self.c, public_id=operation_id,
                ).count(), 1)
            altered = {**payload, 'observacoes': 'Conteúdo diferente com a mesma chave.'}
            response = self.client.post(url, altered)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'identificador de operação já foi utilizado com outros dados')
            with tenant_context(self.c):
                self.assertEqual(m.VisitaTerritorialSaude.objects.filter(
                    organization=self.c, public_id=operation_id,
                ).count(), 1)
            listing = self.client.get(url)
            self.assertEqual(listing.status_code, 200)
            self.assertContains(listing, 'Família FAM-ACS-01')
            self.assertNotContains(listing, notes)
            self.assertIn('no-store', listing['Cache-Control'])

    def test_ace_requires_property_and_blocks_cross_tenant_property(self):
        _, _, agent = self._field_agent('ACE')
        with self.assertRaises(ValidationError):
            with tenant_context(self.c):
                svc.record_field_visit(
                    self.admin_c.user, request_id=uuid.uuid4(), visit_type='ACE', agent_id=agent.pk,
                    performed_at=timezone.now(), observations='Visita sintética sem imóvel.',
                )
        from .phase_f_models import ContribuinteMunicipal, ImovelMunicipal
        with tenant_context(self.a):
            OrganizationERP.objects.get_or_create(
                organization=self.a, erp=self.publico, defaults={'enabled': True},
            )
            contributor = ContribuinteMunicipal.objects.create(
                organization=self.a, codigo='ACE-OUTRO-01', tipo='PF',
                documento='11111111111', nome='Pessoa de outro tenant',
            )
            other_property = ImovelMunicipal.objects.create(
                organization=self.a, inscricao='ACE-IMOVEL-01', proprietario=contributor,
                logradouro='Rua de outro tenant',
            )
        with tenant_context(self.c):
            with self.assertRaises(ValidationError):
                svc.record_field_visit(
                    self.admin_c.user, request_id=uuid.uuid4(), visit_type='ACE', agent_id=agent.pk,
                    property_id=other_property.pk, performed_at=timezone.now(),
                    observations='Tentativa sintética entre tenants.',
                )
            self.assertFalse(m.VisitaTerritorialSaude.objects.filter(organization=self.c).exists())
            form = HealthFieldVisitForm({
                'request_id': str(uuid.uuid4()), 'tipo': 'ACE', 'agente': str(agent.pk),
                'realizada_em': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
                'observacoes': 'Inspeção sintética.',
            }, actor=self.admin_c.user)
            self.assertFalse(form.is_valid())
            self.assertIn('imovel', form.errors)

    def test_field_visit_screen_enforces_permission_product_and_tenant(self):
        with tenant_context(self.c):
            scoped_membership = self._user('health-field-view-only', self.c, self.publico, 'TECNICO')
            scoped_access = AcessoMunicipal.objects.create(
                membership=scoped_membership, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, secretaria=self.structure[0],
                departamento=self.structure[1], setor=self.structure[2], unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=scoped_access, capacidade='saude.field.view')
        url = reverse('rh_municipal_public:saude_field_visits')
        self.client.force_login(scoped_membership.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Salvar visita')
        self.assertEqual(self.client.post(url, {'action': 'record_visit'}).status_code, 403)

        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.admin_c.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        PlanoProdutoModulo.objects.filter(plano=self.plan, modulo=self.health).delete()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_pharmacy_unit_scope_and_other_organization_are_enforced(self):
        allowed_unit = self._health_unit()
        patient = self._citizen()
        with tenant_context(self.c):
            other_secretary = Secretaria.objects.create(organization=self.c, codigo='SEC-FAR-2', nome='Secretaria Sul')
            other_department = DepartamentoMunicipal.objects.create(organization=self.c, secretaria=other_secretary, codigo='DEP-FAR-2', nome='Departamento Sul')
            other_sector = SetorMunicipal.objects.create(organization=self.c, departamento=other_department, codigo='SET-FAR-2', nome='Setor Sul')
            other_municipal_unit = UnidadeMunicipal.objects.create(organization=self.c, setor=other_sector, codigo='UNI-FAR-2', nome='Unidade Sul')
            other_unit = m.UnidadeSaudeMunicipal.objects.create(organization=self.c, unidade=other_municipal_unit)
            medicine = m.MedicamentoMunicipal.objects.create(
                organization=self.c, codigo='FAR-SCOPE', nome='Medicamento Escopo',
                apresentacao='Unidade', unidade_medida='UN',
            )
            m.LoteMedicamentoMunicipal.objects.create(
                organization=self.c, medicamento=medicine, unidade_saude=allowed_unit,
                lote='ESCOPO-1', validade=timezone.localdate()+timedelta(days=30), saldo=Decimal('3'),
                secretaria=self.structure[0], departamento=self.structure[1],
                setor=self.structure[2], unidade=self.structure[3],
            )
            m.LoteMedicamentoMunicipal.objects.create(
                organization=self.c, medicamento=medicine, unidade_saude=other_unit,
                lote='ESCOPO-2', validade=timezone.localdate()+timedelta(days=30), saldo=Decimal('8'),
                secretaria=other_secretary, departamento=other_department,
                setor=other_sector, unidade=other_municipal_unit,
            )
            scoped_membership = self._user('health-pharmacy-unit', self.c, self.publico, 'TECNICO')
            scoped_access = AcessoMunicipal.objects.create(
                membership=scoped_membership, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, secretaria=self.structure[0],
                departamento=self.structure[1], setor=self.structure[2], unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=scoped_access, capacidade='saude.pharmacy.view')
            PermissaoMunicipal.objects.create(acesso=scoped_access, capacidade='saude.pharmacy.manage')
            PermissaoMunicipal.objects.create(acesso=scoped_access, capacidade='saude.dispense')

        self.client.force_login(scoped_membership.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        pharmacy_url = reverse('rh_municipal_public:saude_pharmacy')
        response = self.client.get(pharmacy_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ESCOPO-1')
        self.assertNotContains(response, 'ESCOPO-2')
        scoped_lot = self.client.post(pharmacy_url, {
            'action': 'lot', 'medicamento': medicine.pk, 'unidade_saude': allowed_unit.pk,
            'lot': 'ESCOPO-3', 'expires_on': (timezone.localdate()+timedelta(days=45)).isoformat(),
            'quantity': '1.000',
        })
        self.assertEqual(scoped_lot.status_code, 302)
        forbidden_catalog = self.client.post(pharmacy_url, {
            'action': 'medication', 'codigo': 'FAR-BLOCK', 'nome': 'Não criar',
            'apresentacao': 'UN', 'unidade_medida': 'UN', 'estoque_minimo': '0', 'ativo': 'on',
        })
        self.assertEqual(forbidden_catalog.status_code, 403)
        with tenant_context(self.c):
            self.assertTrue(m.LoteMedicamentoMunicipal.objects.filter(
                organization=self.c, unidade_saude=allowed_unit, lote='ESCOPO-3',
            ).exists())
            self.assertFalse(m.MedicamentoMunicipal.objects.filter(
                organization=self.c, codigo='FAR-BLOCK',
            ).exists())

        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(pharmacy_url).status_code, 403)

    def test_regulation_priority_changes_require_reason_and_are_audited(self):
        health_unit = self._health_unit()
        patient = self._citizen()
        with tenant_context(self.c):
            request = m.SolicitacaoRegulacaoSaude.objects.create(
                organization=self.c, cidadao=patient, unidade_origem=health_unit,
                procedimento='Procedimento sintético', solicitado_por=self.admin_c.user,
            )
            with self.assertRaisesMessage(ValidationError, 'justificativa'):
                svc.change_regulation_priority(self.admin_c.user, request_id=request.pk, priority='URGENTE', justification='')
            with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=Fernet.generate_key().decode()):
                changed = svc.change_regulation_priority(self.admin_c.user, request_id=request.pk,
                    priority='URGENTE', justification='Justificativa sintética de homologação')
            self.assertEqual(changed.prioridade, 'URGENTE')
            audit = m.AuditoriaAcessoSaude.objects.get(
                acao='PRIORIDADE_REGULACAO_ALTERADA', entidade_id=request.pk,
            )
            self.assertNotIn('Justificativa sintética de homologação', str(audit.detalhes))
            self.assertEqual(changed.prioridade_justificativa, 'Justificativa protegida')

    def test_health_configuration_pages_are_available_only_with_module_and_permission(self):
        for slug in ('unidades', 'equipes', 'profissionais', 'agendas', 'atendimentos'):
            response = self.client.get(reverse('rh_municipal_public:saude_registry', args=[slug]))
            self.assertEqual(response.status_code, 200, slug)
        self.client.force_login(self.server_user.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:saude_registry', args=['unidades'])).status_code, 403)
        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:saude_registry', args=['unidades'])).status_code, 403)

    def test_health_setup_forms_reuse_municipal_records_and_audit_changes(self):
        unit_url = reverse('rh_municipal_public:saude_registry', args=['unidades'])
        response = self.client.post(unit_url, {
            'unidade': self.structure[3].pk, 'tipo': 'UBS', 'cnes': '',
            'servicos': '[]', 'ativo': 'on',
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        with tenant_context(self.c):
            health_unit = m.UnidadeSaudeMunicipal.objects.select_related('unidade').get(
                organization=self.c, unidade=self.structure[3],
            )
            self.assertEqual(health_unit.unidade.setor_id, self.structure[2].pk)
            self.assertTrue(m.AuditoriaAcessoSaude.objects.filter(
                organization=self.c, acao='UNIDADE_SAUDE_CONFIGURADA', entidade_id=health_unit.pk,
            ).exists())

        team_url = reverse('rh_municipal_public:saude_registry', args=['equipes'])
        response = self.client.post(team_url, {
            'codigo': 'ESF-01', 'nome': 'Equipe Central', 'tipo': 'ESF',
            'unidade_saude': health_unit.pk, 'microarea': '01', 'ativo': 'on',
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        with tenant_context(self.c):
            team = m.EquipeSaudeMunicipal.objects.get(organization=self.c, codigo='ESF-01')

        professional_url = reverse('rh_municipal_public:saude_registry', args=['profissionais'])
        response = self.client.post(professional_url, {
            'servidor': self.server.pk, 'unidade_saude': health_unit.pk, 'equipe': team.pk,
            'ocupacao': 'Agente de Saúde', 'conselho': '', 'registro_conselho': '',
            'especialidade': '', 'ativo': 'on',
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        with tenant_context(self.c):
            professional = m.ProfissionalSaudeMunicipal.objects.get(organization=self.c, servidor=self.server)

        from datetime import timedelta
        start = timezone.now() + timedelta(days=2)
        agenda_url = reverse('rh_municipal_public:saude_registry', args=['agendas'])
        response = self.client.post(agenda_url, {
            'unidade_saude': health_unit.pk, 'profissional': professional.pk,
            'inicio': start.strftime('%Y-%m-%dT%H:%M'),
            'fim': (start + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M'),
            'capacidade': 2, 'situacao': 'ABERTA',
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        with tenant_context(self.c):
            agenda = m.AgendaSaudeMunicipal.objects.get(organization=self.c, profissional=professional)
        self.assertEqual(agenda.unidade_saude_id, health_unit.pk)

    def test_patient_reference_and_appointment_replay_are_tenant_and_scope_safe(self):
        health_unit = self._health_unit()
        patient = self._citizen()
        # Full-prefecture administrators can assign the public municipal reference unit.
        with tenant_context(self.c):
            patient.unidade = self.structure[3]
            patient.save()
            professional = m.ProfissionalSaudeMunicipal.objects.create(
                organization=self.c, servidor=self.server, unidade_saude=health_unit,
                ocupacao='Profissional sintético',
            )
            start = timezone.now() + timedelta(days=3)
            agenda = m.AgendaSaudeMunicipal.objects.create(
                organization=self.c, unidade_saude=health_unit, profissional=professional,
                inicio=start, fim=start + timedelta(minutes=30), capacidade=1,
            )
            request_id = uuid.uuid4()
            payload = {'agenda_id': agenda.pk, 'citizen_id': patient.pk, 'request_id': request_id}
            first = svc.create_appointment(self.admin_c.user, **payload)
            replay = svc.create_appointment(self.admin_c.user, **payload)
            self.assertEqual(first.pk, replay.pk)
            self.assertEqual(m.AtendimentoSaudeMunicipal.objects.filter(
                organization=self.c, public_id=request_id,
            ).count(), 1)
            self.assertTrue(m.AuditoriaAcessoSaude.objects.filter(
                organization=self.c, acao='ATENDIMENTO_AGENDADO', entidade_id=first.pk,
            ).exists())
            with self.assertRaisesMessage(ValidationError, 'chave deste envio'):
                svc.create_appointment(self.admin_c.user, agenda_id=agenda.pk,
                                       citizen_id=self._citizen().pk, request_id=request_id)

        with tenant_context(self.a):
            self.assertFalse(m.AtendimentoSaudeMunicipal.all_objects.filter(organization=self.a).exists())

    def test_appointment_lifecycle_is_validated_and_audited(self):
        health_unit = self._health_unit()
        patient = self._citizen()
        with tenant_context(self.c):
            professional = m.ProfissionalSaudeMunicipal.objects.create(
                organization=self.c, servidor=self.server, unidade_saude=health_unit,
                ocupacao='Profissional sintético',
            )
            start = timezone.now() + timedelta(days=4)
            agenda = m.AgendaSaudeMunicipal.objects.create(
                organization=self.c, unidade_saude=health_unit, profissional=professional,
                inicio=start, fim=start + timedelta(minutes=30), capacidade=1,
            )
            appointment = svc.create_appointment(
                self.admin_c.user, agenda_id=agenda.pk, citizen_id=patient.pk,
            )
            with self.assertRaisesMessage(ValidationError, 'justificativa'):
                svc.transition_appointment(
                    self.admin_c.user, appointment_id=appointment.pk, status='CANCELADO',
                )
            with self.assertRaisesMessage(ValidationError, 'só pode ser registrada'):
                svc.transition_appointment(
                    self.admin_c.user, appointment_id=appointment.pk, status='FALTOU',
                    justification='Registro sintético',
                )
            started = svc.transition_appointment(
                self.admin_c.user, appointment_id=appointment.pk, status='EM_ATENDIMENTO',
            )
            self.assertIsNotNone(started.iniciado_em)
            with self.assertRaisesMessage(ValidationError, 'não é permitida'):
                svc.transition_appointment(
                    self.admin_c.user, appointment_id=appointment.pk, status='AGENDADO',
                )
            completed = svc.transition_appointment(
                self.admin_c.user, appointment_id=appointment.pk, status='CONCLUIDO',
            )
            self.assertIsNotNone(completed.concluido_em)
            self.assertEqual(completed.status, m.AtendimentoSaudeMunicipal.Status.CONCLUIDO)
            self.assertEqual(m.AuditoriaAcessoSaude.objects.filter(
                organization=self.c, entidade_id=appointment.pk,
                acao='STATUS_ATENDIMENTO_ALTERADO',
            ).count(), 2)

            no_access = self._user('health-status-denied', self.c, self.publico, 'ADMIN')
            with self.assertRaises(PermissionDenied):
                svc.transition_appointment(
                    no_access.user, appointment_id=appointment.pk, status='CANCELADO',
                    justification='Sem permissão',
                )

        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied):
                svc.transition_appointment(
                    self.admin_a.user, appointment_id=appointment.pk, status='CANCELADO',
                    justification='Tenant incorreto',
                )

    def test_unit_scoped_health_access_filters_lists_and_form_choices(self):
        first_unit = self._health_unit()
        with tenant_context(self.c):
            secretary = Secretaria.objects.create(organization=self.c, codigo='SEC-02', nome='Secretaria Norte')
            department = DepartamentoMunicipal.objects.create(organization=self.c, secretaria=secretary, codigo='DEP-02', nome='Departamento Norte')
            sector = SetorMunicipal.objects.create(organization=self.c, departamento=department, codigo='SET-02', nome='Setor Norte')
            municipal_unit = UnidadeMunicipal.objects.create(organization=self.c, setor=sector, codigo='UNI-02', nome='Unidade Norte')
            second_unit = m.UnidadeSaudeMunicipal.objects.create(organization=self.c, unidade=municipal_unit)
            scoped_access = AcessoMunicipal.objects.create(
                membership=self.server_user, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, secretaria=self.structure[0],
                departamento=self.structure[1], setor=self.structure[2], unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=scoped_access, capacidade='saude.units.view')
            PermissaoMunicipal.objects.create(acesso=scoped_access, capacidade='saude.units.manage')
        self.client.force_login(self.server_user.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.get(reverse('rh_municipal_public:saude_registry', args=['unidades']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.structure[3].nome)
        self.assertNotContains(response, municipal_unit.nome)
        with tenant_context(self.c):
            patient_form = PatientForm(actor=self.server_user.user)
            choices = list(patient_form.fields['unidade'].queryset.values_list('pk', flat=True))
        self.assertEqual(choices, [self.structure[3].pk])

    def test_sanitary_establishment_and_inspection_are_audited_scoped_and_idempotent(self):
        key = Fernet.generate_key().decode()
        health_unit, _, professional = self._field_agent('ACS')
        establishment_key = uuid.uuid4()
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=key), tenant_context(self.c):
            data = {
                'request_id': establishment_key, 'contribuinte': None,
                'razao_social': 'Estabelecimento Sanitário Sintético', 'documento': '12345678000199',
                'atividade': 'Comércio de homologação', 'endereco': 'Rua Sintética, 50',
                'secretaria': self.structure[0], 'departamento': self.structure[1],
                'setor': self.structure[2], 'unidade': self.structure[3],
            }
            establishment = svc.configure_sanitary_establishment(self.admin_c.user, data=data)
            replay = svc.configure_sanitary_establishment(self.admin_c.user, data=data)
            self.assertEqual(establishment.pk, replay.pk)
            with self.assertRaisesMessage(ValidationError, 'outros dados'):
                svc.configure_sanitary_establishment(
                    self.admin_c.user, data={**data, 'endereco': 'Endereço divergente'},
                )

            note = 'Observação de inspeção sintética e protegida.'
            operation = uuid.uuid4()
            args = {
                'request_id': operation, 'establishment_id': establishment.pk,
                'professional_id': professional.pk, 'performed_at': timezone.now(),
                'result': 'IRREGULAR', 'return_deadline': timezone.localdate() + timedelta(days=10),
                'observations': note,
            }
            inspection = svc.register_sanitary_inspection(self.admin_c.user, **args)
            inspection_replay = svc.register_sanitary_inspection(self.admin_c.user, **args)
            self.assertEqual(inspection.pk, inspection_replay.pk)
            self.assertNotIn(note.encode(), bytes(inspection.observacoes_cifradas))
            self.assertEqual(Fernet(key.encode()).decrypt(bytes(inspection.observacoes_cifradas)).decode(), note)
            audit = m.AuditoriaAcessoSaude.objects.get(
                organization=self.c, entidade=inspection._meta.label_lower,
                entidade_id=inspection.pk, acao='INSPECAO_SANITARIA_REGISTRADA',
            )
            self.assertEqual(audit.detalhes['request_id'], str(operation))
            self.assertNotIn('observacoes', audit.detalhes)
            with self.assertRaisesMessage(ValidationError, 'outros dados'):
                svc.register_sanitary_inspection(self.admin_c.user, **{**args, 'observations': 'Texto alterado'})

        surveillance_url = reverse('rh_municipal_public:saude_surveillance')
        response = self.client.get(surveillance_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Estabelecimento Sanitário Sintético')
        self.assertContains(response, 'Irregular')
        self.assertNotContains(response, note)
        self.assertIn('no-store', response['Cache-Control'])

    def test_epidemiology_notifications_are_encrypted_audited_and_transitioned(self):
        key = Fernet.generate_key().decode()
        citizen = self._citizen()
        operation = uuid.uuid4()
        sensitive = 'Detalhe clínico sintético que não pode aparecer na listagem.'
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=key), tenant_context(self.c):
            notification = svc.create_epidemiology_notification(
                self.admin_c.user, request_id=operation, citizen_id=citizen.pk,
                code='LOCAL-TESTE', description='Referência de agravo sintética',
                notified_on=timezone.localdate(), details=sensitive,
            )
            replay = svc.create_epidemiology_notification(
                self.admin_c.user, request_id=operation, citizen_id=citizen.pk,
                code='LOCAL-TESTE', description='Referência de agravo sintética',
                notified_on=timezone.localdate(), details=sensitive,
            )
            self.assertEqual(notification.pk, replay.pk)
            self.assertNotIn(sensitive.encode(), bytes(notification.detalhes_cifrados))
            self.assertEqual(Fernet(key.encode()).decrypt(bytes(notification.detalhes_cifrados)).decode(), sensitive)
            audit = m.AuditoriaAcessoSaude.objects.get(
                organization=self.c, entidade=notification._meta.label_lower,
                entidade_id=notification.pk, acao='NOTIFICACAO_EPIDEMIOLOGICA_REGISTRADA',
            )
            self.assertNotIn('detalhes', audit.detalhes)
            self.assertEqual(audit.detalhes['request_id'], str(operation))
            changed = svc.transition_epidemiology_notification(
                self.admin_c.user, notification_id=notification.pk, situation='EM_ANALISE',
                justification='Triagem municipal sintética.',
            )
            self.assertEqual(changed.situacao, 'EM_ANALISE')
            closed = svc.transition_epidemiology_notification(
                self.admin_c.user, notification_id=notification.pk, situation='ENCERRADA',
                justification='Encerramento sintético registrado.',
            )
            self.assertEqual(closed.situacao, 'ENCERRADA')
            with self.assertRaisesMessage(ValidationError, 'não pode ser reaberta'):
                svc.transition_epidemiology_notification(
                    self.admin_c.user, notification_id=notification.pk, situation='ABERTA',
                    justification='Tentativa de reabertura.',
                )
            self.assertEqual(m.AuditoriaAcessoSaude.objects.filter(
                organization=self.c, entidade_id=notification.pk,
                acao='SITUACAO_NOTIFICACAO_EPI_ALTERADA',
            ).count(), 2)

        response = self.client.get(reverse('rh_municipal_public:saude_surveillance'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LOCAL-TESTE')
        self.assertNotContains(response, sensitive)
        self.assertNotContains(response, citizen.nome)

    def test_surveillance_view_permission_does_not_grant_management_or_other_tenant_access(self):
        with tenant_context(self.c):
            membership = self._user('health-surveillance-view', self.c, self.publico, 'TECNICO')
            access = AcessoMunicipal.objects.create(
                membership=membership, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, secretaria=self.structure[0],
                departamento=self.structure[1], setor=self.structure[2], unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='saude.sanitary.view')
        url = reverse('rh_municipal_public:saude_surveillance')
        self.client.force_login(membership.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Cadastrar estabelecimento')
        self.assertEqual(self.client.post(url, {'action': 'establishment'}).status_code, 403)

        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_surveillance_rendered_forms_create_records_without_exposing_restricted_details(self):
        key = Fernet.generate_key().decode()
        _, _, professional = self._field_agent('ACS')
        url = reverse('rh_municipal_public:saude_surveillance')
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=key):
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200)
            establishment_payload = {
                'action': 'establishment', 'request_id': str(uuid.uuid4()), 'contribuinte': '',
                'razao_social': 'Estabelecimento pelo formulário', 'documento': '12345678000199',
                'atividade': 'Atividade sintética', 'endereco': 'Rua de homologação, 1',
                'secretaria': self.structure[0].pk, 'departamento': self.structure[1].pk,
                'setor': self.structure[2].pk, 'unidade': self.structure[3].pk,
            }
            self.assertEqual(self.client.post(url, establishment_payload).status_code, 302)
            with tenant_context(self.c):
                establishment = m.EstabelecimentoSanitarioMunicipal.objects.get(
                    organization=self.c, razao_social='Estabelecimento pelo formulário',
                )
            inspection_note = 'Detalhe confidencial sintético da inspeção.'
            inspection_payload = {
                'action': 'inspection', 'request_id': str(uuid.uuid4()),
                'estabelecimento': establishment.pk, 'realizada_por': professional.pk,
                'realizada_em': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
                'resultado': 'REGULAR', 'prazo_retorno': '', 'observacoes': inspection_note,
            }
            self.assertEqual(self.client.post(url, inspection_payload).status_code, 302)
            epi_note = 'Detalhes epidemiológicos sintéticos e restritos.'
            epi_payload = {
                'action': 'notification', 'request_id': str(uuid.uuid4()), 'cidadao': '',
                'codigo_agravo': 'LOCAL-001', 'descricao_agravo': 'Referência local sintética',
                'notificada_em': timezone.localdate().isoformat(), 'detalhes': epi_note,
            }
            self.assertEqual(self.client.post(url, epi_payload).status_code, 302)
            with tenant_context(self.c):
                inspection = m.InspecaoSanitariaMunicipal.objects.get(
                    organization=self.c, estabelecimento=establishment,
                )
                notification = m.NotificacaoEpidemiologicaMunicipal.objects.get(
                    organization=self.c, codigo_agravo='LOCAL-001',
                )
                self.assertNotIn(inspection_note.encode(), bytes(inspection.observacoes_cifradas))
                self.assertNotIn(epi_note.encode(), bytes(notification.detalhes_cifrados))
            listing = self.client.get(url)
            self.assertEqual(listing.status_code, 200)
            self.assertContains(listing, 'Estabelecimento pelo formulário')
            self.assertContains(listing, 'LOCAL-001')
            self.assertNotContains(listing, inspection_note)
            self.assertNotContains(listing, epi_note)

    def test_tfd_sensitive_payload_is_encrypted_and_transitions_are_audited(self):
        citizen = self._citizen()
        request_id = uuid.uuid4()
        destination = 'Hospital Sintético - cidade de teste'
        treatment = 'Tratamento clínico privado sintético'
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=Fernet.generate_key().decode()), tenant_context(self.c):
            row = svc.create_tfd_request(
                self.admin_c.user, request_id=request_id, citizen_id=citizen.pk,
                destination=destination, treatment=treatment, accompaniment='Acompanhante sintético',
            )
            replay = svc.create_tfd_request(
                self.admin_c.user, request_id=request_id, citizen_id=citizen.pk,
                destination=destination, treatment=treatment, accompaniment='Acompanhante sintético',
            )
            self.assertEqual(row.pk, replay.pk)
            row.refresh_from_db()
            self.assertEqual(row.destino, 'Dados protegidos')
            self.assertEqual(row.tratamento, 'Dados protegidos')
            ciphertext = row.documentos[0]['payload']
            self.assertNotIn(destination, ciphertext)
            self.assertNotIn(treatment, ciphertext)
            self.assertEqual(m.TFDMunicipal.objects.filter(organization=self.c).count(), 1)
            svc.transition_tfd_request(
                self.admin_c.user, request_id=row.pk, status='AUTORIZADA',
                justification='Autorização sintética para teste',
            )
            svc.transition_tfd_request(
                self.admin_c.user, request_id=row.pk, status='CONCLUIDA',
                justification='Conclusão sintética',
            )
            with self.assertRaises(ValidationError):
                svc.transition_tfd_request(
                    self.admin_c.user, request_id=row.pk, status='AUTORIZADA',
                    justification='Tentativa de reabrir',
                )
            row.refresh_from_db()
            self.assertEqual(row.status, 'CONCLUIDA')
            self.assertEqual(m.AuditoriaAcessoSaude.objects.filter(
                organization=self.c, entidade=row._meta.label_lower, entidade_id=row.pk,
            ).count(), 3)
        with tenant_context(self.a):
            self.assertFalse(m.TFDMunicipal.objects.filter(pk=row.pk).exists())

    def test_production_record_is_tenant_scoped_idempotent_and_never_transmitted(self):
        health_unit = self._health_unit()
        request_id = uuid.uuid4()
        with tenant_context(self.c):
            row = svc.register_sus_production(
                self.admin_c.user, request_id=request_id, competence='2026-10',
                record_type=m.RegistroProducaoSUS.Tipo.AIH_RASCUNHO,
                health_unit_id=health_unit.pk, procedure_code='LOCAL-SINTETICO', quantity=3,
            )
            replay = svc.register_sus_production(
                self.admin_c.user, request_id=request_id, competence='2026-10',
                record_type=m.RegistroProducaoSUS.Tipo.AIH_RASCUNHO,
                health_unit_id=health_unit.pk, procedure_code='LOCAL-SINTETICO', quantity=3,
            )
            self.assertEqual(row.pk, replay.pk)
            self.assertEqual(row.status_transmissao, 'NAO_TRANSMITIDO')
            self.assertEqual(m.RegistroProducaoSUS.objects.filter(organization=self.c).count(), 1)
        with tenant_context(self.a):
            self.assertFalse(m.RegistroProducaoSUS.objects.filter(pk=row.pk).exists())
            other = self._user('health-production-no-access', self.a, self.publico, 'ADMIN')
            with self.assertRaises(PermissionDenied):
                svc.register_sus_production(
                    other.user, request_id=uuid.uuid4(), competence='2026-10',
                    record_type=m.RegistroProducaoSUS.Tipo.PROCEDIMENTO,
                    health_unit_id=health_unit.pk, quantity=1,
                )

    def test_tfd_and_production_screens_require_distinct_municipal_capabilities(self):
        tfd = self.client.get(reverse('rh_municipal_public:saude_tfd'))
        production = self.client.get(reverse('rh_municipal_public:saude_production'))
        self.assertEqual(tfd.status_code, 200)
        self.assertEqual(production.status_code, 200)
        self.assertContains(production, 'Sem transmissão oficial.')
        with tenant_context(self.c):
            membership = self._user('health-tfd-view-only', self.c, self.publico, 'TECNICO')
            access = AcessoMunicipal.objects.create(
                membership=membership, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, secretaria=self.structure[0],
                departamento=self.structure[1], setor=self.structure[2], unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='saude.tfd.view')
        self.client.force_login(membership.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(self.client.get(reverse('rh_municipal_public:saude_tfd')).status_code, 200)
        self.assertEqual(self.client.post(
            reverse('rh_municipal_public:saude_tfd'), {'action': 'create'},
        ).status_code, 403)
        self.assertEqual(self.client.get(reverse('rh_municipal_public:saude_production')).status_code, 403)

    def test_regulation_request_slot_capacity_schedule_and_attendance_are_audited(self):
        health_unit = self._health_unit()
        first_citizen = self._citizen()
        second_citizen = self._citizen()
        request_id = uuid.uuid4()
        slot_id = uuid.uuid4()
        operation_id = uuid.uuid4()
        procedure = 'Consulta especializada sintética'
        key = Fernet.generate_key().decode()
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=key), tenant_context(self.c):
            referral = svc.create_regulation_request(
                self.admin_c.user, request_id=request_id, citizen_id=first_citizen.pk,
                origin_unit_id=health_unit.pk, destination_unit_id=health_unit.pk,
                procedure=procedure, priority='URGENTE', justification='Justificativa clínica privada sintética',
            )
            self.assertEqual(svc.create_regulation_request(
                self.admin_c.user, request_id=request_id, citizen_id=first_citizen.pk,
                origin_unit_id=health_unit.pk, destination_unit_id=health_unit.pk,
                procedure=procedure, priority='URGENTE', justification='Justificativa clínica privada sintética',
            ).pk, referral.pk)
            self.assertNotIn('Justificativa clínica privada sintética'.encode('utf-8'), bytes(referral.justificativa_cifrada))
            slot = svc.create_regulation_slot(
                self.admin_c.user, request_id=slot_id, health_unit_id=health_unit.pk,
                procedure=procedure, starts_at=timezone.now() + timedelta(days=2), capacity=1,
            )
            self.assertEqual(svc.create_regulation_slot(
                self.admin_c.user, request_id=slot_id, health_unit_id=health_unit.pk,
                procedure=procedure, starts_at=slot.inicio, capacity=1,
            ).pk, slot.pk)
            link = svc.schedule_regulation_request(
                self.admin_c.user, operation_id=operation_id,
                request_id=referral.pk, slot_id=slot.pk,
            )
            self.assertEqual(svc.schedule_regulation_request(
                self.admin_c.user, operation_id=operation_id,
                request_id=referral.pk, slot_id=slot.pk,
            ).pk, link.pk)
            referral.refresh_from_db()
            self.assertEqual(referral.status, 'AGENDADA')
            second = svc.create_regulation_request(
                self.admin_c.user, request_id=uuid.uuid4(), citizen_id=second_citizen.pk,
                origin_unit_id=health_unit.pk, destination_unit_id=health_unit.pk,
                procedure=procedure, priority='ROTINA', justification='Outra justificativa sintética',
            )
            with self.assertRaisesMessage(ValidationError, 'capacidade'):
                svc.schedule_regulation_request(
                    self.admin_c.user, operation_id=uuid.uuid4(), request_id=second.pk, slot_id=slot.pk,
                )
            completed = svc.transition_regulation_schedule(
                self.admin_c.user, schedule_id=link.pk, situation='ATENDIDO',
                justification='Atendimento sintético concluído',
            )
            self.assertEqual(completed.situacao, 'ATENDIDO')
            referral.refresh_from_db()
            link.refresh_from_db()
            link.atendimento.refresh_from_db()
            self.assertEqual(referral.status, 'ATENDIDA')
            self.assertEqual(link.atendimento.status, 'CONCLUIDO')
            audit = m.AuditoriaAcessoSaude.objects.get(
                organization=self.c, entidade=link._meta.label_lower, entidade_id=link.pk,
                acao='REGULACAO_AGENDAMENTO_ALTERADO',
            )
            self.assertNotIn('Atendimento sintético concluído', audit.justificativa)
            self.assertIn('justificativa_cifrada', audit.detalhes)
            with self.assertRaises(ValidationError):
                svc.transition_regulation_schedule(
                    self.admin_c.user, schedule_id=link.pk, situation='CANCELADO',
                    justification='Não deve reabrir nem substituir conclusão',
                )
        with tenant_context(self.a):
            self.assertFalse(m.SolicitacaoRegulacaoSaude.objects.filter(pk=referral.pk).exists())
            self.assertFalse(m.AgendamentoRegulacaoSaude.objects.filter(pk=link.pk).exists())

    def test_regulation_page_is_scoped_and_view_permission_cannot_manage(self):
        url = reverse('rh_municipal_public:saude_regulation')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(url), 'Regulação e fila municipal')
        with tenant_context(self.c):
            membership = self._user('health-regulation-view', self.c, self.publico, 'TECNICO')
            access = AcessoMunicipal.objects.create(
                membership=membership, papel=AcessoMunicipal.Papel.PROFISSIONAL,
                escopo=AcessoMunicipal.Escopo.UNIDADE, secretaria=self.structure[0],
                departamento=self.structure[1], setor=self.structure[2], unidade=self.structure[3],
                atribuido_por=self.admin_c.user,
            )
            PermissaoMunicipal.objects.create(acesso=access, capacidade='saude.regulation.view')
        self.client.force_login(membership.user)
        session = self.client.session
        session['organization_id'] = self.c.pk
        session.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Enviar para fila')
        self.assertEqual(self.client.post(url, {'action': 'create_request'}).status_code, 403)
        self.client.force_login(self.admin_a.user)
        session = self.client.session
        session['organization_id'] = self.a.pk
        session.save()
        self.assertEqual(self.client.get(url).status_code, 403)
