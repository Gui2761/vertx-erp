"""Seller journeys run against official sales/stock/finance and synthetic tenants."""
import re
import uuid
from decimal import Decimal
from datetime import datetime, date
from unittest.mock import patch
from django.test import TestCase, TransactionTestCase
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.urls import reverse
from django.db import connection
from unittest import skipUnless
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership, MembershipERP, PermissaoMembership, ModuloOrganizacao
from clientes.models import Cliente
from gestao import models as g
from . import models as m, commerce as c, seller_services as s, workforce as w, overtime as o
from .test_block3_commerce import CommerceData
from . import tests as previous_tests

class SellerData(CommerceData):
    def setup_seller(self):
        self.setup_commerce()
        self.seller=self.operator
        membership=OrganizationMembership.objects.get(organization=self.a,user=self.seller)
        membership.role='VENDEDOR';membership.save()
        self.seller.set_password('synthetic-seller-test-only');self.seller.save()
        self.other=self.user('other-seller',self.a,'VENDEDOR')
        with tenant_context(self.a):
            self.other_cash=m.ContaBancaria.objects.create(nome='Outro caixa',tipo='CAIXA')
            self.other_session=c.open_cash(self.other,self.other_cash.pk,0,uuid.uuid4())
            self.other_sale=c.new_sale(self.other,self.other_session.public_id,self.depot.pk)
            self.schedule=m.JornadaTrabalho.objects.create(nome='Abertura 5x2',semana={str(i):{'entrada':'08:00','saida':'17:00','inicio_intervalo':'12:00','fim_intervalo':'13:00'} for i in range(5)})
            self.employee=m.Funcionario.objects.create(usuario=self.seller,matricula='SELLER-1',nome='Vendedor sintético',jornada=self.schedule)
            self.part.referencia='REF-VENDAS';self.part.codigo_barras='BAR-SYNTHETIC';self.part.save()
        self.client.force_login(self.seller)

