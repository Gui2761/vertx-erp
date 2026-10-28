import re
import uuid
from decimal import Decimal
from pathlib import Path
from html.parser import HTMLParser
from PIL import Image
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership, MembershipERP, PermissaoMembership
from .test_block3_commerce import CommerceData
from . import models as m, commerce as c


class CashOpeningFormParser(HTMLParser):
    """Extract the controls the browser submits from rendered opening markup."""
    def __init__(self):
        super().__init__()
        self.in_details=self.in_form=self.in_select=self.in_option=False
        self.form=None
        self.current_select=self.current_option=None

    def handle_starttag(self, tag, values):
        attrs=dict(values)
        if tag=='details' and attrs.get('id')=='abrir-meu-caixa': self.in_details=True
        elif tag=='form' and self.in_details and self.form is None:
            self.in_form=True;self.form={'attrs':attrs,'inputs':[],'selects':[]}
        elif self.in_form and tag=='input': self.form['inputs'].append(attrs)
        elif self.in_form and tag=='select': self.in_select=True;self.current_select={'attrs':attrs,'options':[]}
        elif self.in_select and tag=='option': self.in_option=True;self.current_option={'attrs':attrs,'text':''}

    def handle_data(self, data):
        if self.in_option: self.current_option['text']+=data

    def handle_endtag(self, tag):
        if tag=='option' and self.in_option:
            self.current_select['options'].append(self.current_option);self.current_option=None;self.in_option=False
        elif tag=='select' and self.in_select:
            self.form['selects'].append(self.current_select);self.current_select=None;self.in_select=False
        elif tag=='form' and self.in_form: self.in_form=False
        elif tag=='details' and self.in_details: self.in_details=False


