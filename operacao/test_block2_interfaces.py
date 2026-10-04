"""Permissions, official projections and complete Block 2 journeys on PostgreSQL."""
import io
import tempfile
import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from clientes.models import Cliente
from equipamentos.models import Equipamento
from platform_core.context import tenant_context
from platform_core.models import PlatformAudit
from . import test_block2 as fixtures, models as m, services as s, stock, forms
from . import notifications, reporting, planning_services, dashboard, history
from gestao import models as g, services as gs, forms as gf
from ordens.models import OrdemServico, TecnicoAuxiliar
from contas.models import Tecnico


class Block2InterfaceTests(fixtures.Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = self.settings(PRIVATE_MEDIA_ROOT=self.directory.name)
        override.enable(); self.addCleanup(override.disable)

    def portal_user(self):
        user = self.user('portal-bloco2', self.a, 'CLIENTE')
        m.PortalCliente.objects.create(usuario=user, cliente=self.da['customer'])
        return user

    def document(self, **values):
        data = {'titulo': 'Manual privado', 'tipo': 'PDF', 'categoria': 'MANUAL', 'arquivo': SimpleUploadedFile('manual.pdf', b'%PDF-1.4\n%%EOF'), 'equipamento': self.da['equipment'].pk, 'cliente': self.da['customer'].pk}
        data.update(values)
        form = forms.DocumentoForm(data, {'arquivo': data.pop('arquivo')})
        self.assertTrue(form.is_valid(), form.errors)
        return s.documento_salvar(self.admin, form)

    def need(self, quantity=5):
        form = forms.NecessidadePecaForm({'peca': self.part.pk, 'deposito': self.depot.pk, 'quantidade': quantity, 'urgencia': 'ALTA', 'observacoes': 'Fonte faltante'})
        self.assertTrue(form.is_valid(), form.errors)
        return s.necessidade_peca(self.admin, self.da['order'].pk, form)

    def test_portal_qr_and_internal_equipment_are_separate_permissions(self):
        with tenant_context(self.a):
            user = self.portal_user()
            other_customer = Cliente.objects.create(nome_razao_social='Outro cliente')
            other = Equipamento.objects.create(nome='Outro equipamento', cliente=other_customer, categoria=self.da['equipment'].categoria)
        self.client.force_login(user)
        response = self.client.get(reverse('equipamentos:equipamento_qr', args=[self.da['equipment'].codigo_publico]))
        self.assertRedirects(response, reverse('operacao:portal_equipamento', args=[self.da['equipment'].codigo_publico]))
        for equipment in [other, self.db['equipment']]:
            self.assertEqual(self.client.get(reverse('equipamentos:equipamento_qr', args=[equipment.codigo_publico])).status_code, 404)
            self.assertEqual(self.client.get(reverse('operacao:portal_equipamento', args=[equipment.codigo_publico])).status_code, 404)
        self.assertEqual(self.client.get(reverse('equipamentos:equipamento_detail', args=[self.da['equipment'].pk])).status_code, 403)

    def test_portal_call_priority_and_internal_fields_cannot_be_forged(self):
        with tenant_context(self.a):
            user = self.portal_user()
        self.client.force_login(user)
        token = str(uuid.uuid4())
        data = {'cliente': self.da['customer'].pk, 'equipamento': self.da['equipment'].pk, 'unidade': self.da['unit'].pk, 'titulo': 'Urgência declarada', 'descricao': 'Sem refrigeração', 'prioridade': 'URGENTE', 'request_id': token, 'observacoes_internas': 'FORJADO', 'tecnico': self.db['tech'].pk}
        response = self.client.post(reverse('operacao:portal_chamado'), data)
        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.context else '')
        response = self.client.post(reverse('operacao:portal_chamado'), data)
        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.context else '')
        with tenant_context(self.a):
            call = m.Chamado.objects.get()
            self.assertEqual((call.origem, call.prioridade, call.prioridade_solicitada, call.observacoes_internas, call.tecnico_id), ('PORTAL', 'NORMAL', 'URGENTE', '', None))
        data['cliente'] = self.db['customer'].pk
        self.assertEqual(self.client.post(reverse('operacao:portal_chamado'), data).status_code, 400)

    def test_document_release_does_not_release_other_customers(self):
        with tenant_context(self.a):
            private = self.document()
            public = self.document(titulo='Liberado', disponivel_portal='on')
            user = self.portal_user()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('operacao:portal_documento', args=[private.pk])).status_code, 404)
        response = self.client.get(reverse('operacao:portal_documento', args=[public.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(reverse('operacao:documento_arquivo', args=[public.pk])).status_code, 404)

    def test_call_attachments_validate_type_and_are_audited(self):
        with tenant_context(self.a):
            form = self.call_form(); form.files['anexo'] = SimpleUploadedFile('foto.pdf', b'%PDF-1.4\n%%EOF')
            self.assertTrue(form.is_valid(), form.errors)
            call = s.salvar_chamado(self.admin, form, uuid.uuid4())
            document = m.Documento.objects.get(chamado=call)
            self.assertTrue(document.sha256)
            self.assertTrue(PlatformAudit.objects.filter(organization=self.a, action='CHAMADO_ANEXO').exists())
            form = self.call_form(); form.files['anexo'] = SimpleUploadedFile('arquivo.xml', b'<doc/>')
            self.assertFalse(form.is_valid())

    def test_document_validity_alert_updates_resolves_and_reopens_same_notice(self):
        with tenant_context(self.a):
            document = self.document(validade=self.today + timezone.timedelta(days=7))
            notifications.scan_operational(self.admin); notifications.scan_operational(self.admin)
            notice = m.Notificacao.objects.get(usuario=self.admin, chave=f'ops:documento:{document.pk}')
            notice.lida_em = timezone.now(); notice.save()
            read_at = notice.lida_em
            notifications.scan_operational(self.admin); notice.refresh_from_db()
            self.assertEqual(notice.lida_em, read_at); self.assertIsNone(notice.resolvida_em)
            document.validade = self.today + timezone.timedelta(days=100); document.save()
            notifications.scan_operational(self.admin); notice.refresh_from_db()
            self.assertIsNotNone(notice.resolvida_em)
            document.validade = self.today - timezone.timedelta(days=1); document.save()
            notifications.scan_operational(self.admin); notice.refresh_from_db()
            self.assertIsNone(notice.resolvida_em); self.assertIsNone(notice.lida_em)
            self.assertIn('vencido', notice.titulo)
            self.assertEqual(m.Notificacao.objects.filter(usuario=self.admin, chave=notice.chave).count(), 1)

    def test_contract_sla_snapshot_and_visit_alert(self):
        with tenant_context(self.a):
            contract_form = self.contract_form(sla_horas=8)
            self.assertTrue(contract_form.is_valid(), contract_form.errors)
            contract = gs.salvar_contrato(self.admin, contract_form)
            form = self.call_form(contrato=contract.pk)
            self.assertTrue(form.is_valid(), form.errors)
            call = s.salvar_chamado(self.admin, form)
            self.assertEqual(call.sla_horas, 8)
            self.assertAlmostEqual((call.prazo - call.criado_em).total_seconds() / 3600, 8, places=3)
            notifications.scan_operational(self.admin)
            self.assertTrue(m.Notificacao.objects.filter(usuario=self.admin, chave=f'ops:visitas:{contract.pk}').exists())

    def test_piece_need_pending_purchase_discount_and_idempotent_draft(self):
        with tenant_context(self.a):
            need = self.need(5)
            purchase, item = self.purchase(2)
            created = s.comprar_necessidade(self.admin, need.pk)
            self.assertEqual(created.itens.get().quantidade, 3)
            self.assertEqual(s.comprar_necessidade(self.admin, need.pk).pk, created.pk)
            self.assertEqual(stock.metrics(self.part)['em_compra'], 2)
            self.assertEqual(stock.metrics(self.part)['em_solicitacao'], 3)

    def test_piece_need_is_not_bought_again_when_approved_order_covers_it(self):
        with tenant_context(self.a):
            need = self.need(3); self.purchase(3)
            with self.assertRaises(ValidationError):
                s.comprar_necessidade(self.users['ESTOQUE'], need.pk)
            self.assertEqual(m.Compra.objects.count(), 1)

    def test_piece_need_other_depot_consumption_does_not_satisfy_it(self):
        with tenant_context(self.a):
            need = self.need(2)
            other = m.Deposito.objects.create(nome='Outro depósito')
            gs.movimentar(self.admin, self.part.pk, 'ENTRADA', 2, destino_id=other.pk)
            gs.movimentar(self.admin, self.part.pk, 'OS', 2, origem_id=other.pk, ordem_id=self.da['order'].pk)
            self.assertEqual(stock.need_remaining(need), 2)
            with self.assertRaises(ValidationError):
                s.resolver_necessidade(self.admin, need.pk, '')
            s.resolver_necessidade(self.users['ESTOQUE'], need.pk, 'Cliente recusou substituição')
            need.refresh_from_db(); self.assertIsNotNone(need.resolvida_em)
            self.assertEqual(stock.metrics(self.part)['fisico'], 0)
            self.assertTrue(PlatformAudit.objects.filter(organization=self.a, action='OS_PECA_NECESSIDADE_RESOLVIDA').exists())

    def test_new_earlier_lot_preserves_fefo_and_actual_cost_with_reservation(self):
        with tenant_context(self.a):
            late = self.incoming(2, 60, 25)
            reservation = stock.reserve(self.admin, self.part.pk, self.depot.pk, 2, 'Programada', order_id=self.da['order'].pk)
            early = self.incoming(1, 7, 10)
            movement = gs.movimentar(self.admin, self.part.pk, 'OS', 1, origem_id=self.depot.pk, ordem_id=self.da['order'].pk)
            self.assertEqual(movement.lotes_movimentados.get().lote_id, early.pk)
            self.assertEqual(movement.valor_custo, 10)
            reservation.refresh_from_db(); self.assertEqual(reservation.quantidade, 1)
            self.assertEqual(reservation.alocacoes.get().quantidade, 1)
            late.refresh_from_db(); self.assertEqual(late.quantidade, 2)

    def test_auxiliary_planning_and_checklist_template_cannot_be_swapped(self):
        with tenant_context(self.a):
            user = self.user('aux-planning', self.a, 'TECNICO'); tech = Tecnico.objects.create(nome='Aux', usuario=user)
            TecnicoAuxiliar.objects.create(ordem=self.da['order'], tecnico=tech)
            row = planning_services.orders_for(user).get()
            self.assertIn(tech.pk, planning_services.order_event(row)['tecnico_ids'])
            self.assertEqual(len(reporting.report_data(user, 'os_pendentes', {'tecnico': tech})[1]), 1)
            model = m.ModeloChecklist.objects.create(nome='A', itens=[{'item': 'Conferir', 'obrigatorio': True}])
            self.da['order'].modelo_checklist = model
            from ordens.services import aplicar_modelo_checklist
            aplicar_modelo_checklist(self.da['order']); self.da['order'].save()
            self.da['order'].modelo_checklist = None
            with self.assertRaises(ValidationError):
                self.da['order'].save()

    def test_global_search_scopes_organization_and_permissions(self):
        response = self.client.get(reverse('operacao:pesquisa'), {'q': 'gestao'})
        self.assertContains(response, self.da['equipment'].nome)
        self.assertNotContains(response, self.db['equipment'].nome)
        self.client.force_login(self.users['FINANCEIRO'])
        response = self.client.get(reverse('operacao:pesquisa'), {'q': self.da['order'].numero})
        self.assertNotContains(response, 'href="' + reverse('ordens:detalhe', args=[self.da['order'].pk]) + '"')

    def test_real_dashboard_counts_same_names_as_distinct_equipment(self):
        with tenant_context(self.a):
            equipment = Equipamento.objects.create(nome=self.da['equipment'].nome, cliente=self.da['customer'], unidade=self.da['unit'], categoria=self.da['equipment'].categoria)
            OrdemServico.objects.create(cliente=self.da['customer'], unidade=self.da['unit'], equipamento=equipment, defeito='Defeito B')
            result = dashboard.operational_metrics(self.admin, self.today, self.today)
            self.assertEqual(result['operational_summary']['total_os'], 2)
            self.assertEqual(result['operational_summary']['taxa_conclusao'], 0)
            self.assertIsNone(result['operational_summary']['horas_execucao'])
            self.assertEqual(len(result['operational_charts'][2][1]), 2)
        with tenant_context(self.b):
            self.assertEqual(dashboard.operational_metrics(self.admin_b, self.today, self.today)['operational_summary']['total_os'], 1)

    def test_financial_filters_preserve_root_and_nonbanked_control(self):
        with tenant_context(self.a):
            entry = self.entry(cliente=self.da['customer'], ordem=self.da['order'], valor=Decimal('10.01'))
            s.parcelar(self.admin, entry.pk, 3, self.today)
            installment = entry.parcelas.order_by('pk').first().lancamento
            bank = m.ContaBancaria.objects.create(nome='Banco teste', banco='Local')
            s.pagar(self.admin, installment.pk, '1.01', self.today, '', None, uuid.uuid4())
            s.pagar(self.admin, installment.pk, '1.00', self.today, '', bank.pk, uuid.uuid4())
            result = reporting.financial_dashboard(self.today, self.today, {'origem': 'OS', 'controle': 'NAO_BANCARIZADO'})
            self.assertEqual(result['recebido'], Decimal('1.01'))
            self.assertEqual(result['recebido_nao_bancarizado'], Decimal('1.01'))
            self.assertEqual(reporting.financial_dashboard(self.today, self.today, {'origem': 'OS', 'conta': bank})['recebido'], 1)
            self.assertEqual(reporting.financial_dashboard(self.today, self.today, {'origem': 'MANUAL'})['recebido'], 0)
            self.assertFalse(gf.FinanceiroFiltrosForm({'conta': self.db['part'].pk, 'controle': 'NAO_BANCARIZADO'}).is_valid())

    def test_reports_export_real_cost_and_pending_receipt_in_all_formats(self):
        with tenant_context(self.a):
            self.incoming(2, 30, '7.33')
            gs.movimentar(self.admin, self.part.pk, 'OS', '1.125', origem_id=self.depot.pk, ordem_id=self.da['order'].pk)
            headers, rows = reporting.report_data(self.admin, 'custos_os', {})
            self.assertEqual(rows[0][2], Decimal('8.24625'))
            purchase, item = self.purchase(2)
            s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 1}], uuid.uuid4())
            self.assertEqual(reporting.report_data(self.admin, 'compras_pendentes', {'status': 'APROVADA'})[1], [])
            self.assertEqual(reporting.report_data(self.admin, 'compras_pendentes', {'status': 'PEDIDO'})[1][0][-1], 1)
        for key in ['os_executadas', 'os_pendentes', 'preventivas_previstas', 'preventivas_executadas', 'custos_os', 'custos_equipamento', 'custos_cliente', 'custos_contrato', 'estoque_critico', 'compras_pendentes']:
            for export in ['', 'pdf', 'xlsx']:
                response = self.client.get(reverse('gestao:relatorio', args=[key]), {'export': export})
                self.assertEqual(response.status_code, 200, (key, export))
                if export == 'pdf': self.assertTrue(response.content.startswith(b'%PDF'))
                if export == 'xlsx': self.assertTrue(response.content.startswith(b'PK'))
        self.client.force_login(self.users['TECNICO'])
        self.assertEqual(self.client.get(reverse('gestao:relatorio', args=['custos_os'])).status_code, 403)

    def test_all_new_pages_render_and_other_organization_ids_are_denied(self):
        with tenant_context(self.a):
            form = self.call_form(); self.assertTrue(form.is_valid(), form.errors)
            call = s.salvar_chamado(self.admin, form)
            article = m.ArtigoConhecimento.objects.create(titulo='Fonte X', sintoma='Não liga', solucao='Substituição', equipamento=self.da['equipment'])
            purchase, item = self.purchase()
            plan = m.PlanoPreventivo.objects.create(nome='Plano visual', cliente=self.da['customer'], inicio=self.today, fim=self.today + timezone.timedelta(days=30), periodicidade='MENSAL')
            m.PlanoTecnico.objects.create(plano=plan, tecnico=self.da['tech'])
        plan_page = self.client.get(reverse('operacao:plano_detalhe', args=[plan.pk]))
        self.assertContains(plan_page, self.da['tech'].nome)
        self.assertNotContains(plan_page, 'contas.Tecnico.None')
        for name, args in [('operacao:chamado_detalhe', [call.pk]), ('operacao:conhecimento_detalhe', [article.pk]), ('operacao:conhecimento_novo', []), ('operacao:checklist_novo', []), ('operacao:necessidades', []), ('operacao:compra_receber', [purchase.pk]), ('equipamentos:etiqueta', [self.da['equipment'].pk]), ('core:painel', []), ('gestao:financeiro', []), ('operacao:calendario', [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        self.client.force_login(self.admin_b)
        for name, args in [('operacao:chamado_detalhe', [call.pk]), ('operacao:conhecimento_detalhe', [article.pk]), ('operacao:compra_receber', [purchase.pk]), ('equipamentos:etiqueta', [self.da['equipment'].pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 404, name)

    def test_complete_call_order_acceptance_pdf_finance_equipment_history(self):
        with tenant_context(self.a):
            form = self.call_form(); self.assertTrue(form.is_valid(), form.errors)
            call = s.salvar_chamado(self.admin, form)
            order = s.chamado_os(self.admin, call.pk, self.da['tech'].pk)
            order.valor_cobranca = Decimal('123.45'); order.save()
            self.incoming(2, 7, '7.33')
            stock.reserve(self.admin, self.part.pk, self.depot.pk, 1, 'Chamado', order_id=order.pk)
            gs.movimentar(self.admin, self.part.pk, 'OS', 1, origem_id=self.depot.pk, ordem_id=order.pk)
            signature = self.finalize(order)
            from ordens.reports import gerar_pdf
            pdf = gerar_pdf(signature)
            self.assertTrue(pdf.startswith(b'%PDF'))
            call.refresh_from_db(); self.assertEqual(call.status, 'CONCLUIDO')
            account = g.Lancamento.objects.get(ordem=order)
            s.pagar(self.admin, account.pk, '23.45', self.today, 'Aceite parcial', None, uuid.uuid4())
            account.refresh_from_db(); self.assertEqual(account.saldo, 100)
            events = history.equipment_timeline(self.admin, self.da['equipment'])
            self.assertTrue(any(event['fonte'] == 'chamado' and event['id'] == call.pk for event in events))
            self.assertTrue(any(event['fonte'] == 'os-conclusao' and event['id'] == order.pk for event in events))
            self.assertEqual(order.custo_pecas, Decimal('7.33'))
