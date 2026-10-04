"""Incremental operations: real official stock, calls, checklists and purchasing."""
import copy
import uuid
from decimal import Decimal
from unittest import skipUnless
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from gestao.tests import Dados
from gestao import models as g, services as gs
from ordens import services as os_services
from ordens.models import OrdemServico, TecnicoAuxiliar
from contas.models import Tecnico
from platform_core.context import tenant_context
from . import models as m, services as s, stock, forms, tests as previous_tests


class Block2Fixtures(Dados):
    def setup_operations(self):
        self.prepare_data()
        self.today = timezone.localdate()
        with tenant_context(self.a):
            self.part = self.da['part']
            self.depot = m.Deposito.objects.create(nome='Bloco 2')
            self.supplier = g.Fornecedor.objects.create(nome='Fornecedor técnico')
    def purchase(self, quantity=5):
        purchase = m.Compra.objects.create(deposito=self.depot, fornecedor=self.supplier, necessidade='Reposição', vencimento=self.today, criado_por=self.admin)
        item = m.ItemCompra.objects.create(compra=purchase, peca=self.part, quantidade=quantity, custo_unitario=Decimal('7.33'))
        s.compra_acao(self.admin, purchase.pk, 'aprovar')
        s.compra_acao(self.admin, purchase.pk, 'pedir')
        return purchase, item
    def incoming(self, quantity, days=30, cost=10):
        move = gs.movimentar(self.admin, self.part.pk, 'ENTRADA', quantity, destino_id=self.depot.pk, lote_data={'numero': f'L-{days}', 'validade': self.today + timezone.timedelta(days=days), 'custo_unitario': Decimal(cost)})
        return move.lotes_movimentados.get().lote
    def call_form(self, **extra):
        values = {'cliente': self.da['customer'].pk, 'unidade': self.da['unit'].pk, 'equipamento': self.da['equipment'].pk, 'titulo': 'Fonte avariada', 'descricao': 'Não liga', 'prioridade': 'ALTA', 'solicitante': 'Contato', 'tipo': 'CORRETIVA'}
        values.update(extra)
        return forms.ChamadoForm(values, instance=m.Chamado(criado_por=self.admin))


