"""Testes novos da contingência; não repetem a homologação anterior."""
import tempfile
import hashlib
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from gestao import models as g, services as gs
from ordens import services as os
from ordens.forms import AssinaturaForm
from ordens.models import Auditoria
from platform_core.context import tenant_context
from platform_core.models import MembershipERP
from platform_core.tests import sample_signature
from . import contract_workday as w, models as m, services as s
from .test_pilot_contract import PilotData


@override_settings(CONTINGENCIA_JORNADA_CONTRATUAL=True)
class ContingencyTests(PilotData, TestCase):
    def user(self, name, org, role):
        return super().user('contingency-unit-' + name, org, role)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        storage = override_settings(PRIVATE_MEDIA_ROOT=self.directory.name, PRIVATE_STORAGE=None)
        storage.enable()
        self.addCleanup(storage.disable)
        self.prepare_pilot()

    def test_candidate_still_requires_journey_by_default(self):
        with override_settings(CONTINGENCIA_JORNADA_CONTRATUAL=False), tenant_context(self.a):
            self.assertTrue(w.blocked(self.techuser, self.order))
            with self.assertRaises(PermissionDenied):
                os.iniciar(self.techuser, self.order.pk, {'resultado': 'NEGADA'})

    def test_contingency_starts_order_without_mutating_contract_configuration(self):
        with tenant_context(self.a):
            os.iniciar(self.techuser, self.order.pk, {'resultado': 'NEGADA'})
            self.order.refresh_from_db()
            self.cfg.refresh_from_db()
            self.assertEqual(self.order.status, 'EXECUCAO')
            self.assertTrue(self.cfg.habilitada and self.cfg.exigir_inicio)
            self.assertFalse(w.Jornada.objects.exists())
            self.assertEqual(Auditoria.objects.filter(ordem=self.order, acao='INICIO').get().alteracoes['modo_operacional'], 'CONTINGENCIA_JORNADA_CONTRATUAL')

    def test_journey_mutators_refuse_writes_and_preserve_existing_history(self):
        with tenant_context(self.a):
            with override_settings(CONTINGENCIA_JORNADA_CONTRATUAL=False):
                row = self.start()
            initial = row.inicio
            operations = [lambda: w.start(self.techuser, self.order.pk),
                          lambda: w.event(self.techuser, row.pk, 'FIM'),
                          lambda: w.request_correction(self.techuser, row.pk, initial, initial, 'Teste de contingência'),
                          lambda: w.decide(self.admin, 0, True, 'Teste de contingência')]
            for operation in operations:
                with self.assertRaises(PermissionDenied):
                    operation()
            row.refresh_from_db()
            self.assertEqual(row.inicio, initial)
            self.assertIsNone(row.fim)
            self.assertFalse(row.eventos.exists())
            self.assertEqual(w.Jornada.objects.count(), 1)

    def test_http_config_and_decision_posts_refused_history_get_available(self):
        before = self.cfg.tarifas.copy()
        self.assertEqual(self.client.post(reverse('operacao:contract_configuration', args=[self.contract.pk]), {'habilitada': ''}).status_code, 403)
        self.assertEqual(self.client.post(reverse('operacao:contract_measurement'), {'acao': 'aprovar', 'correcao': 1}).status_code, 403)
        self.assertEqual(self.client.get(reverse('operacao:contract_measurement')).status_code, 200)
        with tenant_context(self.a):
            self.cfg.refresh_from_db()
            self.assertTrue(self.cfg.habilitada)
            self.assertEqual(self.cfg.tarifas, before)

    def test_activity_refused_but_order_ui_and_notice_available(self):
        self.client.force_login(self.techuser)
        self.assertEqual(self.client.get(reverse('operacao:contract_activity', args=[self.order.pk])).status_code, 403)
        response = self.client.get(reverse('ordens:detalhe', args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Modo de contingência')

    def test_permission_and_tenant_checks_remain_required(self):
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied):
                os.autorizar(self.techuser, self.db['order'])
            with self.assertRaises(PermissionDenied):
                os.autorizar(self.users['ESTOQUE'], self.order)
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(reverse('ordens:detalhe', args=[self.order.pk])).status_code, 404)

    def test_disabled_membership_erp_remains_denied(self):
        from platform_core.models import OrganizationMembership
        membership = OrganizationMembership.objects.get(user=self.techuser, organization=self.a)
        MembershipERP.objects.filter(membership=membership).update(enabled=False)
        with tenant_context(self.a), self.assertRaises(PermissionDenied):
            os.iniciar(self.techuser, self.order.pk, {'resultado': 'NEGADA'})

    def test_order_status_rules_remain_enforced(self):
        with tenant_context(self.a):
            os.iniciar(self.techuser, self.order.pk, {'resultado': 'NEGADA'})
            with self.assertRaises(ValidationError):
                os.iniciar(self.techuser, self.order.pk, {'resultado': 'NEGADA'})

    def test_customer_signature_and_order_completion_still_work(self):
        with tenant_context(self.a):
            os.iniciar(self.techuser, self.order.pk, {'resultado': 'NEGADA'})
            self.order.refresh_from_db()
            self.order.diagnostico = 'Teste de contingência'
            self.order.servico_executado = 'Serviço de contingência'
            self.order.save()
            conference = os.preparar(self.techuser, self.order.pk, {'resultado': 'NEGADA'})
            form = AssinaturaForm({'token': 'sintetico', 'nome': 'Cliente sintético', 'cargo': 'Responsável', 'imagem': sample_signature(), 'confirmacao': True})
            self.assertTrue(form.is_valid(), form.errors)
            signature = os.finalizar(self.techuser, self.order.pk, conference.pk, form.cleaned_data)
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, 'FINALIZADA')
            self.assertTrue(signature.imagem_sha256)
            self.assertFalse(w.Vinculo.objects.exists())

    def test_stock_and_partial_financial_payment_keep_audit(self):
        with tenant_context(self.a):
            move = gs.movimentar(self.admin, self.part.pk, 'ENTRADA', 3, destino_id=self.depot.pk,
                                 lote_data={'numero': 'CONTINGENCIA', 'custo_unitario': Decimal('2.17')})
            self.assertEqual(move.lotes_movimentados.get().lote.quantidade, Decimal('3'))
            entry = self.entry(valor=Decimal('10.01'), cliente=self.da['customer'])
            payment = s.pagar(self.admin, entry.pk, Decimal('3.33'), self.today)
            entry.refresh_from_db()
            self.assertEqual(entry.saldo, Decimal('6.68'))
            self.assertEqual(payment.lancamento.cliente_id, self.da['customer'].pk)

    def test_private_document_write_read_remains_tenant_scoped(self):
        with tenant_context(self.a):
            document = m.Documento.objects.create(titulo='Homologação contingência', cliente=self.da['customer'],
                enviado_por=self.admin, arquivo=ContentFile(b'conteudo sintetico', name='contingencia.txt'),
                sha256=hashlib.sha256(b'conteudo sintetico').hexdigest())
            with document.arquivo.open('rb') as stream:
                self.assertEqual(stream.read(), b'conteudo sintetico')
        with tenant_context(self.b):
            self.assertFalse(m.Documento.objects.filter(pk=document.pk).exists())
