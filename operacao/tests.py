import uuid
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError, PermissionDenied
from django.urls import reverse
from django.utils import timezone
from gestao.tests import Dados
from gestao import models as g, services as gs
from platform_core.context import tenant_context
from . import models as m, services as s, forms

class OperacaoTests(Dados, TestCase):
    def setUp(self):
        self.prepare_data()
        self.today = timezone.localdate()

    def purchase(self):
        depot = m.Deposito.objects.create(nome='Recebimento')
        supplier = g.Fornecedor.objects.create(nome='Fornecedor local')
        purchase = m.Compra.objects.create(deposito=depot, fornecedor=supplier, necessidade='Reposição', vencimento=self.today, criado_por=self.admin)
        m.ItemCompra.objects.create(compra=purchase, peca=self.da['part'], quantidade=5, custo_unitario=10)
        return purchase

    def test_compra_recebe_uma_vez_estoque_e_conta(self):
        with tenant_context(self.a):
            p = self.purchase()
            for action in ['aprovar', 'pedir', 'receber', 'receber']:
                s.compra_acao(self.admin, p.pk, action)
            p.refresh_from_db()
            self.da['part'].refresh_from_db()
            self.assertEqual(p.status, 'RECEBIDA')
            self.assertEqual(p.conta.valor, 50)
            self.assertEqual(p.conta.tipo, 'PAGAR')
            self.assertEqual(self.da['part'].quantidade_atual, 5)
            self.assertEqual(g.Movimentacao.objects.count(), 1)
            self.assertEqual(m.SaldoDeposito.objects.get(deposito=p.deposito, peca=self.da['part']).quantidade, 5)

    def test_compra_recebimento_sem_pedido_e_item_editado_negados(self):
        with tenant_context(self.a):
            p = self.purchase()
            with self.assertRaises(ValidationError):
                s.compra_acao(self.admin, p.pk, 'receber')
            s.compra_acao(self.admin, p.pk, 'aprovar')
            item = p.itens.first()
            item.quantidade = 8
            item.compra.refresh_from_db()
            with self.assertRaises(ValidationError):
                item.save()

    def test_venda_baixa_mesmo_estoque_e_gera_recebivel_uma_vez(self):
        with tenant_context(self.a):
            p = self.purchase()
            for action in ['aprovar', 'pedir', 'receber']:
                s.compra_acao(self.admin, p.pk, action)
            sale = m.Venda.objects.create(cliente=self.da['customer'], deposito=p.deposito, vencimento=self.today, criado_por=self.admin)
            m.ItemVenda.objects.create(venda=sale, peca=self.da['part'], quantidade=2, valor_unitario=20, custo_unitario=10)
            s.venda_confirmar(self.admin, sale.pk)
            s.venda_confirmar(self.admin, sale.pk)
            sale.refresh_from_db()
            self.assertEqual(sale.conta.valor, 40)
            self.da['part'].refresh_from_db()
            self.assertEqual(self.da['part'].quantidade_atual, 3)
            self.assertEqual(g.Lancamento.objects.count(), 2)

    def test_venda_sem_saldo_rollback_integral(self):
        with tenant_context(self.a):
            depot = m.Deposito.objects.create(nome='Loja')
            sale = m.Venda.objects.create(cliente=self.da['customer'], deposito=depot, vencimento=self.today, criado_por=self.admin)
            m.ItemVenda.objects.create(venda=sale, peca=self.da['part'], quantidade=1, valor_unitario=20)
            with self.assertRaises(ValidationError):
                s.venda_confirmar(self.admin, sale.pk)
            sale.refresh_from_db()
            self.assertEqual(sale.status, 'RASCUNHO')
            self.assertFalse(g.Lancamento.objects.exists())
            self.assertFalse(g.Movimentacao.objects.exists())

    def test_transferencia_preserva_total_e_proibe_negativo_deposito(self):
        with tenant_context(self.a):
            part = self.da['part']
            gs.movimentar(self.admin, part.pk, 'ENTRADA', 10)
            principal = m.Deposito.objects.get(nome='Principal')
            secondary = m.Deposito.objects.create(nome='Veículo')
            gs.movimentar(self.admin, part.pk, 'TRANSFER', 3, origem_id=principal.pk, destino_id=secondary.pk)
            part.refresh_from_db()
            self.assertEqual(part.quantidade_atual, 10)
            self.assertEqual(m.SaldoDeposito.objects.get(deposito=secondary, peca=part).quantidade, 3)
            with self.assertRaises(ValidationError):
                gs.movimentar(self.admin, part.pk, 'SAIDA', 4, origem_id=secondary.pk)
            self.assertEqual(g.Movimentacao.objects.count(), 2)

    def test_pagamentos_parciais_saldo_caixa_e_idempotencia(self):
        with tenant_context(self.a):
            account = m.ContaBancaria.objects.create(nome='Caixa')
            entry = self.entry()
            token = uuid.uuid4()
            s.pagar(self.admin, entry.pk, 10, self.today, account_id=account.pk, request_id=token)
            s.pagar(self.admin, entry.pk, 10, self.today, account_id=account.pk, request_id=token)
            entry.refresh_from_db()
            self.assertEqual(entry.saldo, 20)
            self.assertEqual(entry.status, 'PENDENTE')
            self.assertEqual(account.saldo, 10)
            with self.assertRaises(ValidationError):
                s.pagar(self.admin, entry.pk, 21, self.today)
            s.pagar(self.admin, entry.pk, 20, self.today, account_id=account.pk)
            entry.refresh_from_db()
            self.assertEqual(entry.status, 'LIQUIDADO')
            self.assertEqual(entry.saldo, 0)
            self.assertEqual(account.saldo, 30)
            self.assertEqual(m.Pagamento.objects.count(), 2)

    def test_banco_transferencia_atomica_e_conciliacao(self):
        with tenant_context(self.a):
            a = m.ContaBancaria.objects.create(nome='Banco A', saldo_inicial=50)
            b = m.ContaBancaria.objects.create(nome='Banco B')
            ref = uuid.uuid4()
            s.transferir_banco(self.admin, a.pk, b.pk, 20, self.today, ref)
            s.transferir_banco(self.admin, a.pk, b.pk, 20, self.today, ref)
            self.assertEqual((a.saldo, b.saldo), (30, 20))
            row = m.ExtratoBancario.objects.create(conta=a, identificador='EXT-1', data=self.today, valor=-20, descricao='Transferência')
            s.conciliar(self.admin, row.pk, a.movimentos.first().pk)
            row.refresh_from_db()
            self.assertTrue(row.movimento_id)
            with self.assertRaises(ValidationError):
                s.transferir_banco(self.admin, a.pk, b.pk, 31, self.today, uuid.uuid4())
            self.assertEqual((a.saldo, b.saldo), (30, 20))

    def test_parcelamento_valores_exatos_sem_receita_duplicada(self):
        with tenant_context(self.a):
            entry = self.entry(valor=100)
            parts = s.parcelar(self.admin, entry.pk, 3, self.today)
            self.assertEqual(sum(row.lancamento.valor for row in parts), 100)
            entry.refresh_from_db()
            self.assertEqual(entry.status, 'CANCELADO')
            self.assertEqual(len(s.parcelar(self.admin, entry.pk, 3, self.today)), 3)

    def test_checklist_preventiva_gerada_e_execucao(self):
        with tenant_context(self.a):
            checklist = m.ModeloChecklist.objects.create(nome='Segurança', itens=[{'item': 'Inspeção', 'obrigatorio': True}])
            plan = m.PlanoPreventivo.objects.create(nome='Mensal', cliente=self.da['customer'], tecnico=self.da['tech'], checklist=checklist, inicio=self.today, fim=self.today + timezone.timedelta(days=70))
            m.PlanoEquipamento.objects.create(plano=plan, equipamento=self.da['equipment'])
            s.gerar_plano(self.admin, plan.pk)
            s.gerar_plano(self.admin, plan.pk)
            self.assertEqual(plan.ocorrencias.count(), 3)
            occurrence = plan.ocorrencias.first()
            order = s.preventiva_os(self.admin, occurrence.pk, self.da['tech'].pk)
            self.assertEqual(plan.proxima_execucao,self.today)
            self.assertEqual(s.preventiva_os(self.admin, occurrence.pk, self.da['tech'].pk).pk, order.pk)
            from ordens import services as os
            os.iniciar(self.admin, order.pk, {'resultado': 'NEGADA'})
            order.refresh_from_db()
            order.diagnostico, order.servico_executado = 'Teste', 'Inspeção'
            order.save()
            with self.assertRaises(ValidationError):
                os.preparar(self.admin, order.pk, {'resultado': 'NEGADA'})
            s.checklist_salvar(self.admin, order.pk, ['0'], {})
            self.assertTrue(os.preparar(self.admin, order.pk, {'resultado': 'NEGADA'}).pk)

    def test_chamado_e_os_mesmo_cliente_sem_duplicar(self):
        with tenant_context(self.a):
            call = m.Chamado.objects.create(cliente=self.da['customer'], unidade=self.da['unit'], equipamento=self.da['equipment'], titulo='Falha', descricao='Falha na fonte', criado_por=self.admin)
            order = s.chamado_os(self.admin, call.pk, self.da['tech'].pk)
            self.assertEqual(s.chamado_os(self.admin, call.pk, self.da['tech'].pk).pk, order.pk)
            self.assertEqual(order.cliente_id, call.cliente_id)

    def test_permissoes_servicos(self):
        with tenant_context(self.a):
            p = self.purchase()
            with self.assertRaises(PermissionDenied):
                s.compra_acao(self.users['TECNICO'], p.pk, 'aprovar')
            with self.assertRaises(PermissionDenied):
                s.pagar(self.users['ESTOQUE'], self.entry().pk, 1, self.today)
            with self.assertRaises(PermissionDenied):
                s.pagar(self.users['CONTABILIDADE'], self.entry().pk, 1, self.today)

    def test_telas_novas_e_forms(self):
        from .views import RESOURCES
        for resource in RESOURCES:
            self.assertEqual(self.client.get(reverse('operacao:' + resource + '_lista')).status_code, 200, resource)
            self.assertEqual(self.client.get(reverse('operacao:' + resource + '_novo')).status_code, 200, resource)
        with tenant_context(self.a):
            obj = self.purchase()
        self.assertEqual(self.client.get(reverse('operacao:compra_detalhe', args=[obj.pk])).status_code, 200)

    def test_isolamento_novos_registros_e_campos_relacionados(self):
        with tenant_context(self.b):
            depot = m.Deposito.objects.create(nome='Externo')
        with tenant_context(self.a):
            form = forms.CompraForm({'deposito': depot.pk, 'necessidade': 'Teste', 'vencimento': self.today})
            self.assertFalse(form.is_valid())
            self.assertNotIn(depot, form.fields['deposito'].queryset)
        self.assertEqual(self.client.get(reverse('operacao:deposito_detalhe', args=[depot.pk])).status_code, 404)

    def test_calendario_visoes_filtros_e_mobile(self):
        response=self.client.get(reverse('operacao:calendario'))
        self.assertEqual(response.context['form']['visao'].value(),'SEMANA')
        self.assertEqual(response.context['form']['data'].value(),timezone.localdate().isoformat())
        self.assertEqual(len(response.context['days']),7)
        for view in ['DIA','SEMANA','MES']:
            response=self.client.get(reverse('operacao:calendario'),{'visao':view})
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'Planejamento')
        self.assertEqual(self.client.get(reverse('operacao:calendario'),{'cliente':self.db['customer'].pk}).status_code,400)
        # The shared PWA now routes ADMIN to the complete ERP.
        self.assertRedirects(self.client.get(reverse('operacao:tecnico')),reverse('core:painel'))
        self.client.force_login(self.users['ESTOQUE'])
        self.assertEqual(self.client.get(reverse('operacao:calendario')).status_code,403)

    def test_portal_isola_clientes_mesma_empresa_e_outra_empresa(self):
        with tenant_context(self.a):
            user=self.user('cliente-portal',self.a,'CLIENTE')
            m.PortalCliente.objects.create(usuario=user,cliente=self.da['customer'])
            from clientes.models import Cliente
            other=Cliente.objects.create(nome_razao_social='CLIENTE SIGILOSO',cpf_cnpj='outro')
            self.entry(cliente=other,descricao='RECEITA SIGILOSA')
            self.entry(cliente=self.da['customer'],descricao='RECEITA PERMITIDA')
        self.client.force_login(user)
        response=self.client.get(reverse('operacao:portal'))
        self.assertContains(response,'RECEITA PERMITIDA')
        self.assertNotContains(response,'RECEITA SIGILOSA')
        self.assertNotContains(response,'CLIENTE SIGILOSO')
        self.assertEqual(self.client.get(reverse('operacao:portal_os',args=[self.db['order'].pk])).status_code,404)
        for path in ['/financeiro/','/ordens/','/clientes/','/documentos/','/configuracoes/']:
            self.assertEqual(self.client.get(path).status_code,403,path)
        self.assertEqual(self.client.get(reverse('operacao:portal_os',args=[self.da['order'].pk])).status_code,200)
        for fmt in ['csv','xlsx','pdf']:
            response=self.client.get(reverse('operacao:portal_relatorio'),{'formato':fmt})
            self.assertEqual(response.status_code,200,fmt)
            self.assertNotIn(b'RECEITA SIGILOSA',response.content)

    def test_portal_chamado_e_aprovacao_com_auditoria(self):
        with tenant_context(self.a):
            user=self.user('portal-decisao',self.a,'CLIENTE')
            m.PortalCliente.objects.create(usuario=user,cliente=self.da['customer'])
            quote=self.quote(gerar_recebivel=True)
            gs.status_orcamento(self.admin,quote.pk,'enviar')
        self.client.force_login(user)
        response=self.client.post(reverse('operacao:portal_chamado'),{'cliente':self.da['customer'].pk,'unidade':self.da['unit'].pk,'equipamento':self.da['equipment'].pk,'titulo':'Chamado via portal','descricao':'Defeito','prioridade':'ALTA'})
        self.assertEqual(response.status_code,302)
        response=self.client.post(reverse('operacao:portal_aprovar',args=[quote.pk,'aprovar']))
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):
            quote.refresh_from_db()
            self.assertEqual(quote.status,'APROVADO')
            self.assertEqual(quote.lancamentos.count(),1)
        self.assertEqual(self.client.post(reverse('operacao:portal_aprovar',args=[quote.pk,'aprovar'])).status_code,400)
        self.assertEqual(self.client.get(reverse('operacao:portal_orcamento_pdf',args=[quote.pk])).status_code,200)

    def test_documento_upload_download_e_idor(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import tempfile
        with tempfile.TemporaryDirectory() as directory, self.settings(PRIVATE_MEDIA_ROOT=directory):
            response=self.client.post(reverse('operacao:documento_novo'),{'titulo':'Manual protegido','tipo':'PDF','cliente':self.da['customer'].pk,'arquivo':SimpleUploadedFile('manual.pdf',b'%PDF-1.4\n%%EOF'),'disponivel_portal':'on'})
            self.assertEqual(response.status_code,302)
            with tenant_context(self.a):
                doc=m.Documento.objects.get()
                user=self.user('portal-documento',self.a,'CLIENTE')
                m.PortalCliente.objects.create(usuario=user,cliente=self.da['customer'])
            response=self.client.get(reverse('operacao:documento_arquivo',args=[doc.pk]))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Cache-Control'],'private, no-store')
            self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
            self.client.force_login(self.admin_b)
            self.assertEqual(self.client.get(reverse('operacao:documento_arquivo',args=[doc.pk])).status_code,404)
            self.client.force_login(user)
            response=self.client.get(reverse('operacao:portal_documento',args=[doc.pk]))
            self.assertEqual(response.status_code,200)
            self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))

    def test_upload_rejeita_arquivo_falso_e_xml_entidades(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        for name,content in [('falso.pdf',b'<script>alert(1)</script>'),('teste.xml',b'<!DOCTYPE doc [<!ENTITY x SYSTEM "file:///etc/passwd">]><doc>&x;</doc>'),('falso.mp4',b'NAO E VIDEO')]:
            response=self.client.post(reverse('operacao:documento_novo'),{'titulo':'Inválido','tipo':'PDF','arquivo':SimpleUploadedFile(name,content)})
            self.assertEqual(response.status_code,400,name)

    def test_fiscal_sem_provedor_nao_emite_nem_altera_estado(self):
        from fiscal.services import executar, payload
        with tenant_context(self.a):
            m.Configuracao.objects.create()
            depot=m.Deposito.objects.create(nome='Fiscal de teste')
            sale=m.Venda.objects.create(cliente=self.da['customer'],deposito=depot,vencimento=self.today,criado_por=self.admin)
            part=self.da['part']
            part.cst_csosn='102'
            part.save()
            m.ItemVenda.objects.create(venda=sale,peca=part,quantidade=2,valor_unitario=20)
            product_doc=m.DocumentoFiscal.objects.create(tipo='NFE',cliente=self.da['customer'],venda=sale,descricao='Produtos de teste',valor=40,criado_por=self.admin)
            products=payload(product_doc)['produtos']
            self.assertEqual(products[0]['sku'],part.sku)
            self.assertEqual(products[0]['cst_csosn'],'102')
            self.assertEqual(Decimal(products[0]['quantidade'])*Decimal(products[0]['valor_unitario']),40)
            with self.assertRaisesMessage(ValidationError,'Integração fiscal não configurada'):
                executar(self.admin,product_doc.pk,'emitir')
            product_doc.refresh_from_db()
            self.assertEqual(product_doc.status,'RASCUNHO')
            doc=m.DocumentoFiscal.objects.create(tipo='NFSE',cliente=self.da['customer'],descricao='Serviço',valor=10,criado_por=self.admin)
            with self.assertRaisesMessage(ValidationError,'Integração fiscal não configurada'):
                executar(self.admin,doc.pk,'emitir')
            doc.refresh_from_db()
            self.assertEqual(doc.status,'RASCUNHO')
            self.assertFalse(doc.numero)
            self.assertFalse(m.Documento.objects.exists())
        response=self.client.post(reverse('operacao:fiscal_acao',args=[doc.pk,'emitir']))
        self.assertEqual(response.status_code,400)

    def test_configuracoes_admin_preservam_segredos_e_usuario_financeiro_negado(self):
        self.assertEqual(self.client.get(reverse('operacao:configuracao')).status_code,200)
        self.client.force_login(self.users['FINANCEIRO'])
        self.assertEqual(self.client.get(reverse('operacao:configuracao')).status_code,403)
        with tenant_context(self.a):
            form=forms.ConfiguracaoForm()
            for secret in ['SECRET_KEY','DATABASE_URL','token','senha','certificado']:
                self.assertNotIn(secret,form.fields)

    def test_notificacoes_isoladas_por_usuario_e_empresa(self):
        with tenant_context(self.a):
            row=m.Notificacao.objects.create(usuario=self.users['TECNICO'],titulo='Privada',mensagem='Teste',chave='privada')
        self.assertNotContains(self.client.get(reverse('operacao:notificacoes')),'Privada')
        self.assertEqual(self.client.post(reverse('operacao:notificacao_lida',args=[row.pk])).status_code,404)
        self.client.force_login(self.users['TECNICO'])
        self.assertContains(self.client.get(reverse('operacao:notificacoes')),'Privada')
        self.assertEqual(self.client.post(reverse('operacao:notificacao_lida',args=[row.pk])).status_code,302)

    def test_pwa_publica_nao_cacheia_documentos_ou_sessao(self):
        self.client.logout()
        self.assertEqual(self.client.get('/manifest.webmanifest').status_code,200)
        response=self.client.get('/sw.js')
        self.assertEqual(response.status_code,200)
        self.assertIn(b"if(event.request.method!=='GET'",response.content)
        self.assertIn(b"ASSETS.includes(url.pathname)",response.content)
        self.assertNotIn(b"'/ordens/'",response.content)

    def test_relatorios_adicionais_e_excel_sem_formulas(self):
        from gestao.reporting import REPORTS, xlsx_bytes
        from openpyxl import load_workbook
        import io
        for key in REPORTS:
            for export in ['csv','pdf','xlsx']:
                response=self.client.get(reverse('gestao:relatorio',args=[key]),{'export':export})
                self.assertEqual(response.status_code,200,f'{key}/{export}')
        workbook=load_workbook(io.BytesIO(xlsx_bytes(['Nome'],[['=HYPERLINK("http://invalid")']])))
        self.assertEqual(workbook.active['A2'].data_type,'s')

    def test_dashboard_pagamento_parcial_nao_duplica_quitacao(self):
        from gestao.reporting import financial_dashboard
        with tenant_context(self.a):
            entry=self.entry()
            s.pagar(self.admin,entry.pk,10,self.today)
            result=financial_dashboard(self.today,self.today)
            self.assertEqual((result['recebido'],result['a_receber']),(10,20))
            s.pagar(self.admin,entry.pk,20,self.today)
            result=financial_dashboard(self.today,self.today)
            self.assertEqual((result['recebido'],result['a_receber']),(30,0))

    def test_historicos_integrados(self):
        self.assertContains(self.client.get(reverse('clientes:cliente_detail',args=[self.da['customer'].pk])),'Histórico integrado')
        self.assertContains(self.client.get(reverse('equipamentos:equipamento_detail',args=[self.da['equipment'].pk])),'Histórico integrado')

    def test_estados_assinados_aprovacao_faturamento_e_reabertura(self):
        from ordens import services as os
        from ordens.models import OrdemServico
        with tenant_context(self.a):
            order=self.da['order']
            order.valor_cobranca=30
            order.save()
            signature=self.finalize(order)
            digest=signature.conferencia.digest
            s.transicao_os(self.admin,order.pk,'aprovar')
            s.transicao_os(self.admin,order.pk,'faturar')
            order.refresh_from_db()
            self.assertEqual(order.status,'FATURADA')
            order.diagnostico='Alteração indevida'
            with self.assertRaises(ValidationError):
                order.save()
            os.reabrir(self.admin,order.pk,'Retorno para conferência')
            order.refresh_from_db()
            self.assertEqual((order.status,order.ciclo),('ABERTA',2))
            signature.conferencia.refresh_from_db()
            self.assertEqual(signature.conferencia.digest,digest)
            self.assertEqual(order.lancamentos.count(),1)

    def test_provedor_fiscal_resposta_invalida_nao_autoriza(self):
        from fiscal.services import executar
        from fiscal.providers.base import FiscalResult
        from unittest.mock import patch, Mock
        with tenant_context(self.a):
            m.Configuracao.objects.create(provedor_fiscal='ADAPTADOR_DE_TESTE')
            doc=gs.write(m.DocumentoFiscal(tipo='NFSE',cliente=self.da['customer'],descricao='Ensaio',valor=10,criado_por=self.admin,status='ENVIADA',protocolo='PROTOCOLO-DE-TESTE'))
            provider=Mock()
            provider.consultar.return_value=FiscalResult(status='AUTORIZADA')
            with patch('fiscal.services.resolve',return_value=provider):
                with self.assertRaisesMessage(ValidationError,'Resposta fiscal inválida'):
                    executar(self.admin,doc.pk,'consultar')
            doc.refresh_from_db()
            self.assertEqual(doc.status,'ENVIADA')
            self.assertFalse(doc.numero)

from django.test import TransactionTestCase
from django.db import connection, connections
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

@skipUnless(connection.vendor == 'postgresql', 'Exige bloqueios reais do PostgreSQL')
class OperacaoPostgreSQLTests(Dados, TransactionTestCase):
    def setUp(self):
        self.prepare_data()

    def race(self, operation):
        barrier=Barrier(2)
        def worker(index):
            connections.close_all()
            try:
                with tenant_context(self.a):
                    barrier.wait(timeout=15)
                    try:
                        operation(index)
                        return 'OK'
                    except ValidationError:
                        return 'BLOQUEADO'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(worker,[0,1]))

    def test_duas_vendas_disputam_ultimo_item_sem_negativo(self):
        with tenant_context(self.a):
            gs.movimentar(self.admin,self.da['part'].pk,'ENTRADA',1)
            depot=m.Deposito.objects.get(nome='Principal')
            sales=[]
            for _ in range(2):
                sale=m.Venda.objects.create(cliente=self.da['customer'],deposito=depot,vencimento=timezone.localdate(),criado_por=self.admin)
                m.ItemVenda.objects.create(venda=sale,peca=self.da['part'],quantidade=1,valor_unitario=20)
                sales.append(sale.pk)
        result=self.race(lambda index:s.venda_confirmar(self.admin,sales[index]))
        self.assertCountEqual(result,['OK','BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(g.Peca.objects.get(pk=self.da['part'].pk).quantidade_atual,0)
            self.assertEqual(m.SaldoDeposito.objects.get(peca=self.da['part']).quantidade,0)
            self.assertEqual(g.Lancamento.objects.count(),1)

    def test_pagamentos_concorrentes_nao_excedem_saldo(self):
        with tenant_context(self.a):
            entry=self.entry(valor=30)
            account=m.ContaBancaria.objects.create(nome='Banco')
        result=self.race(lambda index:s.pagar(self.admin,entry.pk,20,timezone.localdate(),account_id=account.pk))
        self.assertCountEqual(result,['OK','BLOQUEADO'])
        with tenant_context(self.a):
            self.assertEqual(g.Lancamento.objects.get(pk=entry.pk).saldo,10)
            self.assertEqual(account.saldo,20)
            self.assertEqual(m.Pagamento.objects.count(),1)
