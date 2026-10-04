"""Regressões do Bloco 1 sobre os mesmos models e fluxos do ERP."""
import importlib
import uuid
from decimal import Decimal
from unittest import skipUnless
from django.apps import apps
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from gestao.tests import Dados
from gestao import models as g, services as gs, reporting
from gestao.financial_origin import origin_query, origin_type_query
from ordens.models import OrdemServico
from platform_core.context import tenant_context
from . import models as m, services as s, stock
from .reporting import financial_dashboard, report_data
from . import tests as previous_tests


class StabilizationTests(Dados, TestCase):
    def setUp(self):
        self.prepare_data()
        self.today = timezone.localdate()
        with tenant_context(self.a):
            self.part = self.da['part']
            self.depot = m.Deposito.objects.create(nome='Estabilização')
            self.supplier = g.Fornecedor.objects.create(nome='Fornecedor de teste')

    def incoming(self, quantity, cost, days=30, number='LOTE'):
        movement = gs.movimentar(self.admin,self.part.pk,'ENTRADA',Decimal(str(quantity)),destino_id=self.depot.pk,lote_data={'numero':number,'validade':self.today+timezone.timedelta(days=days),'custo_unitario':Decimal(str(cost))})
        return movement.lotes_movimentados.get().lote

    def purchase(self, status, quantity=3):
        row=m.Compra.objects.create(fornecedor=self.supplier,deposito=self.depot,necessidade='Reposição',vencimento=self.today,criado_por=self.admin)
        m.ItemCompra.objects.create(compra=row,peca=self.part,quantidade=quantity,custo_unitario=10,lote='COMPRA',validade=self.today+timezone.timedelta(days=120))
        if status in ['APROVADA','PEDIDO','RECEBIDA']:
            s.compra_acao(self.admin,row.pk,'aprovar')
        if status in ['PEDIDO','RECEBIDA']:
            s.compra_acao(self.admin,row.pk,'pedir')
        if status=='RECEBIDA':
            s.compra_acao(self.admin,row.pk,'receber')
        elif status=='CANCELADA':
            s.compra_acao(self.admin,row.pk,'cancelar')
        row.refresh_from_db()
        return row

    def test_centavos_dizimas_somatorio_exato_e_parcelas_positivas(self):
        with tenant_context(self.a):
            for value,count in [('100.00',3),('0.09',6),('0.07',6),('73.25',7),('1.00',60),('0.02',2)]:
                with self.subTest(value=value,count=count):
                    original=self.entry(valor=Decimal(value))
                    parts=s.parcelar(self.admin,original.pk,count,self.today)
                    values=[row.lancamento.valor for row in parts]
                    self.assertEqual(sum(values,Decimal('0')),Decimal(value))
                    self.assertTrue(all(v>=Decimal('.01') for v in values))
                    self.assertLessEqual(max(values)-min(values),Decimal('.01'))

    def test_parcelamento_inviavel_rollback_e_reenvio_parametros(self):
        with tenant_context(self.a):
            original=self.entry(valor=Decimal('.01'))
            with self.assertRaises(ValidationError):
                s.parcelar(self.admin,original.pk,2,self.today)
            original.refresh_from_db()
            self.assertEqual(original.status,'PENDENTE')
            self.assertFalse(original.parcelas.exists())
            original=self.entry()
            first=s.parcelar(self.admin,original.pk,3,self.today)
            self.assertEqual([r.pk for r in first],[r.pk for r in s.parcelar(self.admin,original.pk,3,self.today)])
            with self.assertRaises(ValidationError):
                s.parcelar(self.admin,original.pk,2,self.today)

    def test_parcelas_preservam_os_cliente_emissao_competencia_e_filtros(self):
        with tenant_context(self.a):
            original=self.entry(cliente=self.da['customer'],ordem=self.da['order'],data_emissao=self.today-timezone.timedelta(days=5),competencia=self.today)
            parts=s.parcelar(self.admin,original.pk,3,self.today)
            self.assertTrue(all(row.lancamento.origem_raiz_id==original.pk for row in parts))
            self.assertTrue(all(row.lancamento.cliente_id==original.cliente_id and row.lancamento.data_emissao==original.data_emissao and row.lancamento.competencia==original.competencia for row in parts))
            self.assertEqual(parts[0].lancamento.origem_financeira,self.da['order'])
            headers,rows=reporting.report_data(self.admin,'receitas',{'equipamento':self.da['equipment']})
            self.assertEqual(len(rows),3)
            self.assertEqual(sum(r[5] for r in rows),original.valor)
            from .history import related
            history = related(self.admin, self.da['customer'], self.da['equipment'])
            ids = {row.pk for row in history['historico_financeiro']}
            self.assertTrue(all(row.lancamento_id in ids for row in parts))
        response=self.client.get(reverse('gestao:lancamento_lista'),{'origem':'OS','ordem':self.da['order'].pk,'status':'PENDENTE'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['page_obj'].paginator.count,3)

    def test_indicadores_nao_classificam_parcelas_os_como_manual(self):
        with tenant_context(self.a):
            original=self.entry(cliente=self.da['customer'],ordem=self.da['order'],valor=90)
            s.parcelar(self.admin,original.pk,3,self.today)
        response=self.client.get(reverse('core:painel'))
        values=dict(response.context['revenue_categories'])
        self.assertEqual(values['Serviços'],90)
        self.assertEqual(values['Sem classificação'],0)

    def test_cancelamento_os_nao_deixa_parcelas_pendentes(self):
        with tenant_context(self.a):
            original = self.entry(cliente=self.da['customer'], ordem=self.da['order'])
            parts = s.parcelar(self.admin, original.pk, 3, self.today)
            s.transicao_os(self.admin, self.da['order'].pk, 'cancelar', 'Cancelamento de teste')
            self.assertFalse(g.Lancamento.objects.filter(pk__in=[row.lancamento_id for row in parts]).exclude(status='CANCELADO').exists())

    def test_cancelamento_os_bloqueado_com_pagamento_parcial_em_parcela(self):
        with tenant_context(self.a):
            original = self.entry(cliente=self.da['customer'], ordem=self.da['order'])
            parts = s.parcelar(self.admin, original.pk, 3, self.today)
            s.pagar(self.admin, parts[0].lancamento_id, Decimal('.01'), self.today)
            with self.assertRaises(ValidationError):
                s.transicao_os(self.admin, self.da['order'].pk, 'cancelar', 'Cancelamento de teste')
            self.da['order'].refresh_from_db()
            self.assertNotEqual(self.da['order'].status, 'CANCELADA')

    def test_origem_orcamento_e_contrato_sem_duplicar_fk_unica(self):
        with tenant_context(self.a):
            quote=self.quote()
            contract=g.Contrato.objects.create(numero='CT-STAB',cliente=self.da['customer'],data_inicial=self.today,data_final=self.today+timezone.timedelta(days=365),valor=40)
            for field,origin in [('orcamento',quote),('contrato',contract)]:
                original=self.entry(cliente=self.da['customer'],**{field:origin})
                parts=s.parcelar(self.admin,original.pk,3,self.today)
                self.assertTrue(all(row.lancamento.origem_financeira==origin for row in parts))
                self.assertEqual(g.Lancamento.objects.filter(origin_query(**{field:origin})).exclude(status='CANCELADO').count(),3)
                self.assertTrue(all(getattr(row.lancamento,field+'_id') is None for row in parts))

    def test_origem_venda_compra_preservada_no_parcelamento(self):
        with tenant_context(self.a):
            purchase=self.purchase('RECEBIDA')
            sale=m.Venda.objects.create(cliente=self.da['customer'],deposito=self.depot,vencimento=self.today,criado_por=self.admin)
            m.ItemVenda.objects.create(venda=sale,peca=self.part,quantidade=1,valor_unitario=20)
            s.venda_confirmar(self.admin,sale.pk)
            sale.refresh_from_db()
            for origin in [purchase,sale]:
                parts=s.parcelar(self.admin,origin.conta_id,2,self.today)
                self.assertTrue(all(row.lancamento.origem_financeira==origin for row in parts))

    def test_reparcelamento_aponta_raiz_unica(self):
        with tenant_context(self.a):
            root=self.entry(valor=90)
            first=s.parcelar(self.admin,root.pk,3,self.today)
            second=s.parcelar(self.admin,first[0].lancamento_id,2,self.today)
            self.assertTrue(all(row.lancamento.origem_raiz_id==root.pk for row in second))
            self.assertEqual(financial_dashboard(self.today,self.today)['a_receber'],90)

    def test_filtro_manual_separa_parcelas_com_origem_sem_perder_total(self):
        with tenant_context(self.a):
            manual = self.entry(valor=Decimal('10.01'))
            os_entry = self.entry(valor=Decimal('30.00'), ordem=self.da['order'], cliente=self.da['customer'])
            parts = s.parcelar(self.admin, manual.pk, 3, self.today)
            s.parcelar(self.admin, os_entry.pk, 3, self.today)
            rows = g.Lancamento.objects.filter(origin_type_query('MANUAL')).exclude(status='CANCELADO')
            self.assertEqual(set(rows.values_list('pk', flat=True)), {row.lancamento_id for row in parts})
            self.assertEqual(sum(row.valor for row in rows), Decimal('10.01'))

    def test_migration_raiz_legada_preserva_valores_e_relacoes(self):
        migration=importlib.import_module('gestao.migrations.0007_origem_parcelas_existentes')
        with tenant_context(self.a):
            original=self.entry(cliente=self.da['customer'],ordem=self.da['order'])
            old=self.entry(cliente=self.da['customer'],valor=10)
            child=self.entry(cliente=self.da['customer'],valor=5)
            m.Parcela.objects.create(origem=original,lancamento=old,numero=1)
            m.Parcela.objects.create(origem=old,lancamento=child,numero=1)
            before=list(g.Lancamento.objects.values_list('id','valor','status','ordem_id'))
            migration.populate_roots(apps,type('Schema',(),{'connection':connection})())
            old.refresh_from_db();child.refresh_from_db()
            self.assertEqual((old.origem_raiz_id,child.origem_raiz_id),(original.pk,original.pk))
            self.assertEqual(list(g.Lancamento.objects.values_list('id','valor','status','ordem_id')),before)

    def test_parcelas_ou_origem_de_outra_organizacao_rejeitadas(self):
        with tenant_context(self.b):
            other=self.entry(cliente=self.db['customer'],criado_por=self.admin_b)
        with tenant_context(self.a):
            with self.assertRaises(g.Lancamento.DoesNotExist):
                s.parcelar(self.admin,other.pk,3,self.today)
            with self.assertRaises(ValidationError):
                self.entry(origem_raiz=other)

    def test_pagamento_decimal_parcial_quitacao_e_reenvio(self):
        with tenant_context(self.a):
            entry=self.entry(valor=Decimal('.30'))
            token=uuid.uuid4()
            first=s.pagar(self.admin,entry.pk,Decimal('.10'),self.today,request_id=token)
            self.assertEqual(first.pk,s.pagar(self.admin,entry.pk,Decimal('.10'),self.today,request_id=token).pk)
            entry.refresh_from_db();self.assertEqual(entry.saldo,Decimal('.20'))
            self.assertEqual(entry.status,'PENDENTE')
            s.pagar(self.admin,entry.pk,Decimal('.20'),self.today)
            entry.refresh_from_db();self.assertEqual(entry.saldo,0)
            self.assertEqual(entry.status,'LIQUIDADO')
            self.assertEqual(m.Pagamento.objects.count(),2)
            self.assertEqual(financial_dashboard(self.today,self.today)['recebido'],Decimal('.30'))
            with self.assertRaises(ValidationError):
                s.pagar(self.admin,entry.pk,Decimal('.01'),self.today)

    def test_pagamento_sem_banco_rastreavel_na_tela_relatorio_e_indicador(self):
        with tenant_context(self.a):
            entry=self.entry()
            payment=s.pagar(self.admin,entry.pk,10,self.today)
            self.assertIn('Não bancarizado',payment.controle_caixa)
            self.assertFalse(m.MovimentoCaixa.objects.exists())
            self.assertEqual(financial_dashboard(self.today,self.today)['recebido_nao_bancarizado'],10)
            headers,rows=report_data(self.admin,'recebimentos',{})
            self.assertIn('Não bancarizado',rows[0][4])
        self.assertContains(self.client.get(reverse('gestao:lancamento_detalhe',args=[entry.pk])),'Não bancarizado')

    def test_pagamento_parcela_mantem_origem_cliente_e_banco(self):
        with tenant_context(self.a):
            root=self.entry(cliente=self.da['customer'],ordem=self.da['order'])
            parcel=s.parcelar(self.admin,root.pk,3,self.today)[0].lancamento
            account=m.ContaBancaria.objects.create(nome='Banco')
            token=uuid.uuid4()
            payment=s.pagar(self.admin,parcel.pk,4,self.today,account_id=account.pk,request_id=token)
            self.assertEqual(payment.origem_financeira,self.da['order'])
            self.assertEqual(payment.lancamento.cliente_id,root.cliente_id)
            self.assertEqual(account.saldo,4)
            self.assertEqual(account.movimentos.get().referencia,token)
            self.assertEqual(financial_dashboard(self.today,self.today)['recebido_nao_bancarizado'],0)

    def test_liquidacao_integral_depois_de_parcial_nao_duplica(self):
        with tenant_context(self.a):
            entry=self.entry()
            s.pagar(self.admin,entry.pk,10,self.today)
            gs.liquidar(self.admin,entry.pk,self.today)
            self.assertEqual(sum(entry.pagamentos.values_list('valor',flat=True)),30)
            self.assertEqual(financial_dashboard(self.today,self.today)['recebido'],30)

    def test_pagamento_invalido_sem_baixa_e_isolamento(self):
        with tenant_context(self.b):
            bank=m.ContaBancaria.objects.create(nome='Banco B')
        with tenant_context(self.a):
            entry=self.entry()
            for value in [Decimal('NaN'),Decimal('Infinity'),Decimal('0'),Decimal('-1'),Decimal('.001'),Decimal('31')]:
                with self.assertRaises(ValidationError):
                    s.pagar(self.admin,entry.pk,value,self.today)
            with self.assertRaises(m.ContaBancaria.DoesNotExist):
                s.pagar(self.admin,entry.pk,1,self.today,account_id=bank.pk)
            self.assertFalse(m.Pagamento.objects.exists())

    def test_mesmo_uuid_isolado_por_organizacao(self):
        token=uuid.uuid4()
        with tenant_context(self.a):
            a=self.entry()
            s.pagar(self.admin,a.pk,5,self.today,request_id=token)
        with tenant_context(self.b):
            b=self.entry(criado_por=self.admin_b)
            s.pagar(self.admin_b,b.pk,7,self.today,request_id=token)
            self.assertEqual(m.Pagamento.objects.get().valor,7)
        with tenant_context(self.a):
            self.assertEqual(m.Pagamento.objects.get().valor,5)

    def test_fefo_multiplos_lotes_custo_exato_e_os(self):
        with tenant_context(self.a):
            self.incoming(2,10,7,'CEDO');self.incoming(2,25,30,'TARDE')
            expired=self.incoming(3,99,-1,'VENCIDO')
            move=gs.movimentar(self.admin,self.part.pk,'OS',3,ordem_id=self.da['order'].pk,origem_id=self.depot.pk)
            self.assertEqual(move.custo_total,45)
            self.assertEqual(move.custo_unitario,15)
            self.assertEqual(list(move.lotes_movimentados.values_list('lote__numero','variacao','custo_unitario','custo_total')),[('CEDO',Decimal('-2'),Decimal('10'),Decimal('20')),('TARDE',Decimal('-1'),Decimal('25'),Decimal('25'))])
            self.assertEqual(self.da['order'].custo_pecas,45)
            self.assertEqual(gs.pecas_snapshot(self.da['order'])[0]['custo_total'],'45.00000')
            expired.refresh_from_db();self.assertEqual(expired.quantidade,3)

    def test_quantidade_fracionaria_custo_total_sem_perda(self):
        with tenant_context(self.a):
            self.incoming('1.333','2.57')
            move=gs.movimentar(self.admin,self.part.pk,'SAIDA',Decimal('1.333'),origem_id=self.depot.pk)
            self.assertEqual(move.custo_total,Decimal('3.42581'))
            self.assertEqual(move.lotes_movimentados.get().custo_total,Decimal('3.42581'))

    def test_consumo_insuficiente_e_vencido_rollback_custos_saldos(self):
        with tenant_context(self.a):
            valid=self.incoming(1,20);expired=self.incoming(2,99,-1,'VENCIDO')
            before=g.Movimentacao.objects.count()
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin,self.part.pk,'OS',2,ordem_id=self.da['order'].pk,origem_id=self.depot.pk)
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin,self.part.pk,'SAIDA',1,origem_id=self.depot.pk,lote_id=expired.pk)
            self.assertEqual(g.Movimentacao.objects.count(),before)
            valid.refresh_from_db();self.assertEqual(valid.quantidade,1)

    def test_devolucao_parcial_recupera_lotes_e_custo_original(self):
        with tenant_context(self.a):
            a=self.incoming(2,10,7,'A');b=self.incoming(2,25,30,'B')
            gs.movimentar(self.admin,self.part.pk,'OS',3,ordem_id=self.da['order'].pk,origem_id=self.depot.pk)
            returned=gs.movimentar(self.admin,self.part.pk,'DEVOLUCAO',Decimal('2.5'),ordem_id=self.da['order'].pk,destino_id=self.depot.pk)
            self.assertEqual(returned.custo_total,Decimal('32.50'))
            self.assertEqual(self.da['order'].custo_pecas,Decimal('12.50'))
            a.refresh_from_db();b.refresh_from_db()
            self.assertEqual((a.quantidade,b.quantidade),(2,Decimal('1.5')))
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin,self.part.pk,'DEVOLUCAO',1,ordem_id=self.da['order'].pk,destino_id=self.depot.pk)

    def test_devolucao_legada_reverte_custo_documentado_sem_reescrever_saida(self):
        with tenant_context(self.a):
            lot = self.incoming(1, 25, 30, 'LEGADO')
            outgoing = gs.movimentar(self.admin, self.part.pk, 'OS', 1, origem_id=self.depot.pk, ordem_id=self.da['order'].pk)
            # Fixture do schema anterior: custo cadastral na saída, sem snapshots econômicos de lote.
            g.Movimentacao.all_objects.filter(pk=outgoing.pk).update(custo_total=None, custo_unitario=Decimal('10.00'))
            m.MovimentacaoLote.all_objects.filter(movimentacao=outgoing).update(custo_total=None, custo_unitario=None)
            returned = gs.movimentar(self.admin, self.part.pk, 'DEVOLUCAO', 1, destino_id=self.depot.pk, ordem_id=self.da['order'].pk)
            self.assertEqual(returned.valor_custo, Decimal('10.00'))
            self.assertEqual(self.da['order'].custo_pecas, Decimal('0'))
            outgoing.refresh_from_db(); lot.refresh_from_db()
            self.assertIsNone(outgoing.custo_total)
            self.assertEqual(outgoing.custo_unitario, Decimal('10.00'))
            self.assertEqual((lot.quantidade, lot.custo_unitario), (Decimal('1'), Decimal('25.00')))

    def test_venda_custo_real_margem_e_reenvio(self):
        with tenant_context(self.a):
            self.incoming(2,10,7,'A');self.incoming(2,25,30,'B')
            sale=m.Venda.objects.create(cliente=self.da['customer'],deposito=self.depot,vencimento=self.today,criado_por=self.admin)
            item=m.ItemVenda.objects.create(venda=sale,peca=self.part,quantidade=3,valor_unitario=20,custo_unitario=99)
            s.venda_confirmar(self.admin,sale.pk);s.venda_confirmar(self.admin,sale.pk)
            item.refresh_from_db()
            self.assertEqual((item.custo_total,item.custo_unitario,item.margem),(45,15,15))
            self.assertEqual(g.Movimentacao.objects.filter(tipo='SAIDA').count(),1)

    def test_transferencia_nao_duplica_custo_e_preserva_lote(self):
        with tenant_context(self.a):
            self.incoming(3,Decimal('4.27'))
            target=m.Deposito.objects.create(nome='Destino')
            move=gs.movimentar(self.admin,self.part.pk,'TRANSFER',2,origem_id=self.depot.pk,destino_id=target.pk)
            self.assertEqual(move.custo_total,Decimal('8.54'))
            self.assertEqual(move.lotes_movimentados.count(),2)
            self.assertEqual(m.LoteEstoque.objects.get(deposito=target).custo_unitario,Decimal('4.27'))

    def test_movimento_custo_imutavel_e_isolamento_lotes(self):
        with tenant_context(self.a):
            self.incoming(1,25)
            move=gs.movimentar(self.admin,self.part.pk,'SAIDA',1,origem_id=self.depot.pk)
            move.custo_total=1
            with self.assertRaises(ValidationError):
                move.save()
        with tenant_context(self.b):
            self.assertFalse(g.Movimentacao.objects.filter(pk=move.pk).exists())
            self.assertFalse(m.MovimentacaoLote.objects.filter(movimentacao_id=move.pk).exists())

    def test_somente_aprovada_pedido_abatem_reposicao(self):
        with tenant_context(self.a):
            self.part.estoque_maximo=10;self.part.save()
            self.purchase('RASCUNHO',100);self.purchase('CANCELADA',100)
            self.assertEqual(stock.metrics(self.part)['sugerido'],10)
            self.purchase('APROVADA',2);self.purchase('PEDIDO',3)
            data=stock.metrics(self.part)
            self.assertEqual((data['em_compra'],data['em_solicitacao'],data['sugerido']),(5,100,5))

    def test_recebimento_sai_pendente_e_entra_fisico_sem_duplo_desconto(self):
        with tenant_context(self.a):
            self.part.estoque_minimo=5;self.part.estoque_maximo=10;self.part.save()
            self.purchase('RECEBIDA',3)
            data=stock.metrics(self.part)
            self.assertEqual((data['fisico'],data['em_compra'],data['sugerido']),(3,0,7))

    def test_reservas_e_pendencias_por_organizacao_na_reposicao(self):
        with tenant_context(self.a):
            self.part.estoque_minimo=5;self.part.estoque_maximo=10;self.part.save()
            self.incoming(5,10,180)
            stock.reserve(self.admin,self.part.pk,self.depot.pk,1,'OS',order_id=self.da['order'].pk)
            self.purchase('PEDIDO',2)
        with tenant_context(self.b):
            depot=m.Deposito.objects.create(nome='B')
            purchase=m.Compra.objects.create(deposito=depot,necessidade='B',vencimento=self.today,criado_por=self.admin_b)
            m.ItemCompra.objects.create(compra=purchase,peca=self.db['part'],quantidade=100,custo_unitario=10)
            purchase.status='PEDIDO';gs.write(purchase)
        with tenant_context(self.a):
            data=stock.metrics(self.part)
            self.assertEqual((data['fisico'],data['reservado'],data['disponivel'],data['em_compra'],data['sugerido']),(5,1,4,2,4))

    def test_permissoes_financeiro_parcelamento_e_estoque(self):
        with tenant_context(self.a):
            entry=self.entry()
            with self.assertRaises(PermissionDenied):
                s.parcelar(self.users['ESTOQUE'],entry.pk,3,self.today)
            with self.assertRaises(PermissionDenied):
                s.pagar(self.users['TECNICO'],entry.pk,1,self.today)
            with self.assertRaises(PermissionDenied):
                gs.movimentar(self.users['FINANCEIRO'],self.part.pk,'ENTRADA',1)


