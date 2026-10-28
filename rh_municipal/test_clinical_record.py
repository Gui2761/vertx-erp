import uuid

from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from platform_core.context import tenant_context
from platform_core.models import ERPProductModule, OrganizationERP
from platform_core.saas_models import AssinaturaSaaS, PlanoProdutoModulo, PlanoSaaS
from . import clinical_services as svc
from . import phase_g_models as health
from . import phase_g_services as health_svc
from .models import AcessoMunicipal, PermissaoMunicipal, UnidadeMunicipal
from .tests import MunicipalFixtures

VIEW = ('saude.records.view', 'saude.patients.view')
SENSITIVE = (*VIEW, 'saude.records.sensitive')
CREATE = (*SENSITIVE, 'saude.records.create')
EDIT = (*SENSITIVE, 'saude.records.edit')


@override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=Fernet.generate_key().decode())
class ClinicalRecordTests(MunicipalFixtures):
    def setUp(self):
        super().setUp()
        self.plan = PlanoSaaS.objects.create(slug='clinical-test', nome='Saúde sintética', erp=self.publico)
        for code in ('gestao_publica', 'saude_sus'):
            PlanoProdutoModulo.objects.create(plano=self.plan, modulo=ERPProductModule.objects.get(erp=self.publico, code=code))
        AssinaturaSaaS.objects.create(organization=self.c, plano=self.plan, status='ATIVA')
        with tenant_context(self.c):
            self.access = AcessoMunicipal.objects.create(membership=self.admin_c, papel='ADMIN_PREFEITURA',
                                                       escopo='PREFEITURA', atribuido_por=self.admin_c.user)
            self.unit = health_svc.configure_health_unit(self.admin_c.user, data={'unidade': self.structure[3], 'tipo': 'UBS'})
            self.team = health_svc.configure_health_team(self.admin_c.user, data={
                'codigo': 'CLIN-TEAM', 'nome': 'Equipe clínica sintética', 'tipo': 'ESF', 'unidade_saude': self.unit,
            })
            server = self._server(self.admin_c.user, matricula='CLIN-001')
            self.professional = health_svc.configure_health_professional(self.admin_c.user, data={
                'servidor': server, 'unidade_saude': self.unit, 'equipe': self.team, 'ocupacao': 'Profissional sintético',
            })
            self.patient = health_svc.create_patient(self.admin_c.user, data={
                'nome': 'PACIENTE_CLINICO_RESTRITO', 'unidade': self.unit.unidade, 'cpf': '00000000001',
            })
        self.actor = self.admin_c.user
        self.chart_url = reverse('rh_municipal_public:saude_citizen_chart', args=[self.patient.public_id])
        self.begin_url = reverse('rh_municipal_public:saude_encounter_begin', args=[self.patient.public_id])

    def begin(self):
        return svc.begin_encounter(self.actor, patient_id=self.patient.public_id, unit_id=self.unit.pk,
                                   professional_id=self.professional.pk, request_id=uuid.uuid4())

    def event(self, encounter, **overrides):
        data = {'request_id': uuid.uuid4(), 'tipo': 'evolucao', 'texto': 'CONTEUDO_CLINICO_RESTRITO', **overrides}
        return svc.record_event(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id, data=data)

    def restrict(self, capabilities):
        self.access.papel = 'PROFISSIONAL'
        self.access.escopo = 'UNIDADE'
        self.access.unidade = self.unit.unidade
        self.access.save()
        for code in capabilities:
            PermissaoMunicipal.objects.create(acesso=self.access, capacidade=code, permitido=True)

    def action_url(self, encounter):
        return reverse('rh_municipal_public:saude_clinical_action', args=[self.patient.public_id, encounter.public_id])

    def read(self, encounter, **kwargs):
        return svc.citizen_chart(self.actor, patient_id=self.patient.public_id,
                                 encounter_id=encounter.public_id, purpose='continuidade', **kwargs)

    def test_walk_in_encounter_reuses_patient_unit_professional_and_is_idempotent(self):
        with tenant_context(self.c):
            request = uuid.uuid4()
            args = dict(patient_id=self.patient.public_id, unit_id=self.unit.pk,
                        professional_id=self.professional.pk, request_id=request)
            first = svc.begin_encounter(self.actor, **args)
            self.assertEqual(first.pk, svc.begin_encounter(self.actor, **args).pk)
            self.assertEqual(first.status, 'EM_ATENDIMENTO')
            self.assertEqual(first.cidadao_id, self.patient.pk)
            self.assertEqual(first.unidade_id, self.unit.unidade_id)
            self.assertTrue(health.AuditoriaAcessoSaude.objects.filter(acao='ATENDIMENTO_CLINICO_INICIADO').exists())

    def test_all_clinical_types_and_vitals_round_trip_encrypted_with_provenance(self):
        with tenant_context(self.c):
            encounter = self.begin()
            for kind in ('acolhimento', 'medico', 'enfermagem', 'evolucao', 'exame', 'encaminhamento'):
                self.event(encounter, tipo=kind, queixa='QUEIXA_RESTRITA', avaliacao='AVALIACAO_RESTRITA',
                           diagnostico='DIAGNOSTICO_RESTRITO', cid='', procedimentos='Procedimento informado',
                           solicitacao='SOLICITACAO_RESTRITA', destino='Serviço informado',
                           pressao_sistolica='120', pressao_diastolica='80', temperatura='36.5', saturacao='98')
            chart = self.read(encounter)
            events = list(chart['events'])
            self.assertEqual(len(events), 6)
            self.assertEqual([e.clinical['kind'] for e in events], ['acolhimento', 'medico', 'enfermagem', 'evolucao', 'exame', 'encaminhamento'])
            self.assertEqual(events[0].clinical['data']['saturacao'], '98')
            self.assertEqual(events[0].clinical['data']['cid'], '')
            self.assertEqual(events[0].clinical['professional']['id'], self.professional.pk)
            self.assertEqual(events[0].clinical['team']['id'], self.team.pk)
            self.assertEqual(events[0].clinical['unit']['id'], self.unit.pk)
            for entry in health.EvolucaoClinicaMunicipal.objects.all():
                self.assertNotIn(b'RESTRITO', bytes(entry.conteudo_cifrado))

    def test_metadata_does_not_decrypt_and_clinical_read_requires_purpose_and_is_audited(self):
        with tenant_context(self.c):
            encounter = self.begin()
            self.event(encounter)
        page = self.client.get(self.chart_url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'CONTEUDO_CLINICO_RESTRITO')
        self.assertIn('no-store', page['Cache-Control'])
        page = self.client.get(self.chart_url, {'atendimento': encounter.public_id, 'purpose': 'continuidade'})
        self.assertContains(page, 'CONTEUDO_CLINICO_RESTRITO')
        with tenant_context(self.c):
            self.assertTrue(health.AuditoriaAcessoSaude.objects.filter(acao='PRONTUARIO_CIDADAO_ABERTO', paciente_id=self.patient.pk).exists())
            self.assertTrue(health.AuditoriaAcessoSaude.objects.filter(acao='PRONTUARIO_ACESSADO').exists())
            self.assertNotIn('CONTEUDO_CLINICO_RESTRITO', str(list(health.AuditoriaAcessoSaude.objects.values('detalhes', 'justificativa'))))

    def test_read_only_user_cannot_post_to_new_or_legacy_routes_even_with_sensitive_access(self):
        with tenant_context(self.c):
            encounter = self.begin()
            entry = self.event(encounter)
            self.restrict(SENSITIVE)
        page = self.client.get(self.chart_url, {'purpose': 'continuidade'})
        self.assertContains(page, 'CONTEUDO_CLINICO_RESTRITO')
        self.assertNotContains(page, 'Salvar registro protegido')
        for url, data in (
            (self.begin_url, {}),
            (self.action_url(encounter), {'action': 'event'}),
            (self.action_url(encounter), {'action': 'conclude'}),
            (reverse('rh_municipal_public:saude_charts'), {'documento': self.patient.cpf}),
            (reverse('rh_municipal_public:saude_clinical_record', args=[encounter.pk]), {'action': 'read', 'entry_id': entry.pk}),
        ):
            self.assertEqual(self.client.post(url, data).status_code, 403)
        with tenant_context(self.c):
            self.assertEqual(health.EvolucaoClinicaMunicipal.objects.count(), 1)

    def test_operational_reader_cannot_retrieve_clinical_content(self):
        with tenant_context(self.c):
            encounter = self.begin()
            self.event(encounter)
            self.restrict(VIEW)
        self.assertEqual(self.client.get(self.chart_url).status_code, 200)
        self.assertEqual(self.client.get(self.chart_url, {'purpose': 'continuidade'}).status_code, 403)

    def test_create_permission_does_not_allow_correction_or_conclusion(self):
        with tenant_context(self.c):
            encounter = self.begin()
            entry = self.event(encounter)
            self.restrict(CREATE)
            with self.assertRaises(PermissionDenied):
                self.event(encounter, corrige=entry.public_id, motivo='Retificação sintética')
            with self.assertRaises(PermissionDenied):
                svc.conclude_encounter(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id)

    def test_edit_only_preserves_original_creates_correction_and_cannot_create_new_entries(self):
        with tenant_context(self.c):
            encounter = self.begin()
            original = self.event(encounter)
            ciphertext = bytes(original.conteudo_cifrado)
            self.restrict(EDIT)
            corrected = self.event(encounter, corrige=original.public_id, motivo='MOTIVO_CLINICO_PRIVADO', texto='CORRECAO_PRIVADA')
            original.refresh_from_db()
            self.assertEqual(bytes(original.conteudo_cifrado), ciphertext)
            self.assertEqual(corrected.retifica_id, original.pk)
            with self.assertRaises(PermissionDenied):
                self.event(encounter)
            with self.assertRaises(ValidationError):
                self.event(encounter, corrige=original.public_id, motivo='Outra correção')
            self.assertTrue(health.AuditoriaAcessoSaude.objects.filter(acao='REGISTRO_CLINICO_RETIFICADO').exists())
            audit = str(list(health.AuditoriaAcessoSaude.objects.values('detalhes', 'justificativa')))
            self.assertNotIn('MOTIVO_CLINICO_PRIVADO', audit)

    def test_event_request_replay_is_idempotent_and_conflicting_payload_is_rejected(self):
        with tenant_context(self.c):
            encounter = self.begin()
            operation = uuid.uuid4()
            entry = self.event(encounter, request_id=operation)
            self.assertEqual(self.event(encounter, request_id=operation).pk, entry.pk)
            with self.assertRaises(ValidationError):
                self.event(encounter, request_id=operation, texto='Outro conteúdo')
            self.assertEqual(health.EvolucaoClinicaMunicipal.objects.count(), 1)

    def test_prescriptions_use_existing_models_encrypt_names_dosage_and_instructions(self):
        with tenant_context(self.c):
            encounter = self.begin()
            data = {'request_id': uuid.uuid4(), 'medicamento': 'MEDICAMENTO_PRIVADO', 'quantidade': '2',
                    'posologia': 'POSOLOGIA_PRIVADA', 'orientacao': 'ORIENTACAO_PRIVADA'}
            entry = svc.prescribe(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id, data=data)
            self.assertEqual(svc.prescribe(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id, data=data).pk, entry.pk)
            item = health.ItemPrescricaoSaude.objects.get()
            self.assertEqual(item.medicamento_nome, '')
            self.assertNotIn(b'MEDICAMENTO_PRIVADO', bytes(item.medicamento_nome_cifrado))
            self.assertNotIn(b'POSOLOGIA_PRIVADA', bytes(item.posologia_cifrada))
            prescription = item.prescricao
            self.assertNotIn(b'ORIENTACAO_PRIVADA', bytes(prescription.orientacao_cifrada))
            chart = self.read(encounter)
            self.assertEqual(chart['prescriptions'][0].clinical_items[0]['medicamento'], 'MEDICAMENTO_PRIVADO')
            self.assertEqual(health.PrescricaoSaudeMunicipal.objects.count(), 1)

    def test_prescription_cancellation_is_separate_permission_and_preserves_history(self):
        with tenant_context(self.c):
            encounter = self.begin()
            svc.prescribe(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id,
                          data={'request_id': uuid.uuid4(), 'medicamento': 'Sintético', 'quantidade': 1, 'posologia': 'Informada'})
            prescription = health.PrescricaoSaudeMunicipal.objects.get()
            svc.cancel_prescription(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id,
                                    prescription_id=prescription.public_id, reason='MOTIVO_CANCELAMENTO_PRIVADO')
            prescription.refresh_from_db()
            self.assertEqual(prescription.status, 'CANCELADA')
            self.assertEqual(health.EvolucaoClinicaMunicipal.objects.count(), 2)
            self.assertNotIn('MOTIVO_CANCELAMENTO_PRIVADO', str(list(health.AuditoriaAcessoSaude.objects.values('detalhes', 'justificativa'))))

    def test_document_is_encrypted_download_is_private_audited_and_not_in_metadata(self):
        content = b'%PDF-1.4\nDOCUMENTO_CLINICO_SINTETICO\n%%EOF'
        with tenant_context(self.c):
            encounter = self.begin()
            entry = svc.attach_document(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id,
                                        title='DOCUMENTO_RESTRITO', uploaded_file=SimpleUploadedFile('private.pdf', content), request_id=uuid.uuid4())
            self.assertNotIn(content, bytes(entry.conteudo_cifrado))
        self.assertNotContains(self.client.get(self.chart_url), 'DOCUMENTO_RESTRITO')
        url = reverse('rh_municipal_public:saude_clinical_document', args=[self.patient.public_id, entry.public_id])
        response = self.client.get(url)
        self.assertEqual(response.content, content)
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        with tenant_context(self.c):
            self.assertTrue(health.AuditoriaAcessoSaude.objects.filter(acao='DOCUMENTO_CLINICO_BAIXADO').exists())

    def test_invalid_or_oversized_documents_do_not_create_records(self):
        with tenant_context(self.c):
            encounter = self.begin()
            for content in (b'not a PDF', b'%PDF-'+b'x'*svc.MAX_DOCUMENT):
                with self.assertRaises(ValidationError):
                    svc.attach_document(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id,
                                        title='Documento', uploaded_file=SimpleUploadedFile('file.pdf', content), request_id=uuid.uuid4())
            self.assertFalse(health.EvolucaoClinicaMunicipal.objects.exists())

    def test_closed_encounter_rejects_new_clinical_content(self):
        with tenant_context(self.c):
            encounter = self.begin()
            self.event(encounter)
            svc.conclude_encounter(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id)
            encounter.refresh_from_db()
            self.assertEqual(encounter.status, 'CONCLUIDO')
            self.assertIsNotNone(encounter.concluido_em)
            with self.assertRaises(ValidationError):
                self.event(encounter)

    def test_inactive_or_unlinked_professional_cannot_write(self):
        with tenant_context(self.c):
            encounter = self.begin()
            self.professional.ativo = False
            self.professional.save()
            with self.assertRaises(PermissionDenied):
                self.event(encounter)
            self.assertFalse(health.EvolucaoClinicaMunicipal.objects.exists())

    def test_missing_key_or_tampered_cipher_fails_closed_without_plaintext(self):
        with tenant_context(self.c):
            encounter = self.begin()
            entry = self.event(encounter)
            with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=''):
                with self.assertRaises(ValidationError):
                    self.event(encounter)
                with self.assertRaises(ValidationError):
                    self.read(encounter)
            entry.conteudo_cifrado = b'invalid'
            entry.save(update_fields=['conteudo_cifrado'])
        page = self.client.get(self.chart_url, {'purpose': 'continuidade'})
        self.assertEqual(page.status_code, 400)
        self.assertNotContains(page, 'CONTEUDO_CLINICO_RESTRITO', status_code=400)

    def test_direct_foreign_patient_encounter_and_document_ids_are_denied(self):
        with tenant_context(self.c):
            encounter = self.begin()
            entry = svc.attach_document(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id,
                                        title='Privado', uploaded_file=SimpleUploadedFile('a.pdf', b'%PDF-1.4 test'), request_id=uuid.uuid4())
        OrganizationERP.objects.create(organization=self.b, erp=self.publico)
        AssinaturaSaaS.objects.create(organization=self.b, plano=self.plan, status='ATIVA')
        membership = self._user('clinical-other-tenant', self.b, self.publico, 'ADMIN')
        with tenant_context(self.b):
            AcessoMunicipal.objects.create(membership=membership, papel='ADMIN_PREFEITURA', escopo='PREFEITURA', atribuido_por=membership.user)
            with self.assertRaises(PermissionDenied):
                svc.citizen_chart(membership.user, patient_id=self.patient.public_id, encounter_id=encounter.public_id, purpose='continuidade')
            with self.assertRaises(PermissionDenied):
                svc.download_document(membership.user, patient_id=self.patient.public_id, entry_id=entry.public_id)
        self.client.force_login(membership.user)
        session = self.client.session
        session['organization_id'] = self.b.pk
        session.save()
        self.assertEqual(self.client.get(self.chart_url).status_code, 403)
        self.assertEqual(self.client.post(self.action_url(encounter), {'action': 'event'}).status_code, 403)

    def test_other_patient_encounter_cannot_be_injected_into_current_chart(self):
        with tenant_context(self.c):
            other = health_svc.create_patient(self.actor, data={'nome': 'OUTRO_PACIENTE_PRIVADO', 'unidade': self.unit.unidade})
            encounter = svc.begin_encounter(self.actor, patient_id=other.public_id, unit_id=self.unit.pk,
                                             professional_id=self.professional.pk, request_id=uuid.uuid4())
        self.assertEqual(self.client.get(self.chart_url, {'atendimento': encounter.public_id}).status_code, 403)

    def test_broad_operational_scope_does_not_expand_sensitive_unit_scope(self):
        with tenant_context(self.c):
            second = UnidadeMunicipal.objects.create(organization=self.c, setor=self.structure[2], codigo='CLIN-U2', nome='Outra UBS')
            unit = health_svc.configure_health_unit(self.actor, data={'unidade': second, 'tipo': 'UBS'})
            encounter = health.AtendimentoSaudeMunicipal.objects.create(
                organization=self.c, cidadao=self.patient, unidade_saude=unit, criado_por=self.actor,
            )
            self.restrict(SENSITIVE)
            access = AcessoMunicipal.objects.create(membership=self.admin_c, papel='ADMIN_SECRETARIA',
                escopo='SECRETARIA', secretaria=self.structure[0], atribuido_por=self.actor)
            PermissaoMunicipal.objects.create(acesso=access, capacidade='saude.records.view', permitido=True)
            with self.assertRaises(PermissionDenied):
                svc.citizen_chart(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id, purpose='continuidade')

    def test_membership_product_and_module_are_revalidated(self):
        with tenant_context(self.c):
            self.begin()
            module = PlanoProdutoModulo.objects.get(plano=self.plan, modulo__code='saude_sus')
            module.delete()
            with self.assertRaises(PermissionDenied):
                svc.citizen_chart(self.actor, patient_id=self.patient.public_id)
        self.assertEqual(self.client.get(self.chart_url).status_code, 403)

    def test_real_forms_create_encounter_and_structured_note(self):
        response = self.client.post(self.begin_url, {'request_id': str(uuid.uuid4()), 'unidade': self.unit.pk, 'profissional': self.professional.pk})
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.c):
            encounter = health.AtendimentoSaudeMunicipal.objects.get(cidadao=self.patient)
        response = self.client.post(self.action_url(encounter), {'action': 'event', 'request_id': str(uuid.uuid4()), 'tipo': 'acolhimento', 'queixa': 'QUEIXA_NO_FORMULARIO'})
        self.assertEqual(response.status_code, 302)
        response = self.client.get(self.chart_url, {'purpose': 'assistencia'})
        self.assertContains(response, 'QUEIXA_NO_FORMULARIO')

    def test_invalid_vitals_and_requests_are_rejected_without_writing(self):
        with tenant_context(self.c):
            encounter = self.begin()
            with self.assertRaises(ValidationError):
                self.event(encounter, saturacao='101')
            with self.assertRaises(ValidationError):
                self.event(encounter, tipo='exame', solicitacao='')
            self.assertFalse(health.EvolucaoClinicaMunicipal.objects.exists())
        response = self.client.get(self.chart_url, {'atendimento': 'not-a-uuid'})
        self.assertEqual(response.status_code, 400)

    def test_clinical_output_is_escaped_and_never_in_dashboard(self):
        with tenant_context(self.c):
            encounter = self.begin()
            self.event(encounter, texto='<script>CLINICAL_SCRIPT</script>')
        response = self.client.get(self.chart_url, {'purpose': 'continuidade'})
        self.assertContains(response, '&lt;script&gt;CLINICAL_SCRIPT&lt;/script&gt;')
        self.assertNotContains(response, '<script>CLINICAL_SCRIPT</script>')
        response = self.client.get(reverse('rh_municipal_public:saude_home'))
        self.assertNotContains(response, 'PACIENTE_CLINICO_RESTRITO')
        self.assertNotContains(response, 'CLINICAL_SCRIPT')

    def test_service_workers_explicitly_bypass_clinical_routes(self):
        response = self.client.get(reverse('rh_municipal_public:saude_worker'))
        self.assertContains(response, "p.startsWith('/gestao-publica/saude/prontuarios/')")
        self.assertContains(response, "p.endsWith('/prontuario/')")
        self.assertNotContains(response, 'caches.open')

    def test_csrf_and_http_methods_protect_clinical_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        session = client.session
        session['organization_id'] = self.c.pk
        session.save()
        self.assertEqual(client.post(self.begin_url, {}).status_code, 403)
        self.assertEqual(self.client.get(self.begin_url).status_code, 405)
        self.assertEqual(self.client.post(self.chart_url, {}).status_code, 405)

    def test_reference_unit_mismatch_is_rejected_and_snapshot_is_immutable(self):
        with tenant_context(self.c):
            encounter = self.begin()
            self.event(encounter)
            self.team.nome = 'Equipe renomeada'
            self.team.save()
            self.assertEqual(self.read(encounter)['events'][0].clinical['team']['nome'], 'Equipe clínica sintética')
            self.patient.unidade = None
            self.patient.save()
            with self.assertRaises(ValidationError):
                self.begin()

    def test_scheduled_encounter_is_started_without_creating_duplicate_visit(self):
        with tenant_context(self.c):
            encounter = health.AtendimentoSaudeMunicipal.objects.create(
                organization=self.c, cidadao=self.patient, unidade_saude=self.unit,
                profissional=self.professional, criado_por=self.actor,
            )
            svc.start_scheduled_encounter(self.actor, patient_id=self.patient.public_id, encounter_id=encounter.public_id)
            self.event(encounter)
            encounter.refresh_from_db()
            self.assertEqual(encounter.status, 'EM_ATENDIMENTO')
            self.assertEqual(health.AtendimentoSaudeMunicipal.objects.count(), 1)

    def test_membership_and_product_revocation_block_record_access(self):
        with tenant_context(self.c):
            self.admin_c.status = 'INATIVO'
            self.admin_c.save()
            with self.assertRaises(PermissionDenied):
                svc.citizen_chart(self.actor, patient_id=self.patient.public_id)
            self.admin_c.status = 'ATIVO'
            self.admin_c.save()
            access = OrganizationERP.objects.get(organization=self.c, erp=self.publico)
            access.enabled = False
            access.save()
            with self.assertRaises(PermissionDenied):
                svc.citizen_chart(self.actor, patient_id=self.patient.public_id)

    def test_existing_family_link_is_reused_without_exposing_household_address(self):
        from . import primary_care_services
        with tenant_context(self.c):
            family = primary_care_services.create_family(self.actor, data={
                'codigo': 'F-CLIN', 'endereco': 'ENDERECO_FAMILIAR_RESTRITO', 'unidade_saude': self.unit,
            })
            primary_care_services.link_family_member(self.actor, family_id=family.pk, citizen_public_id=self.patient.public_id)
            chart = svc.citizen_chart(self.actor, patient_id=self.patient.public_id)
            self.assertEqual(chart['family_count'], 1)
        self.assertNotContains(self.client.get(self.chart_url), 'ENDERECO_FAMILIAR_RESTRITO')

    def test_legacy_free_text_can_be_corrected_without_rewriting_original(self):
        with tenant_context(self.c):
            encounter = self.begin()
            original = health_svc.create_clinical_entry(self.actor, appointment_id=encounter.pk, content='EVOLUCAO_LEGADA')
            ciphertext = bytes(original.conteudo_cifrado)
            correction = self.event(encounter, corrige=original.public_id, motivo='Retificação documentada')
            self.assertEqual(correction.retifica_id, original.pk)
            original.refresh_from_db()
            self.assertEqual(bytes(original.conteudo_cifrado), ciphertext)
            self.assertEqual(self.read(encounter)['events'][0].clinical['data']['texto'], 'EVOLUCAO_LEGADA')

    def test_legacy_prescription_without_timeline_event_remains_accessible_and_audited(self):
        with tenant_context(self.c):
            encounter = self.begin()
            prescription = health.PrescricaoSaudeMunicipal.objects.create(
                organization=self.c, atendimento=encounter, profissional=self.professional,
                **health_svc._health_hierarchy(self.unit),
            )
            health.ItemPrescricaoSaude.objects.create(
                organization=self.c, prescricao=prescription, medicamento_nome='MEDICAMENTO_LEGADO', quantidade=1,
                **health_svc._health_hierarchy(self.unit),
            )
            self.assertEqual(self.read(encounter)['prescriptions'][0].clinical_items[0]['medicamento'], 'MEDICAMENTO_LEGADO')
            self.assertTrue(health.AuditoriaAcessoSaude.objects.filter(acao='PRESCRICAO_CLINICA_ACESSADA').exists())
        self.assertNotContains(self.client.get(self.chart_url), 'MEDICAMENTO_LEGADO')
        self.assertContains(self.client.get(self.chart_url, {'purpose': 'continuidade'}), 'MEDICAMENTO_LEGADO')