class SellerPWATests(SellerData,TestCase):
    def setUp(self): self.setup_seller()

    def test_login_unique_uses_membership_not_global_admin_or_next(self):
        self.client.logout()
        response=self.client.post('/login/?next=/financeiro/',{'username':self.seller.username,'password':'synthetic-seller-test-only'})
        self.assertRedirects(response,'/vendedor/')

    def test_pdv_role_login_also_uses_seller_home(self):
        row=OrganizationMembership.objects.get(user=self.seller,organization=self.a);row.role='PDV';row.save()
        self.client.logout()
        self.assertRedirects(self.client.post('/contas/login/',{'username':self.seller.username,'password':'synthetic-seller-test-only'}),'/vendedor/')

    def test_platform_home_and_selection_land_in_sales(self):
        self.assertRedirects(self.client.get('/vertyx/'),'/vendedor/')
        self.assertRedirects(self.client.post(reverse('platform_core:select_organization'),{'organization':self.a.public_id}),'/vendedor/')

    def test_menu_server_html_contains_only_sales_and_self_service(self):
        response=self.client.get('/vendedor/');self.assertEqual(response.status_code,200)
        html=response.content.decode();menu=html.split('id="menuPrincipal">')[1].split('</div>')[0]
        for label in ['Central de Vendas','Abrir PDV','Minhas vendas','Minha meta','Minha comissão','Meu ponto','Hora extra','Alertas','Sair']:
            self.assertIn(label,menu)
        for text in ['Financeiro','Estoque','Compras','Contratos','Usuários','Configurações','RH','Voltar para VERTYX','disabled','display:none']:
            self.assertNotIn(text,menu)
        self.assertIn('href="/vendedor/"',html)
        self.assertNotIn('href="/assistencia/"',html)

    def test_all_admin_urls_denied_even_with_capability_override(self):
        membership=OrganizationMembership.objects.get(user=self.seller,organization=self.a)
        with tenant_context(self.a):
            for cap in ['financeiro','financeiro_escrever','compras','estoque','rh','desconto_supervisor','caixa_supervisor']:
                PermissaoMembership.objects.create(membership=membership,capacidade=cap,permitido=True)
        for url in ['/financeiro/','/compras/','/estoque/','/depositos/','/contas/usuarios/','/configuracoes/','/rh/funcionarios/','/bancos/','/contratos/','/relatorios/','/assistencia/','/vertyx/empresa/','/pdv/configuracao/','/vendedor/gestao/']:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code,403)

    def test_pdv_home_uses_professional_terminal(self):
        response=self.client.get('/pdv/');self.assertTemplateUsed(response,'operacao/seller_terminal.html')
        self.assertContains(response,'Iniciar venda rápida')
        self.assertNotContains(response,'Banco PIX')

    def test_new_sale_cannot_impersonate_other_seller(self):
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied): c.new_sale(self.seller,self.session.public_id,self.depot.pk,seller_id=self.other.pk)
        self.assertEqual(self.client.post(reverse('operacao:pdv_cash',args=[self.session.public_id]),{'action':'venda','deposito':self.depot.pk,'vendedor':self.other.pk}).status_code,403)

    def test_other_seller_sale_direct_get_post_receipt_and_search_denied(self):
        for suffix in ['','produtos/','comprovante/']:
            url=f'/pdv/vendas/{self.other_sale.public_id}/'+suffix
            self.assertEqual(self.client.get(url).status_code,403)
            self.assertEqual(self.client.post(url,{'action':'observacao','observacoes':'Attack'}).status_code,403)

    def test_same_cash_sale_assigned_to_other_is_denied(self):
        with tenant_context(self.a):
            sale=c.new_sale(self.admin,self.session.public_id,self.depot.pk,seller_id=self.other.pk)
            with self.assertRaises(PermissionDenied): c.add_item(self.seller,sale.public_id,self.part.sku,1)

    def test_foreign_organization_sale_and_customer_injection_denied(self):
        with tenant_context(self.a): sale,item=self.sale()
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(f'/pdv/vendas/{sale.public_id}/').status_code,404)
        self.client.force_login(self.seller)
        response=self.client.post(f'/pdv/vendas/{sale.public_id}/',{'action':'cliente','cliente':self.db['customer'].pk})
        self.assertContains(response,'Revise os dados da operação.')
        with tenant_context(self.a): sale.refresh_from_db();self.assertIsNone(sale.cliente_id)

    def test_product_search_by_name_sku_barcode_and_reference(self):
        with tenant_context(self.a): self.incoming(4);sale,item=self.sale()
        for query in [self.part.descricao,self.part.sku,self.part.codigo_barras,self.part.referencia]:
            response=self.client.get(f'/pdv/vendas/{sale.public_id}/',{'q':query})
            self.assertContains(response,self.part.descricao)
            self.assertEqual(response.context['products'][0]['available'],4)
            self.assertNotContains(response,'custo_unitario')

    def test_product_search_never_includes_foreign_tenant(self):
        with tenant_context(self.a): sale,item=self.sale()
        response=self.client.get(f'/pdv/vendas/{sale.public_id}/',{'q':'Peça'})
        self.assertNotContains(response,self.db['part'].descricao)

    def test_add_edit_plus_minus_remove_use_existing_items(self):
        with tenant_context(self.a):
            sale,item=self.sale()
            url=f'/pdv/vendas/{sale.public_id}/'
        for quantity in ['2.000','1.000']:
            self.assertEqual(self.client.post(url,{'action':'editar','item':item.pk,'quantidade':quantity,'desconto':'0'}).status_code,302)
        with tenant_context(self.a): item.refresh_from_db();self.assertEqual(item.quantidade,1)
        self.assertEqual(self.client.post(url,{'action':'remover','item':item.pk}).status_code,302)
        with tenant_context(self.a): self.assertFalse(sale.itens.exists())

    def test_subtotal_and_discount_decimal_cent_accuracy(self):
        with tenant_context(self.a):
            self.part.preco_venda=Decimal('10.01');self.part.save();m.ConfiguracaoPDV.objects.create(limite_desconto_percentual=10)
            sale,item=self.sale(3);c.pricing(self.seller,sale.public_id,'1.01',0,'Promoção');sale.refresh_from_db()
            self.assertEqual(sale.total,Decimal('29.02'))

    def test_combined_item_global_discount_cannot_bypass_limit(self):
        with tenant_context(self.a):
            m.ConfiguracaoPDV.objects.create(limite_desconto_percentual=5)
            sale,item=self.sale();c.edit_item(self.seller,sale.public_id,item.pk,1,'.50','Promoção')
            with self.assertRaises(PermissionDenied): c.pricing(self.seller,sale.public_id,'.47',0,'Segundo desconto')
            sale.refresh_from_db();self.assertEqual(sale.desconto_global,0)

    def test_unauthorized_discount_post_is_rejected_and_atomic(self):
        with tenant_context(self.a): sale,item=self.sale()
        response=self.client.post(f'/pdv/vendas/{sale.public_id}/',{'action':'preco','desconto':'9.00','motivo':'forçado'})
        self.assertEqual(response.status_code,403)
        with tenant_context(self.a): sale.refresh_from_db();self.assertEqual(sale.desconto_global,0)

    def test_discount_request_deduplicates_and_does_not_apply_before_approval(self):
        with tenant_context(self.a):
            sale,item=self.sale();first=s.request_discount(self.seller,sale.public_id,1,'Condição especial')
            self.assertEqual(first.pk,s.request_discount(self.seller,sale.public_id,1,'Condição especial').pk)
            sale.refresh_from_db();self.assertEqual(sale.desconto_global,0)
            self.assertEqual(m.SolicitacaoDescontoPDV.objects.count(),1)

    def test_supervisor_approval_applies_and_records_actor(self):
        with tenant_context(self.a):
            self.incoming(3);sale,item=self.sale();req=s.request_discount(self.seller,sale.public_id,1,'Cliente')
            s.decide_discount(self.admin,req.pk,True,'Condição aprovada')
            req.refresh_from_db();sale.refresh_from_db();self.assertEqual((req.status,req.decidido_por_id,sale.total),('APROVADO',self.admin.pk,9))
            self.paid(sale,'9.00');self.assertEqual(m.Notificacao.objects.filter(usuario=self.seller,chave=f'pdv-desconto-decisao:{req.pk}').count(),1)

    def test_seller_cannot_self_authorize(self):
        with tenant_context(self.a):
            sale,item=self.sale();req=s.request_discount(self.seller,sale.public_id,1,'Desconto')
            with self.assertRaises(PermissionDenied): s.decide_discount(self.seller,req.pk,True,'Eu aprovo')

    def test_approval_stale_cart_is_rejected(self):
        with tenant_context(self.a):
            sale,item=self.sale();req=s.request_discount(self.seller,sale.public_id,1,'Desconto')
            c.edit_item(self.seller,sale.public_id,item.pk,2)
            with self.assertRaises(ValidationError): s.decide_discount(self.admin,req.pk,True,'Aprovar')
            req.refresh_from_db();self.assertEqual(req.status,'PENDENTE')

    def test_approved_discount_cannot_survive_cart_change(self):
        with tenant_context(self.a):
            sale,item=self.sale();req=s.request_discount(self.seller,sale.public_id,1,'Desconto');s.decide_discount(self.admin,req.pk,True,'Aprovado')
            with self.assertRaises(PermissionDenied): c.edit_item(self.seller,sale.public_id,item.pk,2)
            item.refresh_from_db();self.assertEqual(item.quantidade,1)

    def test_customer_selection_and_quick_sale(self):
        with tenant_context(self.a): sale,item=self.sale()
        url=f'/pdv/vendas/{sale.public_id}/'
        self.assertEqual(self.client.post(url,{'action':'cliente','cliente':self.da['customer'].pk}).status_code,302)
        with tenant_context(self.a): sale.refresh_from_db();self.assertEqual(sale.cliente_id,self.da['customer'].pk)
        self.assertEqual(self.client.post(url,{'action':'cliente','cliente':''}).status_code,302)
        with tenant_context(self.a): sale.refresh_from_db();self.assertIsNone(sale.cliente_id)

    def test_simplified_customer_create_cannot_change_credit(self):
        with tenant_context(self.a): sale,item=self.sale()
        response=self.client.post('/vendedor/cliente/',{'venda':sale.public_id,'nome_razao_social':'Consumidor sintético','tipo_pessoa':'PF','cpf_cnpj':'CPF-SYNTHETIC','limite_credito':'999999','ativo':'off'})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):
            customer=Cliente.objects.get(cpf_cnpj='CPF-SYNTHETIC');self.assertIsNone(customer.limite_credito);self.assertTrue(customer.ativo)
            sale.refresh_from_db();self.assertEqual(sale.cliente_id,customer.pk)

    def test_customer_create_permission_revoked(self):
        member=OrganizationMembership.objects.get(user=self.seller,organization=self.a)
        with tenant_context(self.a):
            sale,item=self.sale();PermissaoMembership.objects.create(membership=member,capacidade='pdv_cliente_cadastrar',permitido=False)
        self.assertEqual(self.client.get('/vendedor/cliente/',{'venda':sale.public_id}).status_code,403)
        self.assertEqual(self.client.get(reverse('clientes:cliente_create')).status_code,403)

    def test_mixed_payment_cash_change_stock_and_receipt(self):
        with tenant_context(self.a):
            early=self.incoming(1,7,'2.25');late=self.incoming(1,60,'7.33');sale,item=self.sale(2)
            key=uuid.uuid4();payments=[{'forma':self.cash_method.pk,'valor':'8.00','recebido':'10.00'},{'forma':self.pix.pk,'valor':'12.00'}]
            result=c.finalize(self.seller,sale.public_id,payments,key);item.refresh_from_db()
            self.assertEqual((result.total,result.conta.saldo,item.custo_total),(20,0,Decimal('9.58000')))
            self.assertEqual(result.pagamentos_pdv.get(forma=self.cash_method).troco,2)
            self.assertEqual([l['id'] for l in result.snapshot['itens'][0]['lotes']],[early.pk,late.pk])
        self.assertContains(self.client.get(f'/pdv/vendas/{sale.public_id}/comprovante/'),'Comprovante não fiscal')

    def test_duplicate_finalize_does_not_duplicate_stock_payment(self):
        with tenant_context(self.a):
            self.incoming(1);sale,item=self.sale();key=uuid.uuid4();rows=[{'forma':self.cash_method.pk,'valor':'10'}]
            c.finalize(self.seller,sale.public_id,rows,key);c.finalize(self.seller,sale.public_id,rows,key)
            self.assertEqual(m.PagamentoVenda.objects.count(),1);self.assertEqual(g.Movimentacao.objects.filter(tipo='SAIDA').count(),1)

    def test_insufficient_or_expired_stock_rejects_without_finance(self):
        with tenant_context(self.a):
            sale,item=self.sale()
            with self.assertRaises(ValidationError): self.paid(sale)
            self.incoming(1,days=-1)
            self.assertEqual(s.availability(self.part,self.depot),0)
            with self.assertRaises(ValidationError): self.paid(sale)
            self.assertFalse(m.Pagamento.objects.exists())

    def test_availability_accounts_for_other_reservations(self):
        with tenant_context(self.a):
            self.incoming(5);m.ConfiguracaoPDV.objects.create(reservar_rascunho=True)
            c.add_item(self.other,self.other_sale.public_id,self.part.sku,2)
            self.assertEqual(s.availability(self.part,self.depot),3)
            self.assertEqual(s.availability(self.part,self.depot,self.other_sale),5)

    def test_my_sales_filter_today_yesterday_period_and_owner(self):
        with tenant_context(self.a): self.incoming(1);sale,item=self.sale();self.paid(sale)
        response=self.client.get('/vendedor/vendas/');self.assertContains(response,str(sale));self.assertNotContains(response,str(self.other_sale))
        self.assertNotContains(self.client.get('/vendedor/vendas/',{'periodo':'ontem'}),str(sale))
        self.assertContains(self.client.get('/vendedor/vendas/',{'periodo':'personalizado','inicio':self.today.isoformat(),'fim':self.today.isoformat()}),str(sale))

    def test_goals_use_configured_value_and_decimal_progress(self):
        with tenant_context(self.a):
            self.incoming(1);sale,item=self.sale();self.paid(sale)
            m.MetaVendedor.objects.create(vendedor=self.seller,competencia=self.today.replace(day=1),valor=20)
            data=s.indicators(self.seller);self.assertEqual((data['month_total'],data['percent'],data['remaining']),(10,Decimal('50.0'),10))
        self.assertContains(self.client.get('/vendedor/meta/'),'50.0')

    def test_goal_management_and_messages_are_scoped(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post('/vendedor/gestao/',{'action':'meta','vendedor':self.seller.pk,'competencia':self.today.replace(day=1).isoformat(),'valor':'200.25'}).status_code,302)
        self.assertEqual(self.client.post('/vendedor/gestao/',{'action':'mensagem','vendedor':self.seller.pk,'mensagem':'Aviso comercial sintético'}).status_code,302)
        self.client.force_login(self.seller);self.assertContains(self.client.get('/vendedor/alertas/'),'Aviso comercial sintético')
        self.client.force_login(self.other);self.assertNotContains(self.client.get('/vendedor/alertas/'),'Aviso comercial sintético')

    def test_commission_not_fabricated(self):
        response=self.client.get('/vendedor/comissao/');self.assertContains(response,'Regra a definir');self.assertContains(response,'Nenhuma comissão')
        self.assertNotContains(response,'5%')

    def test_notifications_read_only_own_recipient(self):
        with tenant_context(self.a):
            row=m.Notificacao.objects.create(usuario=self.seller,chave='seller-qa',titulo='Minha mensagem',mensagem='Teste interno')
        self.assertEqual(self.client.post(f'/vendedor/alertas/{row.pk}/lida/').status_code,302)
        self.client.force_login(self.other);self.assertEqual(self.client.post(f'/vendedor/alertas/{row.pk}/lida/').status_code,404)

    def test_point_uses_employee_schedule_and_overtime_stays_self_service(self):
        with tenant_context(self.a):
            self.assertEqual(w.employee_for(self.seller).jornada_id,self.schedule.pk)
            foreign=m.Funcionario.objects.create(usuario=self.other,matricula='OTHER-SELLER',nome='Outro vendedor',jornada=self.schedule)
            with self.assertRaises(PermissionDenied): w.employee_for(self.seller,foreign.public_id)
        self.assertContains(self.client.get('/ponto/'),'Vendedor sintético')
        self.assertEqual(self.client.get('/ponto/horas-extras/').status_code,200)
        self.assertEqual(self.client.get('/rh/horas-extras/').status_code,403)

    def test_seller_full_point_overtime_request_and_gestor_approval(self):
        day=date(2026,9,28)
        with tenant_context(self.a):
            for kind,hour in [('ENTRADA',8),('SAIDA_INTERVALO',12),('RETORNO_INTERVALO',13),('SAIDA',18)]:
                instant=timezone.make_aware(datetime.combine(day,datetime.min.time()).replace(hour=hour))
                with patch('operacao.workforce.timezone.now',return_value=instant): w.mark(self.seller,kind,uuid.uuid4())
            request=o.request_overtime(self.seller,day,60,'Fechamento do atendimento',uuid.uuid4())
            self.assertEqual(request.status,'PENDENTE')
            o.decide_overtime(self.admin,request.public_id,True,60,'Excedente conferido pela gestão')
            request.refresh_from_db();self.assertEqual(request.status,'APROVADA')

    def test_pwa_same_identity_role_neutral_start_no_private_cache(self):
        manifest=self.client.get('/manifest.webmanifest').json()
        self.assertEqual((manifest['id'],manifest['start_url'],manifest['display']),('/tecnico/','/vertyx/','standalone'))
        worker=self.client.get('/sw.js').content.decode();self.assertIn("event.request.method!=='GET'",worker);self.assertNotIn("'/vendedor/vendas/'",worker)

    def test_bottom_navigation_is_authorized_and_touch_styles_are_present(self):
        response=self.client.get('/vendedor/');html=response.content.decode();bottom=re.search(r'<nav class="sv-bottom".*?</nav>',html,re.S).group()
        for url in ['/pdv/','/vendedor/vendas/','/vendedor/meta/','/ponto/','/vendedor/alertas/']:
            self.assertIn(f'href="{url}"',bottom);self.assertEqual(self.client.get(url).status_code,200)

    def test_switch_organization_recomputes_experience(self):
        member=OrganizationMembership.objects.create(user=self.seller,organization=self.b,role='TECNICO');MembershipERP.objects.create(membership=member,erp=self.erp)
        self.assertRedirects(self.client.post(reverse('platform_core:select_organization'),{'organization':self.b.public_id}),'/tecnico/',fetch_redirect_response=False)
        response=self.client.get('/tecnico/');self.assertNotContains(response,'sv-bottom');self.assertNotContains(response,'Central de Vendas')

    def test_disabled_pdv_module_denies_central(self):
        with tenant_context(self.a): ModuloOrganizacao.objects.create(codigo='pdv',habilitado=False)
        self.assertEqual(self.client.get('/vendedor/').status_code,403)

    def test_admin_gestor_technician_original_experiences_preserved(self):
        for user in [self.admin,self.users['GESTOR']]:
            self.client.force_login(user);self.assertEqual(self.client.get('/assistencia/').status_code,200);self.assertContains(self.client.get('/pdv/'),'PDV · Caixas')
        self.client.force_login(self.users['TECNICO']);self.assertContains(self.client.get('/tecnico/'),'Meus atendimentos');self.assertEqual(self.client.get('/vendedor/').status_code,403)

    def test_invalid_cash_post_never_renders_administrative_cash(self):
        response=self.client.post(reverse('operacao:pdv_cash',args=[self.session.public_id]),{'action':'fechar','contado':'invalid'},follow=True)
        self.assertTemplateUsed(response,'operacao/seller_terminal.html')
        self.assertNotContains(response,str(self.other_session.public_id))
        self.assertNotContains(response,'Conversão de orçamento')

    def test_goal_can_be_updated_without_duplicate_and_foreign_seller_denied(self):
        self.client.force_login(self.admin)
        for amount in ['100.01','250.99']:
            self.assertEqual(self.client.post('/vendedor/gestao/',{'action':'meta','vendedor':self.seller.pk,'competencia':self.today.replace(day=1).isoformat(),'valor':amount}).status_code,302)
        with tenant_context(self.a):
            self.assertEqual(m.MetaVendedor.objects.get().valor,Decimal('250.99'))
        self.client.post('/vendedor/gestao/',{'action':'meta','vendedor':self.admin_b.pk,'competencia':self.today.replace(day=1).isoformat(),'valor':'100'})
        with tenant_context(self.a): self.assertEqual(m.MetaVendedor.objects.count(),1)

    def test_customer_invalid_sale_and_foreign_sale_return_404(self):
        for identifier in ['bad-id',str(uuid.uuid4()),'']:
            self.assertEqual(self.client.get('/vendedor/cliente/',{'venda':identifier}).status_code,404)

    def test_cash_console_payment_dialog_and_quick_actions_are_server_rendered(self):
        with tenant_context(self.a): sale,item=self.sale()
        response=self.client.get(reverse('operacao:pdv_sale',args=[sale.public_id]))
        for text in ['VERTYX','CAIXA ABERTO','Resumo da venda','CLIENTE / CONSUMIDOR','TOTAL DA VENDA','Finalizar venda','id="seller-checkout"','id="seller-barcode-form"']:
            self.assertContains(response,text)
        for key in range(1,12): self.assertContains(response,f'<kbd>F{key}</kbd>')
        self.assertNotContains(response,str(self.other_session.public_id))

    def test_cash_summary_is_limited_to_own_session_and_financial_actions_stay_denied(self):
        with tenant_context(self.a):
            self.incoming(2);sale,item=self.sale();self.paid(sale)
            draft=c.new_sale(self.seller,self.session.public_id,self.depot.pk)
            with self.assertRaises(PermissionDenied): c.cash_operation(self.seller,self.session.public_id,'RETIRADA',1,'Tentativa direta',uuid.uuid4())
            with self.assertRaises(PermissionDenied): c.cash_operation(self.seller,self.session.public_id,'SUPRIMENTO',1,'Tentativa direta',uuid.uuid4())
        response=self.client.get(reverse('operacao:pdv_sale',args=[draft.public_id]))
        self.assertEqual(response.context['cash_summary']['sold'],10)
        self.assertEqual(response.context['cash_summary']['expected'],10)

    def test_supervisor_discount_fingerprint_is_stable_after_decimal_reload(self):
        with tenant_context(self.a):
            self.incoming(3);sale,item=self.sale(3)
            c.pricing(self.admin,sale.public_id,'1.01',0,'Desconto autorizado')
            sale.refresh_from_db();self.assertEqual(self.paid(sale).status,'FINALIZADA')

    def test_login_multiple_organizations_requires_selection_and_ignores_admin_next(self):
        row=OrganizationMembership.objects.create(user=self.seller,organization=self.b,role='VENDEDOR')
        MembershipERP.objects.create(membership=row,erp=self.erp)
        self.client.logout()
        response=self.client.post('/login/?next=/financeiro/',{'username':self.seller.username,'password':'synthetic-seller-test-only'})
        self.assertRedirects(response,'/vertyx/?organizacoes=1')

    def test_receipt_attachments_do_not_leak_other_seller_even_if_created_by_self(self):
        from . import permissions
        with tenant_context(self.a):
            self.other_sale.criado_por=self.seller;self.other_sale.save()
            doc=m.Documento.objects.create(titulo='Documento alheio',venda=self.other_sale,arquivo='permission-qa.pdf',enviado_por=self.seller)
            self.assertFalse(permissions.document_allowed(self.seller,doc))
            self.assertFalse(permissions.documents(self.seller).filter(pk=doc.pk).exists())
        self.assertEqual(self.client.get(reverse('operacao:documento_detalhe',args=[doc.pk])).status_code,404)

    def test_seller_debit_and_credit_use_existing_payment_ledger(self):
        with tenant_context(self.a):
            self.incoming(2)
            for kind in ['DEBITO','CREDITO']:
                method=g.FormaPagamento.objects.create(nome='Cartão '+kind,tipo_pdv=kind,conta_pdv=self.bank)
                sale,item=self.sale()
                result=c.finalize(self.seller,sale.public_id,[{'forma':method.pk,'valor':'10'}],uuid.uuid4())
                self.assertEqual(result.conta.saldo,0)
                self.assertEqual(result.pagamentos_pdv.get().forma_id,method.pk)

    def test_seller_deferred_payment_preserves_receivable_and_requires_customer(self):
        with tenant_context(self.a):
            self.incoming(1);sale,item=self.sale()
            with self.assertRaises(ValidationError): c.finalize(self.seller,sale.public_id,[{'forma':self.credit.pk,'valor':'10'}],uuid.uuid4())
            customer=self.da['customer'];customer.limite_credito=Decimal('10');customer.save()
            sale.cliente=customer;sale.save()
            result=c.finalize(self.seller,sale.public_id,[{'forma':self.credit.pk,'valor':'10'}],uuid.uuid4())
            self.assertEqual(result.conta.saldo,10)
            self.assertEqual(result.snapshot['saldo_pendente'],'10.00')
            self.assertFalse(m.Pagamento.objects.exists())