class AdministrativePDVTests(CommerceData,TestCase):
    def setUp(self):
        self.setup_commerce()
        self.client.force_login(self.admin)

    def test_admin_and_gestor_modules_are_ordered_and_collapsed_on_every_page(self):
        expected=['Financeiro','PDV','Vendas','Estoque','Compras','RH','Relatórios','Configurações','Operacional']
        for user in [self.admin,self.users['GESTOR']]:
            self.client.force_login(user)
            self.assertRedirects(self.client.get('/vertyx/'),'/assistencia/')
            for url in ['/assistencia/']:
                response=self.client.get(url)
                self.assertEqual(response.status_code,200)
                html=response.content.decode()
                groups=re.findall(r'<details class="vx-module"([^>]*)><summary>(.*?)</summary>',html)
                self.assertEqual([label for attrs,label in groups],expected)
                self.assertTrue(all('open' not in attrs for attrs,label in groups))
                self.assertContains(response,'href="/pdv/"')
                self.assertNotContains(response,'VERTYX | ASSISTÊNCIA')
                self.assertContains(response,'/rh/horas-extras/')

    def test_admin_pdv_menu_contains_existing_management_destinations(self):
        response=self.client.get('/assistencia/')
        html=response.content.decode()
        pdv_group=re.search(r'<details class="vx-module"[^>]*><summary>PDV</summary>(.*?)</details>',html,re.S).group(1)
        for label,url in [
            ('Central do PDV','/pdv/'),('Caixas','/pdv/?gestao=1'),
            ('Operadores','/vertyx/empresa/permissoes/'),
            ('Movimentações','/pdv/movimentacoes/'),('Histórico de vendas','/pdv/historico/'),
            ('Configurações','/pdv/configuracao/'),
        ]:
            self.assertIn(label,pdv_group)
            self.assertIn(f'href="{url}"',pdv_group)

    def test_empty_company_gets_guided_setup_without_creating_records(self):
        self.client.force_login(self.admin_b)
        with tenant_context(self.b):
            before=(m.ContaBancaria.objects.count(),m.SessaoCaixa.objects.count(),m.MovimentoCaixa.objects.count(),m.Deposito.objects.count())
        response=self.client.get('/pdv/?gestao=1')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Configuração inicial')
        self.assertContains(response,'/bancos/novo/')
        self.assertContains(response,'/depositos/novo/')
        self.assertContains(response,'/vertyx/empresa/permissoes/')
        with tenant_context(self.b):
            after=(m.ContaBancaria.objects.count(),m.SessaoCaixa.objects.count(),m.MovimentoCaixa.objects.count(),m.Deposito.objects.count())
        self.assertEqual(after,before)

    def test_pdv_movements_are_read_only_tenant_scoped_and_supervisor_only(self):
        from django.utils import timezone
        from . import services as finance
        with tenant_context(self.a):
            finance.caixa(self.admin,self.cash.pk,'ENTRADA','5.00',timezone.localdate(),'PDV sintético A',uuid.uuid4(),origem='PDV')
            self.incoming(1)
            sale=c.new_sale(self.operator,self.session.public_id,self.depot.pk)
            c.add_item(self.operator,sale.public_id,self.part.sku,1)
            c.finalize(self.operator,sale.public_id,[
                {'forma':self.cash_method.pk,'valor':'5.00'},
                {'forma':self.pix.pk,'valor':'5.00'},
            ],uuid.uuid4())
        with tenant_context(self.b):
            depot_b=m.Deposito.objects.create(nome='Depósito sintético B')
            other_cash=m.ContaBancaria.objects.create(nome='Caixa sintético B',tipo='CAIXA',deposito_padrao=depot_b)
            finance.caixa(self.admin_b,other_cash.pk,'ENTRADA','9.00',timezone.localdate(),'PDV sintético B',uuid.uuid4(),origem='PDV')
        response=self.client.get('/pdv/movimentacoes/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'PDV sintético A')
        self.assertContains(response,str(sale))
        self.assertNotContains(response,'PDV sintético B')
        before=m.MovimentoCaixa.objects.count()
        self.assertEqual(self.client.get('/pdv/movimentacoes/?inicio=inválida').status_code,400)
        self.assertEqual(m.MovimentoCaixa.objects.count(),before)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get('/pdv/movimentacoes/').status_code,403)
        self.assertEqual(self.client.get('/vertyx/empresa/permissoes/').status_code,403)

    def test_admin_terminal_reuses_open_cash_without_get_writes(self):
        with tenant_context(self.a):
            cash=m.ContaBancaria.objects.create(nome='OKOK sintético',tipo='CAIXA',deposito_padrao=self.depot)
            session=c.open_cash(self.admin,cash.pk,'12.34',uuid.uuid4())
            before=list(m.SessaoCaixa.objects.order_by('pk').values())
            sale_count=m.Venda.objects.count()
            movements=m.MovimentoCaixa.objects.count()
        for _ in range(2):
            response=self.client.get('/pdv/')
            self.assertTemplateUsed(response,'operacao/seller_terminal.html')
            self.assertContains(response,'OKOK sintético')
            self.assertContains(response,str(session.public_id))
            self.assertContains(response,'Gestão de caixas')
        with tenant_context(self.a):
            self.assertEqual(list(m.SessaoCaixa.objects.order_by('pk').values()),before)
            self.assertEqual(m.Venda.objects.count(),sale_count)
            self.assertEqual(m.MovimentoCaixa.objects.count(),movements)

    def test_opening_cash_from_terminal_commits_and_unlocks_sale_without_duplicate(self):
        with tenant_context(self.a):
            cash=m.ContaBancaria.objects.create(nome='Caixa abertura web sintético',tipo='CAIXA',deposito_padrao=self.depot)
        opening_id=uuid.uuid4()
        response=self.client.post('/pdv/',{'action':'abrir','conta':cash.pk,'contado':'100.00','request_id':opening_id})
        self.assertRedirects(response,'/pdv/')
        with tenant_context(self.a):
            session=m.SessaoCaixa.objects.get(conta=cash,fechado_em__isnull=True)
            self.assertEqual((session.operador_id,session.saldo_abertura,session.abertura_id),(self.admin.pk,Decimal('100.00'),opening_id))
            self.assertEqual(m.MovimentoCaixa.objects.filter(conta=cash).count(),0)
        page=self.client.get('/pdv/')
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'Iniciar venda rápida')
        self.assertContains(page,str(session.public_id))

        # A second opening with a new request key must be rejected while the
        # first session is active, preserving both the balance and one session.
        duplicate=self.client.post('/pdv/',{'action':'abrir','conta':cash.pk,'contado':'100.00','request_id':uuid.uuid4()})
        self.assertEqual(duplicate.status_code,200)
        self.assertContains(duplicate,'Conta já possui caixa aberto.')
        self.assertContains(duplicate,'value="100.00"')
        self.assertContains(duplicate,'id="abrir-meu-caixa" open')
        with tenant_context(self.a):
            self.assertEqual(m.SessaoCaixa.objects.filter(conta=cash,fechado_em__isnull=True).count(),1)
            session.refresh_from_db();self.assertEqual(session.saldo_abertura,Decimal('100.00'))

    def test_invalid_cash_opening_keeps_amount_and_explains_validation(self):
        with tenant_context(self.a):
            cash=m.ContaBancaria.objects.create(nome='Caixa inválido sintético',tipo='CAIXA',deposito_padrao=self.depot)
        response=self.client.post('/pdv/',{'action':'abrir','conta':cash.pk,'contado':'100.001','request_id':uuid.uuid4()})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Informe valor monetário exato em centavos.')
        self.assertContains(response,'value="100.001"')
        self.assertContains(response,'id="abrir-meu-caixa" open')
        with tenant_context(self.a):self.assertFalse(m.SessaoCaixa.objects.filter(conta=cash).exists())

    def test_cash_opening_reports_invalid_account_identifier_and_scoped_missing_cash(self):
        invalid=self.client.post('/pdv/',{'action':'abrir','conta':'caixa-inválido','contado':'100.00','request_id':uuid.uuid4()})
        self.assertEqual(invalid.status_code,200)
        self.assertContains(invalid,'Selecione um caixa válido e tente novamente.')
        missing=self.client.post('/pdv/',{'action':'abrir','conta':'999999999','contado':'100.00','request_id':uuid.uuid4()})
        self.assertEqual(missing.status_code,200)
        self.assertContains(missing,'O caixa selecionado não está disponível nesta organização.')
        with tenant_context(self.a):
            self.assertFalse(m.SessaoCaixa.objects.filter(conta_id=999999999).exists())

    def test_cash_opening_reports_missing_idempotency_field_without_writing(self):
        with tenant_context(self.a):
            cash=m.ContaBancaria.objects.create(nome='Caixa sem token sintético',tipo='CAIXA',deposito_padrao=self.depot)
        response=self.client.post('/pdv/',{'action':'abrir','conta':cash.pk,'contado':'100.00'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Identificador da operação inválido.')
        with tenant_context(self.a):
            self.assertFalse(m.SessaoCaixa.objects.filter(conta=cash).exists())

    def test_cash_opening_posts_the_fields_from_rendered_html(self):
        with tenant_context(self.a):
            depot=m.Deposito.objects.create(nome='Depósito HTML sintético')
            cash=m.ContaBancaria.objects.create(pk=1728,nome='Caixa HTML sintético',tipo='CAIXA',deposito_padrao=depot)
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        session=client.session;session['organization_id']=self.a.pk;session.save()
        headers={'HTTP_HOST':'127.0.0.1:8894'}
        page=client.get('/pdv/',**headers)
        self.assertEqual(page.status_code,200)
        parser=CashOpeningFormParser();parser.feed(page.content.decode())
        self.assertIsNotNone(parser.form)
        attrs=parser.form['attrs']
        self.assertEqual(attrs.get('method','').lower(),'post')
        self.assertFalse(attrs.get('action'))
        inputs={row.get('name'):row.get('value','') for row in parser.form['inputs'] if row.get('name')}
        self.assertEqual(inputs.get('action'),'abrir')
        uuid.UUID(inputs['request_id'])
        self.assertTrue(inputs.get('csrfmiddlewaretoken'))
        select=next(row for row in parser.form['selects'] if row['attrs'].get('name')=='conta')
        option=next(row for row in select['options'] if row['attrs'].get('value')==str(cash.pk))
        self.assertIn('Caixa HTML sintético',option['text'])
        self.assertEqual(option['attrs']['value'],str(cash.pk))
        fields={'action':inputs['action'],'request_id':inputs['request_id'],'csrfmiddlewaretoken':inputs['csrfmiddlewaretoken'],'conta':option['attrs']['value'],'contado':'100'}
        posted=client.post(attrs.get('action') or '/pdv/',fields,HTTP_HOST='127.0.0.1:8894',HTTP_ORIGIN='http://127.0.0.1:8894',HTTP_REFERER='http://127.0.0.1:8894/pdv/')
        self.assertEqual(posted.status_code,302)
        self.assertEqual(posted['Location'],'/pdv/')
        with tenant_context(self.a):
            opened=m.SessaoCaixa.objects.get(conta=cash,abertura_id=inputs['request_id'])
            self.assertEqual((opened.organization_id,opened.operador_id,opened.saldo_abertura),(self.a.pk,self.admin.pk,Decimal('100.00')))

    def test_admin_can_open_professional_draft_and_keep_legacy_management(self):
        with tenant_context(self.a):
            sale=c.new_sale(self.admin,self.session.public_id,self.depot.pk)
        response=self.client.get(f'/pdv/vendas/{sale.public_id}/')
        self.assertTemplateUsed(response,'operacao/seller_pdv.html')
        self.assertContains(response,'Resumo da venda')
        self.assertContains(response,'css/seller.css')
        self.assertContains(response,'data-connection-status')
        with tenant_context(self.a):
            before=(m.ContaBancaria.objects.count(),m.Deposito.objects.count(),m.SessaoCaixa.objects.count(),m.MovimentoCaixa.objects.count())
        cash_page=self.client.get('/pdv/?gestao=1')
        self.assertTemplateUsed(cash_page,'operacao/pdv_home.html')
        for path in ['/bancos/?tipo=CAIXA','/bancos/novo/','/depositos/','/vertyx/empresa/permissoes/','/pdv/movimentacoes/']:
            self.assertContains(cash_page,path)
        with tenant_context(self.a):
            after=(m.ContaBancaria.objects.count(),m.Deposito.objects.count(),m.SessaoCaixa.objects.count(),m.MovimentoCaixa.objects.count())
        self.assertEqual(after,before)
        self.assertTemplateUsed(self.client.get(f'/pdv/caixas/{self.session.public_id}/'),'operacao/pdv_cash.html')

    def test_admin_professional_checkout_uses_official_stock_finance_receipt_and_returns(self):
        with tenant_context(self.a):
            self.incoming(3)
            sale=c.new_sale(self.admin,self.session.public_id,self.depot.pk)
        url=f'/pdv/vendas/{sale.public_id}/'
        self.assertEqual(self.client.post(url,{'action':'adicionar','codigo':self.part.sku,'quantidade':'2'}).status_code,302)
        self.assertContains(self.client.get(url),self.part.descricao)
        import json
        self.assertEqual(self.client.post(url,{'action':'finalizar','request_id':uuid.uuid4(),'pagamentos':json.dumps([{'forma':self.cash_method.pk,'valor':'8.00','recebido':'10.00'},{'forma':self.pix.pk,'valor':'12.00'}])}).status_code,302)
        with tenant_context(self.a):
            sale.refresh_from_db()
            self.assertEqual(sale.status,'FINALIZADA')
            self.assertEqual(sale.conta.saldo,0)
            self.assertEqual(sale.pagamentos_pdv.get(forma=self.cash_method).troco,2)
            self.assertEqual(sale.itens.get().movimento.lotes_movimentados.count(),1)
        self.assertTemplateUsed(self.client.get(url),'operacao/pdv_sale.html')
        self.assertTemplateUsed(self.client.get(url+'comprovante/'),'operacao/pdv_receipt.html')

    def test_complete_synthetic_cash_sale_closes_at_expected_amount(self):
        from decimal import Decimal
        from django.utils import timezone
        from gestao import models as g, services as stock_services

        operator=self.user('operator-e2e',self.a,'VENDEDOR')
        membership=OrganizationMembership.objects.get(user=operator,organization=self.a)
        with tenant_context(self.a):
            PermissaoMembership.objects.create(membership=membership,capacidade='operar_pdv',permitido=True)
            depot=m.Deposito.objects.create(nome='Loja Principal')
            cash=m.ContaBancaria.objects.create(nome='Caixa 01',tipo='CAIXA',deposito_padrao=depot,saldo_inicial=0)
            product=g.Peca.objects.create(sku='FRALDA-ADULTO-TESTE',descricao='Fralda Adulto Teste',preco_venda=Decimal('25.00'),custo_aquisicao=Decimal('5.00'))
            stock_services.movimentar(self.admin,product.pk,'ENTRADA',10,'Carga sintética para homologação',destino_id=depot.pk,lote_data={'numero':'LOTE-FRALDA-TESTE','validade':self.today+timezone.timedelta(days=365),'custo_unitario':Decimal('5.00')})
            session=c.open_cash(operator,cash.pk,'100.00',uuid.uuid4())
            sale=c.new_sale(operator,session.public_id,depot.pk)
            c.add_item(operator,sale.public_id,product.sku,2)
            sale=c.finalize(operator,sale.public_id,[{'forma':self.cash_method.pk,'valor':'50.00','recebido':'50.00'}],uuid.uuid4())
            sale.refresh_from_db()

            balance=m.SaldoDeposito.objects.get(deposito=depot,peca=product).quantidade
            self.assertEqual(balance,Decimal('8.000'))
            self.assertEqual(sale.itens.get().peca.descricao,'Fralda Adulto Teste')
            self.assertEqual((sale.status,sale.total,sale.conta.status),('FINALIZADA',Decimal('50.00'),'LIQUIDADO'))
            payment=sale.pagamentos_pdv.get()
            self.assertEqual((payment.valor,payment.recebido,payment.troco),(Decimal('50.00'),Decimal('50.00'),Decimal('0.00')))
            movement=m.MovimentoCaixa.objects.get(conta=cash,lancamento=sale.conta)
            self.assertEqual((movement.tipo,movement.valor,movement.origem),('ENTRADA',Decimal('50.00'),'LANCAMENTO'))
            self.assertEqual(m.EventoCaixa.objects.get(movimento=movement).sessao_id,session.pk)
            self.assertEqual(cash.saldo,Decimal('50.00'))
            closed=c.close_cash(operator,session.public_id,'150.00')
            self.assertEqual((closed.esperado,closed.contado,closed.diferenca),(Decimal('150.00'),Decimal('150.00'),Decimal('0.00')))

        self.client.force_login(operator)
        history=self.client.get('/pdv/historico/')
        self.assertEqual(history.status_code,200)
        self.assertContains(history,str(sale))

        unauthorized=self.user('operator-without-capability',self.a,'VENDEDOR')
        self.client.force_login(unauthorized)
        self.assertEqual(self.client.get('/pdv/configuracao/').status_code,403)
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied):
                c.new_sale(unauthorized,session.public_id,depot.pk)

    def test_cash_default_depot_is_used_for_sale_and_stock_decrement(self):
        from decimal import Decimal
        from gestao import services as stock_services
        with tenant_context(self.a):
            other=m.Deposito.objects.create(nome='Depósito secundário')
            stock_services.movimentar(self.admin,self.part.pk,'ENTRADA',2,'Estoque secundário',destino_id=other.pk)
            stock_services.movimentar(self.admin,self.part.pk,'ENTRADA',3,'Estoque do caixa',destino_id=self.depot.pk)
            sale=c.new_sale(self.operator,self.session.public_id)
            self.assertEqual(sale.deposito_id,self.depot.pk)
            c.add_item(self.operator,sale.public_id,self.part.sku,1)
            c.finalize(self.operator,sale.public_id,[{'forma':self.cash_method.pk,'valor':'10.00'}],uuid.uuid4())
            self.assertEqual(m.SaldoDeposito.objects.get(deposito=self.depot,peca=self.part).quantidade,Decimal('2.000'))
            self.assertEqual(m.SaldoDeposito.objects.get(deposito=other,peca=self.part).quantidade,Decimal('2.000'))

    def test_cash_without_active_default_depot_cannot_open_or_sell(self):
        from .forms import ContaBancariaForm
        with tenant_context(self.a):
            form=ContaBancariaForm({'nome':'Caixa sem depósito','tipo':'CAIXA','saldo_inicial':'0.00','ativo':'on'})
            self.assertFalse(form.is_valid())
            self.assertIn('deposito_padrao',form.errors)
        with tenant_context(self.a):
            unconfigured=m.ContaBancaria.objects.create(nome='Caixa sem depósito',tipo='CAIXA')
            with self.assertRaises(ValidationError):
                c.open_cash(self.operator,unconfigured.pk,0,uuid.uuid4())
            # A legacy/open session may exist when an administrator removes a
            # depot in old data; it remains closeable but cannot start a sale.
            unconfigured.deposito_padrao=self.depot
            unconfigured.save()
            session=c.open_cash(self.operator,unconfigured.pk,0,uuid.uuid4())
            unconfigured.deposito_padrao=None
            unconfigured.save()
            with self.assertRaises(ValidationError):
                c.new_sale(self.operator,session.public_id)
            self.assertFalse(m.Venda.objects.filter(sessao_caixa=session).exists())

    def test_admin_can_change_cash_default_without_rewriting_existing_sale_history(self):
        from gestao import models as g, services as stock_services
        with tenant_context(self.a):
            self.incoming(2)
            old_sale=c.new_sale(self.operator,self.session.public_id)
            c.add_item(self.operator,old_sale.public_id,self.part.sku,1)
            c.finalize(self.operator,old_sale.public_id,[{'forma':self.cash_method.pk,'valor':'10.00'}],uuid.uuid4())
            original_depot=old_sale.deposito_id
            movement_id=old_sale.itens.get().movimento_id
            new_depot=m.Deposito.objects.create(nome='Depósito novo padrão')
        response=self.client.post(f'/bancos/{self.cash.pk}/editar/',{
            'nome':self.cash.nome,'banco':'','agencia':'','numero':'','titular':'','tipo':'CAIXA',
            'deposito_padrao':new_depot.pk,'saldo_inicial':'0.00','ativo':'on',
        })
        self.assertEqual(response.status_code,302,response.content)
        with tenant_context(self.a):
            self.cash.refresh_from_db();old_sale.refresh_from_db()
            self.assertEqual(self.cash.deposito_padrao_id,new_depot.pk)
            self.assertEqual(old_sale.deposito_id,original_depot)
            self.assertEqual(old_sale.itens.get().movimento_id,movement_id)
            self.assertTrue(g.Movimentacao.objects.filter(pk=movement_id).exists())
            new_sale=c.new_sale(self.operator,self.session.public_id)
            self.assertEqual(new_sale.deposito_id,new_depot.pk)

    def test_vendor_cannot_change_cash_depot_or_choose_another_for_sale(self):
        vendor=self.user('seller-cannot-configure-cash',self.a,'VENDEDOR')
        member=OrganizationMembership.objects.get(user=vendor,organization=self.a)
        with tenant_context(self.a):
            PermissaoMembership.objects.create(membership=member,capacidade='operar_pdv',permitido=True)
            other=m.Deposito.objects.create(nome='Depósito alternativo')
            seller_cash=m.ContaBancaria.objects.create(nome='Caixa do vendedor',tipo='CAIXA',deposito_padrao=self.depot)
            seller_session=c.open_cash(vendor,seller_cash.pk,0,uuid.uuid4())
        self.client.force_login(vendor)
        self.assertEqual(self.client.get(f'/bancos/{self.cash.pk}/editar/').status_code,403)
        response=self.client.post(f'/pdv/caixas/{seller_session.public_id}/',{
            'action':'venda','request_id':uuid.uuid4(),'deposito':other.pk,
        })
        self.assertEqual(response.status_code,302,response.content)
        self.assertIn('/pdv/vendas/',response.url)
        with tenant_context(self.a):
            sale=m.Venda.objects.get(sessao_caixa=seller_session)
            self.assertEqual(sale.deposito_id,self.depot.pk)

    def test_cash_depot_foreign_organization_is_rejected(self):
        with tenant_context(self.b):
            foreign=m.Deposito.objects.create(nome='Depósito de outra organização')
        with tenant_context(self.a):
            account=m.ContaBancaria.objects.create(nome='Caixa local',tipo='CAIXA',deposito_padrao=self.depot)
            account.deposito_padrao=foreign
            with self.assertRaises(ValidationError):
                account.save()
            form=__import__('operacao.forms',fromlist=['ContaBancariaForm']).ContaBancariaForm(
                {'nome':'Caixa adulterado','tipo':'CAIXA','deposito_padrao':foreign.pk,'saldo_inicial':'0.00','ativo':'on'},
                instance=account,
            )
            self.assertFalse(form.is_valid())

    def test_seller_cannot_use_administrative_cash_management(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get('/pdv/?gestao=1').status_code,403)
        response=self.client.get('/pdv/')
        self.assertTemplateUsed(response,'operacao/seller_terminal.html')
        for text in ['Gestão de caixas','Operadores','Movimentações','Configurações']:
            self.assertNotContains(response,text)
        vendor=self.user('vendor-without-pdv',self.a,'VENDEDOR')
        self.client.force_login(vendor)
        self.assertEqual(self.client.get('/pdv/').status_code,403)
        self.assertEqual(self.client.get('/pdv/?gestao=1').status_code,403)
        self.assertEqual(self.client.get('/vertyx/empresa/permissoes/').status_code,403)

    def test_technician_navigation_and_pwa_identity_are_preserved(self):
        self.client.force_login(self.users['TECNICO'])
        response=self.client.get('/tecnico/')
        self.assertNotContains(response,'vx-module')
        self.assertNotContains(response,'Central do PDV')
        self.assertContains(response,'Atalhos do técnico')
        self.assertContains(response,'href="/tecnico/manifest.webmanifest"')
        self.assertEqual(self.client.get('/pdv/').status_code,403)
        manifest=self.client.get('/tecnico/manifest.webmanifest').json()
        self.assertEqual((manifest['id'],manifest['start_url'],manifest['scope']),('/tecnico/','/tecnico/','/tecnico/'))

    def test_switch_organization_removes_admin_navigation_and_pdv(self):
        member=OrganizationMembership.objects.create(user=self.admin,organization=self.b,role='TECNICO')
        MembershipERP.objects.create(membership=member,erp=self.erp)
        self.assertEqual(self.client.post('/vertyx/organizacao/',{'organization':self.b.public_id}).status_code,302)
        response=self.client.get('/tecnico/')
        self.assertNotContains(response,'vx-module')
        self.assertEqual(self.client.get('/pdv/').status_code,403)

    def test_admin_foreign_organization_sale_still_404(self):
        with tenant_context(self.a): sale=c.new_sale(self.admin,self.session.public_id,self.depot.pk)
        self.client.force_login(self.admin_b)
        self.assertEqual(self.client.get(f'/pdv/vendas/{sale.public_id}/').status_code,404)

    def test_pdv_manifest_is_public_stable_and_icons_have_correct_sizes(self):
        self.client.logout()
        response=self.client.get('/manifest-pdv.webmanifest')
        self.assertEqual(response.status_code,200)
        manifest=response.json()
        self.assertEqual((manifest['id'],manifest['start_url'],manifest['scope'],manifest['display']),('/pdv/','/pdv/','/pdv/','standalone'))
        self.assertEqual(response['Content-Type'],'application/manifest+json')
        for icon in manifest['icons']:
            with Image.open(Path(settings.BASE_DIR)/icon['src'].lstrip('/')) as image:
                size=int(icon['sizes'].split('x')[0]);self.assertEqual(image.size,(size,size))
        self.assertRedirects(self.client.get('/pdv/'),'/pdv/entrar/?next=/pdv/')

    def test_pdv_has_its_manifest_and_installation_instructions_and_offline_notice(self):
        response=self.client.get('/pdv/')
        self.assertContains(response,'href="/pdv/manifest.webmanifest"')
        for text in ['Instalar VERTYX PDV','No Chrome:','No Edge:','Operações offline ficam pendentes']:
            self.assertContains(response,text)
        worker=self.client.get('/sw.js')
        self.assertEqual(worker['Service-Worker-Allowed'],'/')
        self.assertIn("event.request.method!=='GET'",worker.content.decode())