class Block2OperationsTests(Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()

    def test_partial_receipt_pending_lots_and_final_account(self):
        with tenant_context(self.a):
            purchase, item = self.purchase()
            receipt = s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 2, 'lote': 'PARTE-A'}], uuid.uuid4())
            purchase.refresh_from_db(); item.refresh_from_db()
            self.assertEqual((purchase.status, item.quantidade_recebida, item.quantidade_pendente), ('PEDIDO', 2, 3))
            self.assertIsNone(purchase.conta_id)
            self.assertEqual(stock.metrics(self.part)['em_compra'], 3)
            s.compra_acao(self.admin, purchase.pk, 'receber')
            s.compra_acao(self.admin, purchase.pk, 'receber')
            purchase.refresh_from_db()
            self.assertEqual((purchase.status, purchase.conta.valor), ('RECEBIDA', Decimal('36.65')))
            self.assertEqual((m.LoteEstoque.objects.count(), purchase.recebimentos.count()), (2, 2))
            self.assertEqual(stock.metrics(self.part)['fisico'], 5)
            self.assertEqual(stock.metrics(self.part)['em_compra'], 0)
            self.assertEqual(receipt.itens.get().movimentacao.valor_custo, Decimal('14.66'))

    def test_receipt_same_token_returns_same_record(self):
        with tenant_context(self.a):
            purchase, item = self.purchase()
            token = uuid.uuid4(); lines = [{'item_id': item.pk, 'quantidade': Decimal('1.125'), 'lote': 'A'}]
            first = s.receber_compra(self.admin, purchase.pk, lines, token)
            self.assertEqual(first.pk, s.receber_compra(self.admin, purchase.pk, lines, token).pk)
            self.assertEqual(g.Movimentacao.objects.count(), 1)
            self.assertEqual(first.itens.get().movimentacao.custo_total, Decimal('8.24625'))
            with self.assertRaises(ValidationError):
                s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 2}], token)

    def test_over_receipt_rolls_back_all_details(self):
        with tenant_context(self.a):
            purchase, item = self.purchase(1)
            with self.assertRaises(ValidationError):
                s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 2}], uuid.uuid4())
            self.assertEqual((m.RecebimentoCompra.objects.count(), g.Movimentacao.objects.count()), (0, 0))
            self.part.refresh_from_db(); self.assertEqual(self.part.quantidade_atual, 0)

    def test_received_history_is_immutable_and_partial_cannot_cancel(self):
        with tenant_context(self.a):
            purchase, item = self.purchase()
            receipt = s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 1}], uuid.uuid4())
            with self.assertRaises(ValidationError):
                s.compra_acao(self.admin, purchase.pk, 'cancelar')
            with self.assertRaises(ValidationError):
                receipt.save()
            with self.assertRaises(ValidationError):
                receipt.itens.get().delete()

    def test_expired_receipt_and_foreign_item_are_rejected(self):
        with tenant_context(self.a):
            purchase, item = self.purchase()
            with self.assertRaises(ValidationError):
                s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 1, 'validade': self.today - timezone.timedelta(days=1)}], uuid.uuid4())
            other, other_item = self.purchase()
            with self.assertRaises(ValidationError):
                s.receber_compra(self.admin, purchase.pk, [{'item_id': other_item.pk, 'quantidade': 1}], uuid.uuid4())
            self.assertEqual(m.RecebimentoCompra.objects.count(), 0)

    def test_purchase_receipt_permissions_and_organization(self):
        with tenant_context(self.a):
            purchase, item = self.purchase()
            with self.assertRaises(PermissionDenied):
                s.receber_compra(self.users['TECNICO'], purchase.pk, [{'item_id': item.pk, 'quantidade': 1}], uuid.uuid4())
            s.receber_compra(self.users['ESTOQUE'], purchase.pk, [{'item_id': item.pk, 'quantidade': 1}], uuid.uuid4())
        with tenant_context(self.b):
            self.assertFalse(m.RecebimentoCompra.objects.exists())
            self.assertFalse(m.ItemRecebimentoCompra.objects.exists())
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(reverse('operacao:compra_receber', args=[purchase.pk])).status_code, 404)

    def test_reservation_allocates_fefo_without_reducing_physical(self):
        with tenant_context(self.a):
            late = self.incoming(3, 60); early = self.incoming(2, 7)
            reservation = stock.reserve(self.admin, self.part.pk, self.depot.pk, 3, 'Programação', order_id=self.da['order'].pk)
            self.assertEqual(dict(reservation.alocacoes.values_list('lote_id', 'quantidade')), {early.pk: 2, late.pk: 1})
            data = stock.metrics(self.part)
            self.assertEqual((data['fisico'], data['disponivel']), (5, 2))

    def test_reserved_lot_is_not_consumed_by_other_order(self):
        with tenant_context(self.a):
            early = self.incoming(2, 7, 10); late = self.incoming(3, 60, 25)
            stock.reserve(self.admin, self.part.pk, self.depot.pk, 2, 'Agenda', order_id=self.da['order'].pk)
            other = OrdemServico.objects.create(cliente=self.da['customer'], unidade=self.da['unit'], equipamento=self.da['equipment'], tecnico=self.da['tech'], defeito='Outro')
            movement = gs.movimentar(self.admin, self.part.pk, 'OS', 2, origem_id=self.depot.pk, ordem_id=other.pk)
            self.assertEqual(movement.lotes_movimentados.get().lote_id, late.pk)
            self.assertEqual(movement.custo_total, 50)
            early.refresh_from_db(); self.assertEqual(early.quantidade, 2)

    def test_reserved_consumption_partial_then_return_preserves_cost(self):
        with tenant_context(self.a):
            lot = self.incoming(3, 7, Decimal('7.33'))
            reservation = stock.reserve(self.admin, self.part.pk, self.depot.pk, 3, 'Agenda', order_id=self.da['order'].pk)
            movement = gs.movimentar(self.admin, self.part.pk, 'OS', Decimal('1.125'), origem_id=self.depot.pk, ordem_id=self.da['order'].pk)
            reservation.refresh_from_db()
            self.assertEqual((reservation.quantidade, reservation.alocacoes.get().quantidade), (Decimal('1.875'), Decimal('1.875')))
            returned = gs.movimentar(self.admin, self.part.pk, 'DEVOLUCAO', Decimal('0.125'), destino_id=self.depot.pk, ordem_id=self.da['order'].pk)
            self.assertEqual((movement.custo_total, returned.custo_total), (Decimal('8.24625'), Decimal('0.91625')))
            self.assertEqual(returned.lotes_movimentados.get().lote_id, lot.pk)

    def test_cancel_releases_reservations_without_stock_change(self):
        with tenant_context(self.a):
            self.incoming(3)
            reservation = stock.reserve(self.admin, self.part.pk, self.depot.pk, 3, 'Agenda', order_id=self.da['order'].pk)
            s.transicao_os(self.admin, self.da['order'].pk, 'cancelar', 'Cliente cancelou a visita')
            reservation.refresh_from_db()
            self.assertEqual(reservation.status, 'LIBERADA')
            self.assertEqual(stock.metrics(self.part)['disponivel'], 3)

    def test_reservation_idempotent_and_foreign_lot_denied(self):
        with tenant_context(self.a):
            lot = self.incoming(3); token = uuid.uuid4()
            first = stock.reserve(self.admin, self.part.pk, self.depot.pk, 1, 'Agenda', request_id=token, lot_id=lot.pk)
            self.assertEqual(first.pk, stock.reserve(self.admin, self.part.pk, self.depot.pk, 1, 'Agenda', request_id=token, lot_id=lot.pk).pk)
            with self.assertRaises(ValidationError):
                stock.reserve(self.admin, self.part.pk, self.depot.pk, 1, 'Agenda', lot_id=999999)

    def test_call_conversion_status_tracking_without_duplicate_order(self):
        with tenant_context(self.a):
            form = self.call_form(); self.assertTrue(form.is_valid(), form.errors)
            token = uuid.uuid4(); call = s.salvar_chamado(self.admin, form, token)
            repeated = self.call_form(); self.assertTrue(repeated.is_valid(), repeated.errors)
            self.assertEqual(call.pk, s.salvar_chamado(self.admin, repeated, token).pk)
            s.chamado_status(self.admin, call.pk, 'TRIAGEM')
            order = s.chamado_os(self.admin, call.pk, self.da['tech'].pk)
            self.assertEqual(order.pk, s.chamado_os(self.admin, call.pk, self.da['tech'].pk).pk)
            signature = self.finalize(order)
            call.refresh_from_db(); self.assertEqual(call.status, 'CONCLUIDO')
            self.assertEqual(signature.ordem_id, order.pk)

    def test_call_agenda_requires_responsible_and_schedule(self):
        with tenant_context(self.a):
            form = self.call_form(); self.assertTrue(form.is_valid(), form.errors)
            call = s.salvar_chamado(self.admin, form)
            s.chamado_status(self.admin, call.pk, 'TRIAGEM')
            with self.assertRaises(ValidationError):
                s.chamado_status(self.admin, call.pk, 'AGENDADO')
            with self.assertRaises(ValidationError):
                s.chamado_status(self.admin, call.pk, 'CONCLUIDO')

    def test_typed_checklist_false_zero_decimal_and_selection(self):
        with tenant_context(self.a):
            order = self.da['order']
            order.checklist = [{'item': 'Conforme?', 'tipo': 'CONFORMIDADE', 'obrigatorio': True}, {'item': 'Temperatura', 'tipo': 'MEDICAO', 'unidade': '°C', 'obrigatorio': True}, {'item': 'Ação', 'tipo': 'SELECAO', 'opcoes': ['Limpar', 'Trocar'], 'obrigatorio': True}]
            order.save()
            s.checklist_salvar(self.admin, order.pk, [], {}, {'0': 'false', '1': '0.000', '2': 'Trocar'})
            order.refresh_from_db(); s.validar_respostas_checklist(order)
            self.assertIs(order.checklist[0]['resposta'], False)
            self.assertTrue(all(item['concluido'] for item in order.checklist))
            with self.assertRaises(ValidationError):
                s.checklist_salvar(self.admin, order.pk, [], {}, {'0': 'true', '1': 'NaN', '2': 'Trocar'})
            order.refresh_from_db(); self.assertEqual(order.checklist[1]['resposta'], '0.000')

    def test_checklist_model_copy_and_signed_snapshot_frozen(self):
        with tenant_context(self.a):
            model = m.ModeloChecklist.objects.create(nome='Medição', itens=[{'item': 'Temperatura', 'tipo': 'MEDICAO', 'unidade': '°C', 'obrigatorio': True}])
            order = self.da['order']; order.modelo_checklist = model; order.save()
            os_services.aplicar_modelo_checklist(order)
            s.checklist_salvar(self.admin, order.pk, [], {}, {'0': '-12.34'})
            signature = self.finalize(order); before = copy.deepcopy(signature.conferencia.dados)
            model.itens = [{'item': 'Alterado'}]; model.save()
            os_services.reabrir(self.admin, order.pk, 'Nova inspeção solicitada pelo cliente')
            order.refresh_from_db(); signature.conferencia.refresh_from_db()
            self.assertEqual(signature.conferencia.dados, before)
            self.assertNotIn('resposta', order.checklist[0])

    def test_photo_checklist_rejects_unrelated_photo(self):
        with tenant_context(self.a):
            order = self.da['order']; order.checklist = [{'item': 'Identificação', 'tipo': 'FOTO', 'obrigatorio': True}]; order.save()
            with self.assertRaises(ValidationError):
                s.checklist_salvar(self.admin, order.pk, [], {}, {'0': '999999'})

    def test_auxiliary_authorization_and_new_states(self):
        with tenant_context(self.a):
            user = self.user('auxiliar', self.a, 'TECNICO')
            tech = Tecnico.objects.create(nome='Auxiliar', usuario=user)
            order = self.da['order']; TecnicoAuxiliar.objects.create(ordem=order, tecnico=tech)
            os_services.autorizar(user, order)
            self.assertTrue(os_services.visiveis(user).filter(pk=order.pk).exists())
            s.transicao_os(user, order.pk, 'deslocamento')
            os_services.iniciar(user, order.pk, {'resultado': 'NEGADA', 'latitude': None, 'longitude': None, 'precisao': None})
            s.transicao_os(user, order.pk, 'aguardar_aprovacao')
            self.assertContains(self.client.get(reverse('ordens:lista'), {'grupo': 'andamento'}), order.numero)
            s.transicao_os(user, order.pk, 'retomar')
            order.refresh_from_db(); self.assertEqual(order.status, 'EXECUCAO')
            with self.assertRaises(PermissionDenied):
                os_services.autorizar(self.users['FINANCEIRO'], order)

    def test_quadrimestral_generation_is_anchored_and_idempotent(self):
        with tenant_context(self.a):
            from dateutil.relativedelta import relativedelta
            plan = m.PlanoPreventivo.objects.create(nome='Quadrimestral', cliente=self.da['customer'], inicio=self.today, fim=self.today + relativedelta(months=9), periodicidade='QUADRIMESTRAL')
            m.PlanoEquipamento.objects.create(plano=plan, equipamento=self.da['equipment'])
            s.gerar_plano(self.admin, plan.pk); s.gerar_plano(self.admin, plan.pk)
            self.assertEqual(list(plan.ocorrencias.values_list('data', flat=True)), [self.today + relativedelta(months=months) for months in [0, 4, 8]])
            order = s.preventiva_os(self.admin, plan.ocorrencias.first().pk, self.da['tech'].pk)
            self.finalize(order)
            plan.refresh_from_db(); self.assertEqual(plan.proxima_execucao, self.today + relativedelta(months=4))


