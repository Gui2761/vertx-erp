import uuid
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from platform_core.context import tenant_context
from gestao import models as g, services as gs
from . import models as m, services as finance, commerce as c
from .test_block2 import Block2Fixtures

class CommerceData(Block2Fixtures):
    def setup_commerce(self):
        self.setup_operations()
        self.operator=self.user('pdv-bloco3',self.a,'PDV')
        with tenant_context(self.a):
            self.cash=m.ContaBancaria.objects.create(nome='Caixa PDV',tipo='CAIXA')
            self.bank=m.ContaBancaria.objects.create(nome='Banco PIX',tipo='BANCO')
            self.cash_method=g.FormaPagamento.objects.create(nome='Dinheiro PDV',tipo_pdv='DINHEIRO')
            self.pix=g.FormaPagamento.objects.create(nome='PIX PDV',tipo_pdv='PIX',conta_pdv=self.bank)
            self.credit=g.FormaPagamento.objects.create(nome='Crediário PDV',tipo_pdv='CREDIARIO')
            self.part.preco_venda=Decimal('10');self.part.save()
            self.session=c.open_cash(self.operator,self.cash.pk,0,uuid.uuid4())
    def sale(self,quantity=1,user=None):
        user=user or self.operator
        sale=c.new_sale(user,self.session.public_id,self.depot.pk)
        item=c.add_item(user,sale.public_id,self.part.sku,quantity)
        return sale,item
    def paid(self,sale,amount=None,key=None):
        return c.finalize(self.operator,sale.public_id,[{'forma':self.cash_method.pk,'valor':str(amount or sale.total)}],key or uuid.uuid4())