@skipUnless(connection.vendor=='postgresql','Exige bloqueios PostgreSQL')
class StabilizationPostgreSQLTests(Dados, TransactionTestCase):
    race=previous_tests.OperacaoPostgreSQLTests.race

    def setUp(self):
        self.prepare_data()
        self.today=timezone.localdate()

    def test_parcelamento_concorrente_uma_arvore_de_parcelas(self):
        with tenant_context(self.a):
            entry=self.entry(valor=Decimal('100'))
        self.assertEqual(self.race(lambda i:s.parcelar(self.admin,entry.pk,3,self.today)),['OK','OK'])
        with tenant_context(self.a):
            self.assertEqual(m.Parcela.objects.count(),3)
            self.assertEqual(sum(p.lancamento.valor for p in m.Parcela.objects.all()),100)

    def test_pagamento_mesmo_token_concorrente_uma_baixa(self):
        with tenant_context(self.a):
            entry=self.entry();account=m.ContaBancaria.objects.create(nome='Caixa')
        token=uuid.uuid4()
        self.assertEqual(self.race(lambda i:s.pagar(self.admin,entry.pk,10,self.today,account_id=account.pk,request_id=token)),['OK','OK'])
        with tenant_context(self.a):
            self.assertEqual((m.Pagamento.objects.count(),m.MovimentoCaixa.objects.count()),(1,1))
            self.assertEqual(g.Lancamento.objects.get(pk=entry.pk).saldo,20)

    def test_token_disputado_entre_contas_rollback_da_baixa_perdedora(self):
        with tenant_context(self.a):
            entries=[self.entry(),self.entry()]
            accounts=[m.ContaBancaria.objects.create(nome='Banco A'),m.ContaBancaria.objects.create(nome='Banco B')]
        token=uuid.uuid4()
        results=self.race(lambda i:s.pagar(self.admin,entries[i].pk,10,self.today,account_id=accounts[i].pk,request_id=token))
        self.assertCountEqual(results,['OK','BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual((m.Pagamento.objects.count(),m.MovimentoCaixa.objects.count()),(1,1))
            self.assertEqual(sum(a.saldo for a in accounts),10)

    def test_fefo_concorrente_preserva_custo_e_saldo(self):
        with tenant_context(self.a):
            part=self.da['part'];depot=m.Deposito.objects.create(nome='Concorrência')
            gs.movimentar(self.admin,part.pk,'ENTRADA',5,destino_id=depot.pk,lote_data={'numero':'UNICO','custo_unitario':Decimal('7.33'),'validade':self.today+timezone.timedelta(days=30)})
        self.assertCountEqual(self.race(lambda i:gs.movimentar(self.admin,part.pk,'SAIDA',4,origem_id=depot.pk)),['OK','BLOQUEADO'])
        with tenant_context(self.a):
            move=g.Movimentacao.objects.get(tipo='SAIDA')
            self.assertEqual(move.custo_total,Decimal('29.32'))
            self.assertEqual(m.LoteEstoque.objects.get().quantidade,1)

    def test_devolucao_concorrente_nao_restaura_consumo_duas_vezes(self):
        with tenant_context(self.a):
            part=self.da['part'];order=self.da['order']
            gs.movimentar(self.admin,part.pk,'ENTRADA',1,lote_data={'numero':'OS','custo_unitario':Decimal('9.99')})
            gs.movimentar(self.admin,part.pk,'OS',1,ordem_id=order.pk)
        self.assertCountEqual(self.race(lambda i:gs.movimentar(self.admin,part.pk,'DEVOLUCAO',1,ordem_id=order.pk)),['OK','BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(g.Movimentacao.objects.get(tipo='DEVOLUCAO').custo_total,Decimal('9.99'))
            self.assertEqual(OrdemServico.objects.get(pk=order.pk).custo_pecas,0)
