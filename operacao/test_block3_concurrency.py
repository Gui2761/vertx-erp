import uuid
from unittest import skipUnless
from unittest.mock import patch
from django.db import connection
from django.test import TransactionTestCase
from platform_core.context import tenant_context
from gestao import models as g
from . import models as m, commerce as c, workforce as w, inventory as inv, services as s
from . import tests as previous_tests
from .test_block3_commerce import CommerceData
from .test_block3_workforce import WorkforceData

@skipUnless(connection.vendor=='postgresql','Concorrência exige PostgreSQL real')
class CommerceConcurrencyTests(CommerceData,TransactionTestCase):
    race=previous_tests.OperacaoPostgreSQLTests.race
    def setUp(self): self.setup_commerce()
    def test_double_finalize_commits_one_stock_and_one_payment(self):
        with tenant_context(self.a): self.incoming(1);sale,item=self.sale();key=uuid.uuid4();rows=[{'forma':self.cash_method.pk,'valor':'10'}]
        self.assertEqual(self.race(lambda _:c.finalize(self.operator,sale.public_id,rows,key)),['OK','OK'])
        with tenant_context(self.a): self.assertEqual((m.Pagamento.objects.count(),g.Movimentacao.objects.filter(tipo='SAIDA').count()),(1,1))
    def test_two_cash_sessions_compete_for_last_item(self):
        with tenant_context(self.a):
            self.incoming(1);first,item=self.sale()
            account=m.ContaBancaria.objects.create(nome='Segundo caixa',tipo='CAIXA');second_session=c.open_cash(self.operator,account.pk,0,uuid.uuid4())
            second=c.new_sale(self.operator,second_session.public_id,self.depot.pk);c.add_item(self.operator,second.public_id,self.part.sku,1)
            sales=[first,second]
        results=self.race(lambda index:self.paid(sales[index]))
        self.assertCountEqual(results,['OK','BLOQUEADO'])
        with tenant_context(self.a):
            self.part.refresh_from_db();self.assertEqual(self.part.quantidade_atual,0);self.assertEqual(m.Pagamento.objects.count(),1)
    def test_two_reservations_cannot_overcommit_last_item(self):
        with tenant_context(self.a):
            self.incoming(1);m.ConfiguracaoPDV.objects.create(reservar_rascunho=True)
            first=c.new_sale(self.operator,self.session.public_id,self.depot.pk)
            account=m.ContaBancaria.objects.create(nome='Reserva caixa B',tipo='CAIXA');other=c.open_cash(self.operator,account.pk,0,uuid.uuid4());second=c.new_sale(self.operator,other.public_id,self.depot.pk)
            sales=[first,second]
        self.assertCountEqual(self.race(lambda index:c.add_item(self.operator,sales[index].public_id,self.part.sku,1)),['OK','BLOQUEADO'])
        with tenant_context(self.a): self.assertEqual(m.ReservaEstoque.objects.filter(status='ATIVA').count(),1)
    def test_cash_close_is_serial_and_idempotent(self):
        self.assertEqual(self.race(lambda _:c.close_cash(self.operator,self.session.public_id,0)),['OK','OK'])
        with tenant_context(self.a): self.assertEqual(m.SessaoCaixa.objects.filter(fechado_em__isnull=False).count(),1)
    def test_cash_close_racing_with_finalization_never_leaves_partial_sale(self):
        with tenant_context(self.a): self.incoming(1);sale,item=self.sale()
        self.race(lambda index:self.paid(sale) if index==0 else c.close_cash(self.operator,self.session.public_id,0,'Contagem simultânea'))
        with tenant_context(self.a):
            sale.refresh_from_db();self.part.refresh_from_db()
            if sale.status=='FINALIZADA': self.assertEqual((self.part.quantidade_atual,m.Pagamento.objects.count()),(0,1))
            else: self.assertEqual((self.part.quantidade_atual,m.Pagamento.objects.count(),g.Lancamento.objects.count()),(1,0,0))
    def test_double_return_creates_only_one_refund_and_restores_one_item(self):
        with tenant_context(self.a): self.incoming(1);sale,item=self.sale();self.paid(sale);key=uuid.uuid4();rows=[{'item':item.pk,'quantidade':'1'}]
        self.assertEqual(self.race(lambda _:c.return_sale(self.admin,sale.public_id,rows,'Devolução',key)),['OK','OK'])
        with tenant_context(self.a):
            self.part.refresh_from_db();self.assertEqual((self.part.quantidade_atual,m.DevolucaoVenda.objects.count(),g.Lancamento.objects.filter(tipo='PAGAR').count()),(1,1,1))
    def test_distinct_returns_cannot_exceed_original_quantity(self):
        with tenant_context(self.a): self.incoming(1);sale,item=self.sale();self.paid(sale);rows=[{'item':item.pk,'quantidade':'1'}]
        self.assertCountEqual(self.race(lambda _:c.return_sale(self.admin,sale.public_id,rows,'Devolução',uuid.uuid4())),['OK','BLOQUEADO'])
    def test_duplicate_purchase_receipt_preserves_final_account(self):
        with tenant_context(self.a): purchase,item=self.purchase(1);key=uuid.uuid4();rows=[{'item_id':item.pk,'quantidade':1,'lote':'ÚNICO'}]
        self.assertEqual(self.race(lambda _:s.receber_compra(self.admin,purchase.pk,rows,key)),['OK','OK'])
        with tenant_context(self.a): self.assertEqual((m.RecebimentoCompra.objects.count(),g.Lancamento.objects.filter(tipo='PAGAR').count()),(1,1))
    def test_quote_conversion_is_unique_under_concurrency(self):
        with tenant_context(self.a):
            quote=g.Orcamento.objects.create(cliente=self.da['customer'],validade=self.today,criado_por=self.admin)
            g.ItemOrcamento.objects.create(orcamento=quote,tipo='PECA',peca=self.part,descricao='Produto',quantidade=1,valor_unitario=10)
            from gestao import services as gs
            gs.status_orcamento(self.admin,quote.pk,'enviar');gs.status_orcamento(self.admin,quote.pk,'aprovar')
        self.assertEqual(self.race(lambda _:c.quote_to_sale(self.operator,quote.pk,self.session.public_id,self.depot.pk)),['OK','OK'])
        with tenant_context(self.a): self.assertEqual(m.Venda.objects.filter(orcamento_origem=quote).count(),1)

@skipUnless(connection.vendor=='postgresql','Concorrência exige PostgreSQL real')
class PointConcurrencyTests(WorkforceData,TransactionTestCase):
    race=previous_tests.OperacaoPostgreSQLTests.race
    def setUp(self): self.setup_workforce()
    def test_same_point_token_records_one_immutable_mark(self):
        key=uuid.uuid4()
        with patch('operacao.workforce.timezone.now',return_value=self.instant(8)):
            self.assertEqual(self.race(lambda _:w.mark(self.worker,'ENTRADA',key)),['OK','OK'])
        with tenant_context(self.a): self.assertEqual(m.MarcacaoPonto.objects.count(),1)
    def test_distinct_point_tokens_do_not_duplicate_entry_sequence(self):
        with patch('operacao.workforce.timezone.now',return_value=self.instant(8)):
            self.assertCountEqual(self.race(lambda _:w.mark(self.worker,'ENTRADA',uuid.uuid4())),['OK','BLOQUEADO'])