class CommerceTests(CommerceData,TestCase):
    def setUp(self): self.setup_commerce()

    def test_purchase_unit_cannot_be_injected_to_reduce_pdv_price(self):
        with tenant_context(self.a):
            self.part.fator_compra=10;self.part.save()
            sale=c.new_sale(self.operator,self.session.public_id,self.depot.pk)
            with self.assertRaises(ValidationError): c.add_item(self.operator,sale.public_id,self.part.sku,1,'compra')
            self.assertFalse(sale.itens.exists())
            with self.assertRaises(ValidationError): c.money('999999999999999999999999999999999')

    def test_cart_quantity_updates_reservation_and_rolls_back_excess(self):
        with tenant_context(self.a):
            self.incoming(3);m.ConfiguracaoPDV.objects.create(reservar_rascunho=True)
            sale,item=self.sale()
            c.edit_item(self.operator,sale.public_id,item.pk,2)
            self.assertEqual(sale.reservas_estoque.get(status='ATIVA').quantidade,2)
            with self.assertRaises(ValidationError): c.edit_item(self.operator,sale.public_id,item.pk,4)
            item.refresh_from_db();self.assertEqual(item.quantidade,2)
            self.assertEqual(sale.reservas_estoque.get(status='ATIVA').quantidade,2)
            c.sale_note(self.operator,sale.public_id,'Entrega no balcão')
            sale.refresh_from_db();self.assertEqual(sale.observacoes,'Entrega no balcão')
            c.remove_item(self.operator,sale.public_id,item.pk)
            self.assertFalse(sale.reservas_estoque.filter(status='ATIVA').exists())
            self.assertFalse(sale.itens.exists())

    def test_opening_count_is_not_receipt_and_is_idempotent(self):
        with tenant_context(self.a):
            self.assertEqual(m.MovimentoCaixa.objects.count(),0)
            self.assertEqual(c.open_cash(self.operator,self.cash.pk,0,self.session.abertura_id).pk,self.session.pk)
            with self.assertRaises(ValidationError): c.open_cash(self.operator,self.cash.pk,1,self.session.abertura_id)

    def test_mixed_payments_troco_fefo_cost_snapshot_and_ledger(self):
        with tenant_context(self.a):
            late=self.incoming(2,60,'7.33');early=self.incoming(1,7,'2.25')
            sale,item=self.sale(2)
            key=uuid.uuid4(); rows=[{'forma':self.cash_method.pk,'valor':'8.00','recebido':'10.00'},{'forma':self.pix.pk,'valor':'12.00'}]
            sale=c.finalize(self.operator,sale.public_id,rows,key);item.refresh_from_db()
            self.assertEqual((sale.status,sale.conta.saldo),('FINALIZADA',0))
            self.assertEqual(item.custo_total,Decimal('9.58000'))
            self.assertEqual([r['id'] for r in sale.snapshot['itens'][0]['lotes']],[early.pk,late.pk])
            self.assertEqual((self.cash.saldo,self.bank.saldo),(8,12))
            self.assertEqual(sale.pagamentos_pdv.get(forma=self.cash_method).troco,2)
            self.assertIsNotNone(sale.pagamentos_pdv.get(forma=self.pix).pagamento_id)
            self.assertEqual(c.finalize(self.operator,sale.public_id,rows,key).pk,sale.pk)
            self.assertEqual((m.Pagamento.objects.count(),g.Movimentacao.objects.filter(tipo='SAIDA').count()),(2,1))
            with self.assertRaises(ValidationError): item.quantidade=1;item.save()
            with self.assertRaises(ValidationError): sale.observacoes='mudança';sale.save()

    def test_pdv_cannot_call_arbitrary_stock_finance_or_foreign_sale(self):
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied): gs.movimentar(self.operator,self.part.pk,'ENTRADA',1)
            with self.assertRaises(PermissionDenied): finance.caixa(self.operator,self.cash.pk,'ENTRADA',10,self.today,'Manual')
            sale,item=self.sale()
        with tenant_context(self.b):
            with self.assertRaises(m.Venda.DoesNotExist): c.add_item(self.admin_b,sale.public_id,self.part.sku,1)

    def test_insufficient_stock_rolls_back_receivable_and_payment(self):
        with tenant_context(self.a):
            sale,item=self.sale()
            with self.assertRaises(ValidationError): self.paid(sale)
            self.assertEqual((g.Lancamento.objects.count(),m.Pagamento.objects.count()),(0,0))
            sale.refresh_from_db();self.assertEqual(sale.status,'RASCUNHO')

    def test_payment_without_bank_is_tracked(self):
        with tenant_context(self.a):
            self.pix.conta_pdv=None;self.pix.save();self.incoming(1)
            sale,item=self.sale()
            sale=c.finalize(self.operator,sale.public_id,[{'forma':self.pix.pk,'valor':'10.00'}],uuid.uuid4())
            payment=sale.pagamentos_pdv.get().pagamento
            self.assertIsNone(payment.conta_id);self.assertEqual(payment.valor,10)
            self.assertIn('Não bancarizado',payment.controle_caixa)

    def test_closed_cash_blocks_writes_and_difference_requires_reason(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError): c.close_cash(self.operator,self.session.public_id,1)
            closed=c.close_cash(self.operator,self.session.public_id,1,'Conferência divergente')
            self.assertEqual((closed.esperado,closed.diferenca),(0,1))
            self.assertEqual(m.MovimentoCaixa.objects.count(),0)
            with self.assertRaises(ValidationError): self.sale()

    def test_discount_supervision_and_cent_allocation(self):
        with tenant_context(self.a):
            self.incoming(10)
            sale,item=self.sale()
            with self.assertRaises(PermissionDenied): c.pricing(self.operator,sale.public_id,1,0,'Desconto')
            c.pricing(self.admin,sale.public_id,'1.33','.04','Supervisor')
            sale.refresh_from_db();sale=self.paid(sale,'8.71')
            self.assertEqual(sum(Decimal(i['valor_liquido']) for i in sale.snapshot['itens']),Decimal('8.71'))

    def test_crediario_requires_customer_and_configured_credit(self):
        with tenant_context(self.a):
            self.incoming(2);sale,item=self.sale()
            rows=[{'forma':self.credit.pk,'valor':'10'}]
            with self.assertRaises(ValidationError): c.finalize(self.operator,sale.public_id,rows,uuid.uuid4())
            sale.cliente=self.da['customer'];sale.save()
            with self.assertRaises(ValidationError): c.finalize(self.operator,sale.public_id,rows,uuid.uuid4())
            customer=sale.cliente;customer.limite_credito=10;customer.save()
            sale=c.finalize(self.operator,sale.public_id,rows,uuid.uuid4())
            self.assertEqual(sale.conta.saldo,10);self.assertEqual(m.Pagamento.objects.count(),0)

    def test_cash_supervisor_movement_idempotency(self):
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied): c.cash_operation(self.operator,self.session.public_id,'SUPRIMENTO',10,'Fundo',uuid.uuid4())
            key=uuid.uuid4();event=c.cash_operation(self.admin,self.session.public_id,'SUPRIMENTO',10,'Fundo',key)
            self.assertEqual(c.cash_operation(self.admin,self.session.public_id,'SUPRIMENTO',10,'Fundo',key).pk,event.pk)
            self.assertEqual((c.cash_expected(self.session),self.cash.saldo),(10,10))
