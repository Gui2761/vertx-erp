import uuid
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError, PermissionDenied
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership,PermissaoMembership,FilialEmpresa
from gestao import models as g,services as gs
from . import models as m,services as s,commerce as c,stock,executive
from .forms import ItemCompraForm
from .test_block3_commerce import CommerceData

class IntegrationTests(CommerceData,TestCase):
    def setUp(self): self.setup_commerce()

    def test_commercial_purchase_converts_and_partial_receipt_uses_same_stock(self):
        buyer=self.user('comprador-b3',self.a,'COMPRAS')
        with tenant_context(self.a):
            self.part.unidade_compra='CX';self.part.fator_compra=10;self.part.estoque_maximo=20;self.part.save()
            purchase=m.Compra.objects.create(deposito=self.depot,fornecedor=self.supplier,necessidade='Caixas',vencimento=self.today,criado_por=buyer)
            form=ItemCompraForm({'peca':self.part.pk,'quantidade':2,'custo_unitario':100,'unidade_entrada':'compra'},instance=m.ItemCompra(compra=purchase))
            self.assertTrue(form.is_valid(),form.errors)
            item=form.save();self.assertEqual((item.quantidade,item.custo_unitario),(20,10))
            self.assertEqual(stock.metrics(self.part)['em_compra'],0)
            s.compra_acao(buyer,purchase.pk,'aprovar');s.compra_acao(buyer,purchase.pk,'pedir')
            self.assertEqual(stock.metrics(self.part)['em_compra'],20)
            s.receber_compra(buyer,purchase.pk,[{'item_id':item.pk,'quantidade':5,'lote':'PARCIAL'}],uuid.uuid4())
            purchase.refresh_from_db();self.assertIsNone(purchase.conta_id)
            s.receber_compra(buyer,purchase.pk,[{'item_id':item.pk,'quantidade':15,'lote':'FINAL'}],uuid.uuid4())
            purchase.refresh_from_db();self.assertEqual(purchase.conta.valor,200)
            self.assertEqual(stock.metrics(self.part)['em_compra'],0)
            sale,line=self.sale(2);self.paid(sale)
            self.part.refresh_from_db();line.refresh_from_db()
            self.assertEqual((self.part.quantidade_atual,line.custo_total),(18,20))
            with self.assertRaises(PermissionDenied): gs.movimentar(buyer,self.part.pk,'ENTRADA',100,destino_id=self.depot.pk)

    def test_executive_nets_return_and_credit_abatement_is_not_cash(self):
        with tenant_context(self.a):
            self.incoming(2,cost='7.33');sale,item=self.sale(2);sale=self.paid(sale)
            c.return_sale(self.admin,sale.public_id,[{'item':item.pk,'quantidade':1}],'Devolução parcial',uuid.uuid4())
            data=executive.indicators(self.admin,self.today,self.today)
            self.assertEqual((data['vendas_liquidas'],data['custo_liquido_produtos'],data['margem_registrada']),(10,Decimal('7.33'),Decimal('2.67')))
            self.assertEqual(data['financeiro']['recebido'],20)
            from .reporting import report_data
            headers,rows=report_data(self.admin,'vendas_margem',{})
            self.assertEqual(rows[0][-2:],[10,Decimal('2.67')])
            branch=FilialEmpresa.objects.create(codigo='F1',nome='Filial própria')
            filtered=executive.indicators(self.admin,self.today,self.today,branch.pk)
            self.assertEqual(filtered['vendas_liquidas'],0);self.assertIsNone(filtered['os_no_periodo'])
        self.client.force_login(self.admin)
        session=self.client.session;session['organization_id']=self.a.pk;session.save()
        dashboard_response=self.client.get(reverse('operacao:executive'))
        # The basic SaaS fixture includes the standard dashboard charts but
        # not the separate advanced-indicators endpoint.
        self.assertEqual(dashboard_response.status_code,403)
        self.assertEqual(self.client.get(reverse('core:painel')).status_code,200)

    def test_sales_chart_uses_only_the_active_organization(self):
        with tenant_context(self.a):
            self.incoming(2)
            sale, _item = self.sale(2)
            self.paid(sale)
            chart_a = executive.sales_chart(self.today, self.today, '7')
        with tenant_context(self.b):
            chart_b = executive.sales_chart(self.today, self.today, '7')
        self.assertEqual(sum((row['vendas'] for row in chart_b), Decimal('0')), Decimal('0'))
        self.assertGreater(sum((row['vendas'] for row in chart_a), Decimal('0')), Decimal('0'))

    def test_analytics_filters_are_limited_by_plan_level(self):
        basic = executive.PeriodForm({'periodo':'MES','grafico':'3M'}, analytics_level='BASICO')
        self.assertFalse(basic.is_valid())
        professional = executive.PeriodForm({'periodo':'PERSONALIZADO','inicio':'2026-01-01',
                                             'fim':'2026-06-30','grafico':'6M'}, analytics_level='AVANCADO')
        self.assertTrue(professional.is_valid(), professional.errors)
        enterprise = executive.PeriodForm({'periodo':'PERSONALIZADO','inicio':'2025-10-22',
                                           'fim':'2026-10-22','grafico':'12M'}, analytics_level='COMPLETO')
        self.assertTrue(enterprise.is_valid(), enterprise.errors)

    def test_permission_admin_updates_override_without_duplicate_and_pdv_cannot(self):
        with tenant_context(self.a): member=OrganizationMembership.objects.get(user=self.operator,organization=self.a)
        url=reverse('platform_core:permissoes')
        for allow in (True,False):
            data={'membership':member.pk,'capacidade':'pdv'}
            if allow:data['permitido']='on'
            self.assertEqual(self.client.post(url,data).status_code,302)
        with tenant_context(self.a):
            self.assertEqual(PermissaoMembership.objects.filter(membership=member).count(),1)
            self.assertFalse(PermissaoMembership.objects.get(membership=member).permitido)
        self.client.force_login(self.operator);self.assertEqual(self.client.post(url,{'membership':member.pk,'capacidade':'financeiro_escrever','permitido':'on'}).status_code,403)

    def test_creation_token_is_idempotent_and_customer_credit_cannot_be_changed_by_pdv(self):
        with tenant_context(self.a):
            key=uuid.uuid4();sale=c.new_sale(self.operator,self.session.public_id,self.depot.pk,request_id=key)
            self.assertEqual(c.new_sale(self.operator,self.session.public_id,self.depot.pk,request_id=key).pk,sale.pk)
            with self.assertRaises(ValidationError):c.new_sale(self.operator,self.session.public_id,self.depot.pk,self.da['customer'].pk,request_id=key)
            from clientes.forms import ClienteForm
            form=ClienteForm({'nome_razao_social':'Consumidor','limite_credito':'999999'},user=self.operator)
            self.assertNotIn('limite_credito',form.fields)

    def test_non_fractionable_product_rejects_direct_stock_fraction(self):
        with tenant_context(self.a):
            self.part.fracionavel=False;self.part.save()
            with self.assertRaises(ValidationError): self.incoming(Decimal('0.5'))
            self.assertEqual(g.Movimentacao.objects.count(),0)

    def test_executive_query_count_does_not_grow_per_sale(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with tenant_context(self.a):
            self.incoming(10);sale,item=self.sale();self.paid(sale)
            with CaptureQueriesContext(connection) as first:
                executive.indicators(self.admin,self.today,self.today)
            for index in range(5):
                sale,item=self.sale();self.paid(sale)
            with CaptureQueriesContext(connection) as second:
                data=executive.indicators(self.admin,self.today,self.today)
            self.assertEqual(data['vendas_liquidas'],60)
            self.assertLessEqual(len(second),len(first)+1)

    def test_executive_override_does_not_implicitly_grant_financial_access(self):
        with tenant_context(self.a):
            member=OrganizationMembership.objects.get(user=self.operator,organization=self.a)
            PermissaoMembership.objects.create(membership=member,capacidade='executivo',permitido=True)
            with self.assertRaises(PermissionDenied):
                executive.indicators(self.operator,self.today,self.today)
            # Other explicitly authorized roles retain the original separation.
            stock_member=OrganizationMembership.objects.get(user=self.users['ESTOQUE'],organization=self.a)
            PermissaoMembership.objects.create(membership=stock_member,capacidade='executivo',permitido=True)
            self.assertEqual(executive.indicators(self.users['ESTOQUE'],self.today,self.today)['financeiro'],{})