@skipUnless(connection.vendor=='postgresql','Concorrência exige PostgreSQL')
class SellerConcurrencyTests(SellerData,TransactionTestCase):
    race=previous_tests.OperacaoPostgreSQLTests.race
    def setUp(self): self.setup_seller()
    def test_concurrent_discount_request_is_single_pending_occurrence(self):
        with tenant_context(self.a): sale,item=self.sale()
        self.assertEqual(self.race(lambda _:s.request_discount(self.seller,sale.public_id,1,'Condição concorrente')),['OK','OK'])
        with tenant_context(self.a): self.assertEqual(m.SolicitacaoDescontoPDV.objects.filter(status='PENDENTE').count(),1)

@skipUnless(connection.vendor=='postgresql','Preservação de schema exige PostgreSQL')
class SellerMigrationTests(SellerData,TransactionTestCase):
    def test_additive_schema_keeps_existing_tenants_users_stock_finance_sales_and_point(self):
        from django.db.migrations.executor import MigrationExecutor
        from contas.models import Usuario
        from ordens.models import OrdemServico
        from platform_core.models import Organization
        self.setup_seller()
        with tenant_context(self.a):
            self.incoming(3);sale,item=self.sale();self.paid(sale)
        executor=MigrationExecutor(connection);latest=executor.loader.graph.leaf_nodes()
        models=[Organization,OrganizationMembership,Usuario,Cliente,OrdemServico,g.Peca,m.SaldoDeposito,m.LoteEstoque,m.Venda,m.ItemVenda,g.Lancamento,m.Pagamento,m.Documento,m.Funcionario,m.JornadaTrabalho,m.MarcacaoPonto]
        def snapshot():
            return {model._meta.label:list(model._base_manager.order_by('pk').values()) for model in models}
        try:
            executor.migrate([('operacao','0016_hora_extra_aprovacao')])
            before=snapshot()
            MigrationExecutor(connection).migrate(latest)
            self.assertEqual(snapshot(),before)
            self.assertIn('operacao_metavendedor',connection.introspection.table_names())
            self.assertIn('operacao_solicitacaodescontopdv',connection.introspection.table_names())
        finally:
            MigrationExecutor(connection).migrate(latest)
