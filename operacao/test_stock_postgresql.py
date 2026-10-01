from unittest import skipUnless
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from gestao.tests import Dados
from gestao import services as gs, models as g
from platform_core.context import tenant_context
from . import models as m, stock, stock_scheduler, tests as earlier

@skipUnless(connection.vendor=='postgresql','Exige bloqueios reais do PostgreSQL')
class StockPostgreSQLTests(Dados,TransactionTestCase):
    race=earlier.OperacaoPostgreSQLTests.race

    def setUp(self):
        self.prepare_data()
        with tenant_context(self.a):
            self.part=self.da['part']
            self.depot=m.Deposito.objects.create(nome='Depósito concorrente')
            m.Configuracao.objects.create()
            gs.movimentar(self.admin,self.part.pk,'ENTRADA',5,'Entrada',destino_id=self.depot.pk,lote_data={'numero':'ULTIMO','validade':timezone.localdate()+timezone.timedelta(days=15)})

    def test_fefo_concorrente_nao_duplica_baixa_do_lote(self):
        results=self.race(lambda index:gs.movimentar(self.admin,self.part.pk,'SAIDA',4,'Saída',origem_id=self.depot.pk))
        self.assertCountEqual(results,['OK','BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(m.LoteEstoque.objects.get(peca=self.part).quantidade,1)
            self.assertEqual(g.Peca.objects.get(pk=self.part.pk).quantidade_atual,1)
            self.assertEqual(m.SaldoDeposito.objects.get(peca=self.part,deposito=self.depot).quantidade,1)
            self.assertEqual(stock.total(m.SaldoDeposito.objects.filter(peca=self.part)),1)

    def test_reserva_concorrente_protege_disponibilidade(self):
        results=self.race(lambda index:stock.reserve(self.admin,self.part.pk,self.depot.pk,4,'Separação'))
        self.assertCountEqual(results,['OK','BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(m.ReservaEstoque.objects.count(),1)
            self.assertEqual(stock.metrics(self.part)['disponivel'],1)

    def test_runners_concorrentes_geram_uma_ocorrencia_e_um_relatorio(self):
        self.race(lambda index:stock_scheduler.tick(self.admin,timezone.now()+timezone.timedelta(days=7)))
        with tenant_context(self.a):
            self.assertEqual(m.OcorrenciaEstoque.objects.filter(tipo='VALIDADE').count(),1)
            self.assertEqual(m.RelatorioEstoque.objects.filter(automatico=True).count(),1)
