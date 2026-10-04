import uuid
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.db.models import Sum
from gestao.tests import Dados
from gestao import models as g, services as gs
from platform_core.context import tenant_context
from platform_core.models import PlatformAudit
from . import models as m, stock, services, stock_scheduler, stock_forms

class StockTests(Dados,TestCase):
    def setUp(self):
        self.prepare_data()
        self.today=timezone.localdate()
        with tenant_context(self.a):
            self.part=self.da['part']
            self.depot=m.Deposito.objects.create(nome='Almoxarifado')
            self.supplier=g.Fornecedor.objects.create(nome='Fornecedor do lote')
            self.config=m.Configuracao.objects.create()
            self.part.estoque_maximo=10
            self.part.save()

    def entry(self,quantity=10,days=None,number='L1',**extra):
        data={'numero':number,'validade':self.today+timezone.timedelta(days=days) if days is not None else None,'fornecedor':self.supplier,'custo_unitario':Decimal('12.50'),**extra}
        movement=gs.movimentar(self.admin,self.part.pk,'ENTRADA',quantity,'Entrada de teste',destino_id=self.depot.pk,lote_data=data)
        return movement.lotes_movimentados.get().lote

    def purchase(self,quantity=4,approved=False):
        purchase=m.Compra.objects.create(fornecedor=self.supplier,deposito=self.depot,necessidade='Reposição',vencimento=self.today,criado_por=self.admin)
        m.ItemCompra.objects.create(compra=purchase,peca=self.part,quantidade=quantity,custo_unitario=10,lote='COMPRA',validade=self.today+timezone.timedelta(days=180))
        if approved:
            services.compra_acao(self.admin,purchase.pk,'aprovar')
        return purchase

    def invariant(self):
        self.part.refresh_from_db()
        self.assertEqual(stock.total(self.part.lotes.all()),self.part.quantidade_atual)
        self.assertEqual(stock.total(m.SaldoDeposito.objects.filter(peca=self.part)),self.part.quantidade_atual)
        for balance in m.SaldoDeposito.objects.filter(peca=self.part):
            self.assertEqual(stock.total(self.part.lotes.filter(deposito=balance.deposito)),balance.quantidade)

    def test_multiplos_lotes_preservam_metadados_e_saldo(self):
        with tenant_context(self.a):
            a=self.entry(4,7,'A',fabricacao=self.today-timezone.timedelta(days=7),documento_entrada='NF de teste',localizacao='Prateleira 1')
            b=self.entry(6,60,'B')
            self.assertNotEqual(a.pk,b.pk)
            self.assertEqual((a.numero,a.fornecedor,a.custo_unitario,a.documento_entrada),('A',self.supplier,Decimal('12.50'),'NF de teste'))
            self.assertEqual(self.part.lotes.count(),2)
            self.invariant()

    def test_fefo_ignora_vencido_e_consume_vencimento_mais_proximo(self):
        with tenant_context(self.a):
            late=self.entry(6,60,'TARDIO')
            early=self.entry(2,7,'CEDO')
            expired=self.entry(3,-1,'VENCIDO')
            move=gs.movimentar(self.admin,self.part.pk,'SAIDA',3,'Teste FEFO',origem_id=self.depot.pk)
            early.refresh_from_db();late.refresh_from_db();expired.refresh_from_db()
            self.assertEqual((early.quantidade,late.quantidade,expired.quantidade),(0,5,3))
            self.assertEqual(move.lotes_movimentados.count(),2)
            self.invariant()

    def test_fefo_prioriza_lotes_com_validade_antes_dos_sem_validade(self):
        with tenant_context(self.a):
            unlimited=self.entry(3,None,'SEM PRAZO')
            expiry=self.entry(2,30,'PRAZO')
            gs.movimentar(self.admin,self.part.pk,'SAIDA',2,origem_id=self.depot.pk)
            expiry.refresh_from_db();unlimited.refresh_from_db()
            self.assertEqual((expiry.quantidade,unlimited.quantidade),(0,3))

    def test_lote_vencido_bloqueia_saida_os_e_venda_sem_baixa_parcial(self):
        with tenant_context(self.a):
            self.entry(5,-1)
            for kind in ['SAIDA','OS']:
                with self.assertRaises(ValidationError):
                    gs.movimentar(self.admin,self.part.pk,kind,1,origem_id=self.depot.pk,ordem_id=self.da['order'].pk if kind=='OS' else None)
            sale=m.Venda.objects.create(cliente=self.da['customer'],deposito=self.depot,vencimento=self.today,criado_por=self.admin)
            m.ItemVenda.objects.create(venda=sale,peca=self.part,quantidade=1,valor_unitario=30)
            with self.assertRaises(ValidationError):
                services.venda_confirmar(self.admin,sale.pk)
            self.assertFalse(g.Lancamento.objects.exists())
            self.invariant()

    def test_lote_valido_na_data_limite(self):
        with tenant_context(self.a):
            lot=self.entry(1,0)
            gs.movimentar(self.admin,self.part.pk,'SAIDA',1,origem_id=self.depot.pk)
            lot.refresh_from_db();self.assertEqual(lot.quantidade,0)

    def test_validade_global_legada_nao_sobrepoe_lote_identificado(self):
        with tenant_context(self.a):
            self.part.validade=self.today-timezone.timedelta(days=1)
            self.part.save()
            self.entry(2,30)
            gs.movimentar(self.admin,self.part.pk,'OS',1,origem_id=self.depot.pk,ordem_id=self.da['order'].pk)
            self.invariant()

    def test_produto_com_validade_exige_metadados_na_entrada(self):
        with tenant_context(self.a):
            self.part.controla_validade=True;self.part.save()
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin,self.part.pk,'ENTRADA',1,destino_id=self.depot.pk)
            self.entry(2,90)
            self.invariant()

    def test_classificacoes_de_validade(self):
        with tenant_context(self.a):
            for days,label in [(-1,'VENCIDO'),(0,'7'),(7,'7'),(8,'15'),(15,'15'),(16,'30'),(30,'30'),(31,'60'),(60,'60'),(61,'90'),(90,'90'),(91,'VALIDADE NORMAL')]:
                lot=self.entry(1,days,str(days))
                expected=label if label in ['VENCIDO','VALIDADE NORMAL'] else f'VENCE EM ATÉ {label} DIAS'
                self.assertEqual(lot.classificacao,expected)

    def test_alertas_de_90_60_30_15_7_dias_e_vencido(self):
        with tenant_context(self.a):
            for days in [90,60,30,15,7,-1]:
                lot=self.entry(10,days,str(days))
                stock.scan_stock(self.admin)
                event=m.OcorrenciaEstoque.objects.get(lote=lot,resolvida_em__isnull=True)
                self.assertEqual(event.situacao,'VENCIDO' if days<0 else f'VENCE EM ATÉ {days} DIAS')
            lot=self.entry(1,91,'NORMAL')
            stock.scan_stock(self.admin)
            self.assertFalse(m.OcorrenciaEstoque.objects.filter(lote=lot).exists())

    def test_estoque_no_minimo_e_zerado(self):
        with tenant_context(self.a):
            stock.scan_stock(self.admin)
            event=m.OcorrenciaEstoque.objects.get(tipo='REPOSICAO')
            self.assertEqual(event.situacao,'ZERADO')
            self.entry(2,None)
            stock.scan_stock(self.admin)
            event.refresh_from_db()
            self.assertEqual(event.situacao,'ESTOQUE BAIXO')

    def test_alerta_nao_duplica_resolve_e_reabre_nova_ocorrencia(self):
        with tenant_context(self.a):
            self.entry(2,None)
            stock.scan_stock(self.admin)
            event=m.OcorrenciaEstoque.objects.get(tipo='REPOSICAO')
            notices=m.Notificacao.objects.filter(ocorrencia_estoque=event).count()
            stock.scan_stock(self.admin,timezone.now()+timezone.timedelta(minutes=30))
            self.assertEqual(m.OcorrenciaEstoque.objects.filter(tipo='REPOSICAO').count(),1)
            self.assertEqual(m.Notificacao.objects.filter(ocorrencia_estoque=event).count(),notices)
            self.entry(20,None,'REGULARIZADO')
            stock.scan_stock(self.admin)
            event.refresh_from_db();self.assertIsNotNone(event.resolvida_em)
            self.assertFalse(m.Notificacao.objects.filter(ocorrencia_estoque=event,resolvida_em__isnull=True).exists())
            gs.movimentar(self.admin,self.part.pk,'SAIDA',20,origem_id=self.depot.pk)
            stock.scan_stock(self.admin)
            self.assertEqual(m.OcorrenciaEstoque.objects.filter(tipo='REPOSICAO').count(),2)
            self.assertNotEqual(m.OcorrenciaEstoque.objects.get(tipo='REPOSICAO',resolvida_em__isnull=True).pk,event.pk)

    def test_leitura_da_notificacao_nao_resolve_ocorrencia(self):
        with tenant_context(self.a):
            stock.scan_stock(self.admin)
            event=m.OcorrenciaEstoque.objects.get(tipo='REPOSICAO')
            notice=m.Notificacao.objects.get(usuario=self.admin,ocorrencia_estoque=event)
        self.assertEqual(self.client.post(reverse('operacao:notificacao_lida',args=[notice.pk])).status_code,302)
        with tenant_context(self.a):
            notice.refresh_from_db();event.refresh_from_db()
            self.assertIsNotNone(notice.lida_em)
            self.assertIsNone(event.resolvida_em)
            stock.scan_stock(self.admin)
            notice.refresh_from_db();self.assertIsNotNone(notice.lida_em)

    def test_reserva_reduz_disponivel_e_protege_outros_fluxos(self):
        with tenant_context(self.a):
            self.entry(10,None)
            reserve=stock.reserve(self.admin,self.part.pk,self.depot.pk,7,'OS compromissada',order_id=self.da['order'].pk)
            self.assertEqual(stock.metrics(self.part)['disponivel'],3)
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin,self.part.pk,'SAIDA',4,origem_id=self.depot.pk)
            gs.movimentar(self.admin,self.part.pk,'OS',5,origem_id=self.depot.pk,ordem_id=self.da['order'].pk)
            reserve.refresh_from_db();self.assertEqual(reserve.quantidade,2)
            self.assertEqual(stock.metrics(self.part)['disponivel'],3)
            self.invariant()

    def test_venda_consumindo_sua_reserva_nao_duplica_baixa(self):
        with tenant_context(self.a):
            self.entry(5,None)
            sale=m.Venda.objects.create(cliente=self.da['customer'],deposito=self.depot,vencimento=self.today,criado_por=self.admin)
            m.ItemVenda.objects.create(venda=sale,peca=self.part,quantidade=5,valor_unitario=20)
            reservation=stock.reserve(self.admin,self.part.pk,self.depot.pk,5,'Pedido confirmado para separação',sale_id=sale.pk)
            services.venda_confirmar(self.admin,sale.pk)
            services.venda_confirmar(self.admin,sale.pk)
            reservation.refresh_from_db();self.assertEqual(reservation.status,'CONSUMIDA')
            self.assertEqual(stock.metrics(self.part)['disponivel'],0)
            self.assertEqual(g.Lancamento.objects.count(),1)
            self.invariant()

    def test_liberacao_e_reserva_encerrada_sao_auditadas(self):
        with tenant_context(self.a):
            self.entry(5,None)
            row=stock.reserve(self.admin,self.part.pk,self.depot.pk,3,'Reserva')
            stock.release(self.admin,row.pk,'Necessidade cancelada')
            row.refresh_from_db();self.assertEqual(row.status,'LIBERADA')
            self.assertEqual(stock.metrics(self.part)['disponivel'],5)
            self.assertTrue(PlatformAudit.objects.filter(organization=self.a,action='RESERVA_LIBERADA').exists())

    def test_transferencia_preserva_lote_validade_custo_e_saldos(self):
        with tenant_context(self.a):
            lot=self.entry(10,30)
            destination=m.Deposito.objects.create(nome='Destino')
            move=gs.movimentar(self.admin,self.part.pk,'TRANSFER',4,'Redistribuição',origem_id=self.depot.pk,destino_id=destination.pk)
            target=m.LoteEstoque.objects.get(grupo=lot.grupo,deposito=destination)
            self.assertEqual((target.numero,target.validade,target.custo_unitario,target.quantidade),(lot.numero,lot.validade,lot.custo_unitario,4))
            self.assertEqual(move.lotes_movimentados.count(),2)
            self.invariant()

    def test_devolucao_restaura_lote_original_mesmo_apos_vencimento(self):
        with tenant_context(self.a):
            lot=self.entry(3,1)
            gs.movimentar(self.admin,self.part.pk,'OS',2,origem_id=self.depot.pk,ordem_id=self.da['order'].pk)
            with patch('operacao.stock.timezone.localdate',return_value=self.today+timezone.timedelta(days=2)):
                gs.movimentar(self.admin,self.part.pk,'DEVOLUCAO',1,destino_id=self.depot.pk,ordem_id=self.da['order'].pk)
                self.assertEqual(stock.total(stock.valid_lots(self.part)),0)
            lot.refresh_from_db();self.assertEqual(lot.quantidade,2)
            self.assertEqual(self.part.lotes.count(),1)
            self.invariant()

    def test_descarte_vencido_exige_ajuste_lote_e_motivo(self):
        with tenant_context(self.a):
            lot=self.entry(3,-1)
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin,self.part.pk,'SAIDA',1,origem_id=self.depot.pk,lote_id=lot.pk)
            # Ajuste global atual usa Principal; transferir fisicamente para ele.
            principal=m.Deposito.objects.get(nome='Principal')
            gs.movimentar(self.admin,self.part.pk,'TRANSFER',3,'Separar para descarte',origem_id=self.depot.pk,destino_id=principal.pk,lote_id=lot.pk)
            target=m.LoteEstoque.objects.get(grupo=lot.grupo,deposito=principal)
            gs.movimentar(self.admin,self.part.pk,'AJUSTE',0,'Descarte autorizado de vencido',lote_id=target.pk)
            self.invariant()

    def test_edicao_silenciosa_de_lote_e_historico_bloqueada(self):
        with tenant_context(self.a):
            lot=self.entry(3,90)
            lot.quantidade=9
            with self.assertRaises(ValidationError):lot.save()
            detail=m.MovimentacaoLote.objects.first()
            with self.assertRaises(ValidationError):detail.save()
            balance=m.SaldoDeposito.objects.get(peca=self.part,deposito=self.depot)
            with self.assertRaises(ValidationError):balance.save()

    def test_sugestao_ideal_desconta_disponivel_e_compra_pendente(self):
        with tenant_context(self.a):
            self.entry(1,None)
            self.purchase(4,approved=True)
            data=stock.metrics(self.part)
            self.assertEqual((data['disponivel'],data['em_compra'],data['sugerido']),(1,4,5))
            self.purchase(5,approved=True)
            self.assertEqual(stock.metrics(self.part)['sugerido'],0)

    def test_lotes_vencidos_e_vencendo_entram_na_reposicao(self):
        with tenant_context(self.a):
            self.entry(3,-1,'VENCIDO')
            self.entry(4,7,'VENCENDO')
            data=stock.metrics(self.part)
            self.assertEqual((data['fisico'],data['vencido'],data['vencendo'],data['sugerido']),(7,3,4,10))

    def test_consumo_medio_so_aparece_com_historico_suficiente(self):
        with tenant_context(self.a):
            self.entry(100,None)
            move=gs.movimentar(self.admin,self.part.pk,'SAIDA',90,origem_id=self.depot.pk)
            self.assertEqual(stock.metrics(self.part)['consumo_medio'],0)
            g.Movimentacao.all_objects.filter(pk=move.pk).update(criado_em=timezone.now()-timezone.timedelta(days=45))
            data=stock.metrics(self.part)
            self.assertEqual(data['consumo_medio'],1)
            self.assertEqual(data['ideal'],30)

    def test_relatorio_semanal_idempotente_e_historico_imutavel(self):
        with tenant_context(self.a):
            first=stock.generate_report(self.admin)
            again=stock.generate_report(self.admin)
            next_week=stock.generate_report(self.admin,first.semana+timezone.timedelta(days=7))
            self.assertEqual(first.pk,again.pk)
            self.assertNotEqual(first.pk,next_week.pk)
            with self.assertRaises(ValidationError):first.save()
            item=first.itens.get();self.assertEqual(Decimal(item.dados['sugerido']),10)
            self.entry(10,None)
            item.refresh_from_db();self.assertEqual(Decimal(item.dados['sugerido']),10)

    def test_geracao_compra_itens_idempotente_e_recebimento_lote_pagavel(self):
        with tenant_context(self.a):
            report=stock.generate_report(self.admin)
            item=report.itens.get()
            token=uuid.uuid4()
            purchase=stock.report_purchase(self.users['ESTOQUE'],report.pk,{item.pk:10},self.depot.pk,self.today,token)
            self.assertEqual(stock.report_purchase(self.users['ESTOQUE'],report.pk,{item.pk:10},self.depot.pk,self.today,token).pk,purchase.pk)
            self.assertEqual(purchase.itens.count(),1)
            purchase.fornecedor=self.supplier;purchase.save()
            row=purchase.itens.get();row.lote='RECEBIDO';row.validade=self.today+timezone.timedelta(days=365);row.save()
            for action in ['aprovar','pedir','receber','receber']:
                services.compra_acao(self.admin,purchase.pk,action)
            lot=m.LoteEstoque.objects.get(item_compra=row)
            self.assertEqual(lot.quantidade,10)
            self.assertEqual(lot.custo_unitario,10)
            self.assertEqual(g.Lancamento.objects.get().valor,100)
            self.assertEqual(stock.metrics(self.part)['em_compra'],0)
            self.invariant()

    def test_necessidade_coberta_nao_gera_compra_sem_justificativa(self):
        with tenant_context(self.a):
            report=stock.generate_report(self.admin)
            item=report.itens.get()
            self.purchase(10,approved=True)
            with self.assertRaises(ValidationError):
                stock.report_purchase(self.admin,report.pk,{item.pk:10},self.depot.pk,self.today,uuid.uuid4())
            purchase=stock.report_purchase(self.admin,report.pk,{item.pk:2},self.depot.pk,self.today,uuid.uuid4(),'Reserva estratégica revisada pelo gestor')
            self.assertEqual(purchase.itens.get().quantidade,2)

    def test_scheduler_respeita_30_minutos_e_semana(self):
        with tenant_context(self.a):
            monday=self.today-timezone.timedelta(days=self.today.weekday())
            first=timezone.make_aware(timezone.datetime.combine(monday,timezone.datetime.min.time()).replace(hour=8))
            result=stock_scheduler.tick(self.admin,first)
            self.assertEqual(result,{'alertas':True,'relatorio':True})
            self.assertEqual(stock_scheduler.tick(self.admin,first+timezone.timedelta(minutes=29)),{'alertas':False,'relatorio':False})
            self.assertEqual(stock_scheduler.tick(self.admin,first+timezone.timedelta(minutes=30)),{'alertas':True,'relatorio':False})
            self.assertEqual(m.RelatorioEstoque.objects.count(),1)
            stock_scheduler.tick(self.admin,first+timezone.timedelta(days=7))
            self.assertEqual(m.RelatorioEstoque.objects.count(),2)

    def test_scheduler_horario_dia_configurado_desabilitado_e_recuperacao(self):
        with tenant_context(self.a):
            self.config.relatorio_dia_semana=4
            self.config.relatorio_horario=timezone.datetime.min.time().replace(hour=17)
            self.config.save()
            monday=self.today-timezone.timedelta(days=self.today.weekday())
            before=timezone.make_aware(timezone.datetime.combine(monday+timezone.timedelta(days=4),timezone.datetime.min.time()).replace(hour=16,minute=59))
            stock_scheduler.tick(self.admin,before)
            self.assertFalse(m.RelatorioEstoque.objects.exists())
            stock_scheduler.tick(self.admin,before+timezone.timedelta(days=1))
            self.assertEqual(m.RelatorioEstoque.objects.count(),1)
            self.config.refresh_from_db();self.config.relatorio_semanal_ativo=False;self.config.save()
            stock_scheduler.tick(self.admin,before+timezone.timedelta(days=8))
            self.assertEqual(m.RelatorioEstoque.objects.count(),1)

    def test_scheduler_isola_organizacoes_e_nao_herda_contexto(self):
        result=stock_scheduler.run(now=timezone.now()+timezone.timedelta(days=7))
        self.assertTrue(all('erro' not in row for row in result),result)
        with tenant_context(self.a):
            self.assertEqual(m.RelatorioEstoque.objects.count(),1)
            self.assertEqual(m.RelatorioEstoque.objects.get().itens.get().peca_id,self.part.pk)
        with tenant_context(self.b):
            self.assertEqual(m.RelatorioEstoque.objects.count(),1)
            self.assertEqual(m.RelatorioEstoque.objects.get().itens.get().peca_id,self.db['part'].pk)
            self.assertFalse(m.Notificacao.objects.filter(usuario=self.admin).exists())

    def test_relatorios_lotes_reservas_isolados_no_http_e_form(self):
        with tenant_context(self.a):
            lot=self.entry(1,30)
            report=stock.generate_report(self.admin)
            reservation=stock.reserve(self.admin,self.part.pk,self.depot.pk,1,'Reservado')
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(reverse('operacao:stock_report',args=[report.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse('operacao:stock_release',args=[reservation.pk]),{'motivo':'Invasão'}).status_code,404)
        self.assertNotContains(self.client.get(reverse('operacao:stock_lots')),self.part.descricao)
        self.assertEqual(self.client.get(reverse('operacao:stock_lots'),{'peca':self.part.pk}).status_code,404)
        with tenant_context(self.b):
            form=stock_forms.EntradaLoteForm({'peca':self.part.pk,'deposito':self.depot.pk,'numero':'INDEVIDO','quantidade':1,'custo_unitario':1,'motivo':'Invasão','request_id':uuid.uuid4()})
            self.assertFalse(form.is_valid())
            foreign=m.LoteEstoque(peca=self.part,deposito=self.depot,numero='INDEVIDO')
            with self.assertRaises(ValidationError):gs.write(foreign)

    def test_permissoes_admin_gestor_estoque_e_financeiro_tecnico(self):
        for role,user in self.users.items():
            self.client.force_login(user)
            access=role in ['ADMIN','GESTOR','ESTOQUE']
            for name in ['stock_entry','stock_reservations','stock_occurrences','stock_reports']:
                self.assertEqual(self.client.get(reverse('operacao:'+name)).status_code,200 if access else 403,(role,name))
            self.assertEqual(self.client.get(reverse('operacao:stock_config')).status_code,200 if role=='ADMIN' else 403)

    def test_relatorio_pdf_excel_tela_e_post_gerando_compra(self):
        with tenant_context(self.a):
            report=stock.generate_report(self.admin)
            item=report.itens.get()
        for export,magic in [('pdf',b'%PDF-'),('xlsx',b'PK')]:
            response=self.client.get(reverse('operacao:stock_report',args=[report.pk]),{'export':export})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.content.startswith(magic))
            if export=='xlsx':
                from openpyxl import load_workbook
                sheet=load_workbook(BytesIO(response.content)).active
                self.assertEqual(sheet['D2'].data_type,'n')
                self.assertEqual(sheet['B2'].data_type,'s')
        response=self.client.get(reverse('operacao:stock_report',args=[report.pk]))
        self.assertContains(response,'GERAR SOLICITAÇÃO DE COMPRA')
        response=self.client.post(reverse('operacao:stock_report',args=[report.pk]),{'deposito':self.depot.pk,'vencimento':self.today,'request_id':uuid.uuid4(),f'selecionar_{item.pk}':'on',f'quantidade_{item.pk}':'10'})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):self.assertEqual(m.Compra.objects.count(),1)

    def test_csrf_e_dashboard_financeiro_protegidos(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        self.assertEqual(client.post(reverse('operacao:stock_entry'),{}).status_code,403)
        self.client.force_login(self.users['TECNICO'])
        response=self.client.get(reverse('core:painel'))
        self.assertNotContains(response,'Contas e caixa')
        self.assertNotContains(response,'Recebimentos do mês')

    def test_configuracoes_novas_e_dashboard_real_sem_valores_ficticios(self):
        response=self.client.get(reverse('core:painel'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'VERTYX Gestão')
        self.assertEqual(response.context['stock_summary']['repor'],1)
        self.assertEqual(response.context['commercial']['valor'],0)
        self.assertEqual(response.context['contract_count'],0)
        self.assertEqual(self.client.get(reverse('core:painel'),{'periodo':'PERSONALIZADO','inicio':'2026-10-10','fim':'2026-10-01'}).status_code,400)

    def test_recebimento_identifica_lote_sem_alterar_quantidade_aprovada(self):
        with tenant_context(self.a):
            purchase=self.purchase()
            services.compra_acao(self.admin,purchase.pk,'aprovar');services.compra_acao(self.admin,purchase.pk,'pedir')
            item=purchase.itens.get()
        response=self.client.post(reverse('operacao:stock_receipt',args=[purchase.pk,item.pk]),{'lote':'NOVO','validade':self.today+timezone.timedelta(days=90),'quantidade':'999'})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):
            item.refresh_from_db();self.assertEqual((item.lote,item.quantidade),('NOVO',4))
            services.compra_acao(self.admin,purchase.pk,'receber')
            self.assertEqual(m.LoteEstoque.objects.get(item_compra=item).numero,'NOVO')

    def test_filtro_minimo_considera_reservas_e_exibe_pendencias(self):
        with tenant_context(self.a):
            self.entry(10,None)
            stock.reserve(self.admin,self.part.pk,self.depot.pk,8,'Separação da OS',order_id=self.da['order'].pk)
            self.purchase(3)
        response=self.client.get(reverse('gestao:peca_lista'),{'minimo':'1'})
        self.assertContains(response,self.part.sku)
        self.assertContains(response,'Disponível válido')
        self.assertContains(response,'Em compra')

    def test_entrada_nao_ignora_lote_selecionado_incompativel(self):
        with tenant_context(self.a):
            lot=self.entry(2,30)
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin,self.part.pk,'ENTRADA',1,'Inválida',destino_id=self.depot.pk,lote_id=lot.pk)
            self.invariant()
        self.assertEqual(self.client.get(reverse('operacao:stock_lots'),{'peca':'invalido'}).status_code,404)

    def test_grafico_realizado_sem_duplicar_pagamento_e_legado(self):
        from .executive import charts
        with tenant_context(self.a):
            entry=g.Lancamento.objects.create(tipo='RECEBER',descricao='Parcial',valor=100,vencimento=self.today,criado_por=self.admin)
            services.pagar(self.admin,entry.pk,40,self.today)
            gs.write(g.Lancamento(tipo='RECEBER',descricao='Histórico',valor=20,vencimento=self.today,status='LIQUIDADO',data_liquidacao=self.today,criado_por=self.admin))
            chart=charts(self.today,self.today,'7')
            self.assertEqual(chart[0]['entrada'],60)
            self.assertEqual(chart[0]['saida'],0)
        response=self.client.get(reverse('core:painel'),{'periodo':'HOJE','grafico':'7'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['financial_cards'][2]['value'],60)

    def test_dashboard_periodo_personalizado_e_isolamento_financeiro(self):
        with tenant_context(self.b):
            g.Lancamento.objects.create(tipo='RECEBER',descricao='Receita da B',valor=999,vencimento=self.today,criado_por=self.admin)
            m.ContaBancaria.objects.create(nome='Banco privado B',saldo_inicial=1000)
        response=self.client.get(reverse('core:painel'),{'periodo':'PERSONALIZADO','inicio':self.today,'fim':self.today,'grafico':'3M'})
        self.assertEqual(response.context['period_start'],self.today)
        self.assertEqual(response.context['financial_cards'][0]['value'],0)
        self.assertEqual(response.context['bank_total'],0)
        self.assertNotContains(response,'Banco privado B')

    def test_menu_de_gestao_agrupado_e_operacional_preservado(self):
        response=self.client.get(reverse('core:painel'))
        self.assertContains(response,'vx-nav-group')
        self.assertContains(response,'Recolher menu')
        self.client.force_login(self.users['TECNICO'])
        response=self.client.get(reverse('core:painel'))
        self.assertNotContains(response,'vx-nav-group')
        self.assertContains(response,'Agenda')

    def test_relatorio_item_nao_selecionado_com_sugestao_zero_nao_bloqueia_compra(self):
        with tenant_context(self.a):
            other=g.Peca.objects.create(sku='ZERO-IDEAL',descricao='Produto sem ideal')
            report=stock.generate_report(self.admin)
            selected=report.itens.get(peca=self.part)
            zero=report.itens.get(peca=other)
        data={'deposito':self.depot.pk,'vencimento':self.today,'request_id':uuid.uuid4(),f'selecionar_{selected.pk}':'on',f'quantidade_{selected.pk}':10,f'quantidade_{zero.pk}':0}
        self.assertEqual(self.client.post(reverse('operacao:stock_report',args=[report.pk]),data).status_code,302)
        data[f'quantidade_{selected.pk}']=0
        data['request_id']=uuid.uuid4()
        self.assertEqual(self.client.post(reverse('operacao:stock_report',args=[report.pk]),data).status_code,400)
