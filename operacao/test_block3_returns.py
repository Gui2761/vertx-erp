import uuid
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from platform_core.context import tenant_context
from gestao import models as g, services as gs
from . import models as m, commerce as c
from .test_block3_commerce import CommerceData

class ReturnTests(CommerceData,TestCase):
    def setUp(self): self.setup_commerce()

    def test_partial_returns_original_lots_cost_and_exact_last_cent(self):
        with tenant_context(self.a):
            early=self.incoming(1,7,'2.25');late=self.incoming(2,60,'7.33')
            sale,item=self.sale(3);c.pricing(self.admin,sale.public_id,'1.01',0,'Desconto autorizado');sale.refresh_from_db();sale=self.paid(sale,'28.99')
            first=c.return_sale(self.admin,sale.public_id,[{'item':item.pk,'quantidade':'1'}],'Produto devolvido',uuid.uuid4())
            self.assertEqual((first.valor,first.itens.get().movimento.custo_total),(Decimal('9.66'),Decimal('2.25')))
            early.refresh_from_db();self.assertEqual(early.quantidade,1)
            second=c.return_sale(self.admin,sale.public_id,[{'item':item.pk,'quantidade':'2'}],'Restante devolvido',uuid.uuid4())
            self.assertEqual(first.valor+second.valor,Decimal('28.99'))
            self.assertEqual(second.itens.get().movimento.custo_total,Decimal('14.66'))
            sale.refresh_from_db();self.assertEqual(sale.status,'DEVOLVIDA')
            self.assertEqual(g.Lancamento.objects.filter(tipo='PAGAR').count(),2)
            self.assertEqual(self.cash.saldo,Decimal('28.99'))

    def test_credit_return_abates_pending_without_fictional_payment(self):
        with tenant_context(self.a):
            self.incoming(1);sale,item=self.sale()
            customer=self.da['customer'];customer.limite_credito=10;customer.save();sale.cliente=customer;sale.save()
            sale=c.finalize(self.operator,sale.public_id,[{'forma':self.credit.pk,'valor':'10'}],uuid.uuid4())
            result=c.return_sale(self.admin,sale.public_id,[{'item':item.pk,'quantidade':'1'}],'Cancelamento de entrega',uuid.uuid4())
            sale.conta.refresh_from_db();self.assertEqual(sale.conta.saldo,0)
            self.assertEqual((sale.conta.eventos.get(tipo='ABATIMENTO').valor,m.Pagamento.objects.count()),(10,0))
            self.assertIsNone(result.reembolso_id)

    def test_return_idempotency_over_return_and_expired_physical_stock(self):
        with tenant_context(self.a):
            lot=self.incoming(1,1);sale,item=self.sale();sale=self.paid(sale)
            from unittest.mock import patch
            key=uuid.uuid4();rows=[{'item':item.pk,'quantidade':'1'}]
            with patch('operacao.stock.timezone.localdate',return_value=self.today+__import__('datetime').timedelta(days=2)):
                result=c.return_sale(self.admin,sale.public_id,rows,'Lote retornado',key)
            self.assertEqual(c.return_sale(self.admin,sale.public_id,rows,'Lote retornado',key).pk,result.pk)
            self.assertEqual(result.itens.get().movimento.lotes_movimentados.get().lote_id,lot.pk)
            with self.assertRaises(ValidationError): c.return_sale(self.admin,sale.public_id,rows,'Outra devolução',uuid.uuid4())

    def test_quote_conversion_reuses_receivable_and_cannot_generate_os(self):
        with tenant_context(self.a):
            self.incoming(1)
            quote=g.Orcamento.objects.create(cliente=self.da['customer'],equipamento=self.da['equipment'],unidade=self.da['unit'],validade=self.today,criado_por=self.admin,gerar_recebivel=True)
            g.ItemOrcamento.objects.create(orcamento=quote,tipo='PECA',peca=self.part,descricao='Produto',quantidade=1,valor_unitario=10)
            gs.status_orcamento(self.admin,quote.pk,'enviar');gs.status_orcamento(self.admin,quote.pk,'aprovar')
            sale=c.quote_to_sale(self.operator,quote.pk,self.session.public_id,self.depot.pk)
            self.assertEqual(c.quote_to_sale(self.operator,quote.pk,self.session.public_id,self.depot.pk).pk,sale.pk)
            sale=self.paid(sale)
            self.assertEqual(g.Lancamento.objects.filter(tipo='RECEBER').count(),1)
            with self.assertRaises(ValidationError): gs.converter_orcamento(self.admin,quote.pk,self.da['tech'].pk)

    def test_pdv_views_uuid_and_receipt_are_organization_scoped(self):
        with tenant_context(self.a): self.incoming(1);sale,item=self.sale();self.paid(sale)
        self.client.force_login(self.operator)
        from django.urls import reverse
        self.assertContains(self.client.get(reverse('operacao:pdv_receipt',args=[sale.public_id])),'Comprovante não fiscal')
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(reverse('operacao:pdv_sale',args=[sale.public_id])).status_code,404)