@skipUnless(connection.vendor == 'postgresql', 'Exige PostgreSQL real')
class Block2PostgreSQLTests(Block2Fixtures, TransactionTestCase):
    race = previous_tests.OperacaoPostgreSQLTests.race
    def setUp(self):
        self.setup_operations()
    def test_partial_receipt_race_never_exceeds_order(self):
        with tenant_context(self.a):
            purchase, item = self.purchase(3)
        self.assertCountEqual(self.race(lambda index: s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 2}], uuid.uuid4())), ['OK', 'BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(m.ItemRecebimentoCompra.objects.aggregate(total=Sum('quantidade'))['total'], 2)
            self.part.refresh_from_db(); self.assertEqual(self.part.quantidade_atual, 2)
    def test_same_receipt_token_race_creates_one_entry(self):
        with tenant_context(self.a):
            purchase, item = self.purchase()
        token = uuid.uuid4()
        self.assertEqual(self.race(lambda index: s.receber_compra(self.admin, purchase.pk, [{'item_id': item.pk, 'quantidade': 1}], token)), ['OK', 'OK'])
        with tenant_context(self.a):
            self.assertEqual((m.RecebimentoCompra.objects.count(), g.Movimentacao.objects.count()), (1, 1))
    def test_reservation_race_does_not_overcommit_lot(self):
        with tenant_context(self.a):
            self.incoming(3)
        self.assertCountEqual(self.race(lambda index: stock.reserve(self.admin, self.part.pk, self.depot.pk, 2, 'Agenda', request_id=uuid.uuid4())), ['OK', 'BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(stock.metrics(self.part)['reservado'], 2)
            self.assertEqual(m.AlocacaoReservaEstoque.objects.get().quantidade, 2)
    def test_call_conversion_race_creates_one_order(self):
        with tenant_context(self.a):
            form = self.call_form(); assert form.is_valid(), form.errors
            call = s.salvar_chamado(self.admin, form)
        self.assertEqual(self.race(lambda index: s.chamado_os(self.admin, call.pk, self.da['tech'].pk)), ['OK', 'OK'])
        with tenant_context(self.a):
            self.assertEqual(OrdemServico.objects.count(), 2)
    def test_call_opening_same_token_race(self):
        token = uuid.uuid4()
        def create(index):
            form = self.call_form(); assert form.is_valid(), form.errors
            return s.salvar_chamado(self.admin, form, token)
        self.assertEqual(self.race(create), ['OK', 'OK'])
        with tenant_context(self.a):
            self.assertEqual(m.Chamado.objects.count(), 1)
    def test_preventive_generation_and_conversion_are_idempotent_in_race(self):
        with tenant_context(self.a):
            plan = m.PlanoPreventivo.objects.create(nome='Concorrência', cliente=self.da['customer'], inicio=self.today, fim=self.today, periodicidade='MENSAL')
            m.PlanoEquipamento.objects.create(plano=plan, equipamento=self.da['equipment'])
        self.assertEqual(self.race(lambda index: s.gerar_plano(self.admin, plan.pk)), ['OK', 'OK'])
        with tenant_context(self.a):
            occurrence = plan.ocorrencias.get()
        self.assertEqual(self.race(lambda index: s.preventiva_os(self.admin, occurrence.pk, self.da['tech'].pk)), ['OK', 'OK'])
        with tenant_context(self.a):
            self.assertEqual((plan.ocorrencias.count(), OrdemServico.objects.count()), (1, 2))
    def test_reserved_consumption_race_retains_lot_cost_and_remaining_hold(self):
        with tenant_context(self.a):
            self.incoming(3, 7, '7.33')
            stock.reserve(self.admin, self.part.pk, self.depot.pk, 3, 'Reserva concorrente', order_id=self.da['order'].pk)
        self.assertCountEqual(self.race(lambda index: gs.movimentar(self.admin, self.part.pk, 'OS', 2, ordem_id=self.da['order'].pk, origem_id=self.depot.pk, request_id=uuid.uuid4())), ['OK', 'BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(self.da['order'].custo_pecas, Decimal('14.66'))
            self.assertEqual(m.AlocacaoReservaEstoque.objects.get().quantidade, 1)
