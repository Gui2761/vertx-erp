from decimal import Decimal
import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from unittest.mock import patch
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase
from unittest import skipUnless
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership, PermissaoMembership, ModuloOrganizacao
from platform_core.modules import has_capability
from gestao import models as g
from . import models as m, commerce as c, pdv_offline as off
from .test_block3_commerce import CommerceData

class SplitPWAData(CommerceData):
    def setup_split(self):
        self.setup_commerce()
        self.seller=self.user('split-seller',self.a,'VENDEDOR')
        self.member=OrganizationMembership.objects.get(user=self.seller,organization=self.a)
        self.client.force_login(self.operator)
    def grant(self,allowed=True):
        return PermissaoMembership.objects.update_or_create(membership=self.member,capacidade='operar_pdv',defaults={'permitido':allowed})
    def payload(self):
        claims={'organization':str(self.a.public_id),'user':self.operator.pk,'session':str(self.session.public_id),'depot':self.depot.pk}
        return {**claims,'request_id':str(uuid.uuid4()),'device':str(uuid.uuid4()),'grant':signing.dumps(claims,salt=off.SALT,compress=True),'items':[{'sku':self.part.sku,'quantity':'1','unit_price':'10.00','discount':'0.00'}],'discount':'0.00','reason':'','payments':[{'forma':self.cash_method.pk,'valor':'10.00','recebido':'12.00'}]}

class SplitPWATests(SplitPWAData,TestCase):
    def setUp(self):self.setup_split()
    def test_vendor_default_does_not_operate_cash_even_with_legacy_override(self):
        with tenant_context(self.a):
            PermissaoMembership.objects.create(membership=self.member,capacidade='pdv',permitido=True)
            self.assertFalse(has_capability(self.seller,'pdv'))
            self.assertFalse(has_capability(self.seller,'operar_pdv'))
            with self.assertRaises(PermissionDenied):c.open_cash(self.seller,self.cash.pk,0,uuid.uuid4())
        self.client.force_login(self.seller)
        for url in ['/pdv/','/pdv/offline/','/pdv/historico/','/pdv/offline/operar/','/pdv/offline/contexto/']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.post('/pdv/sincronizacao/',json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_explicit_capability_grants_only_pdv_not_finance_admin(self):
        with tenant_context(self.a):self.grant()
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get('/pdv/').status_code,200)
        self.assertEqual(self.client.get('/financeiro/').status_code,403)
        self.assertEqual(self.client.get('/contas/usuarios/').status_code,403)
        with tenant_context(self.a):self.grant(False)
        self.assertEqual(self.client.get('/pdv/').status_code,403)
    def test_vendor_ui_excludes_pdv_even_when_granted(self):
        self.client.force_login(self.seller)
        for allowed in [False,True]:
            with tenant_context(self.a):self.grant(allowed)
            response=self.client.get('/vendedor/')
            self.assertContains(response,'VERTYX VENDEDOR')
            for forbidden in ['href="/pdv/"','Abrir PDV','Abrir meu caixa','Fechar caixa','href="/financeiro/"']:
                self.assertNotContains(response,forbidden)
            self.assertContains(response,'href="/vendedor/ponto/"')
            self.assertContains(response,'href="/vendedor/manifest.webmanifest"')
    def test_independent_pdv_menu_does_not_contain_vendor_home(self):
        response=self.client.get('/pdv/')
        self.assertContains(response,'href="/pdv/manifest.webmanifest"')
        self.assertContains(response,'href="/pdv/offline/"')
        self.assertNotContains(response,'href="/vendedor/"')
    def test_cash_capacity_does_not_depend_on_personal_seller_central(self):
        with tenant_context(self.a):
            member=OrganizationMembership.objects.get(user=self.operator,organization=self.a)
            PermissaoMembership.objects.create(membership=member,capacidade='central_vendedor',permitido=False)
            sale,item=self.sale()
        self.assertEqual(self.client.get('/vendedor/').status_code,403)
        self.assertEqual(self.client.get('/pdv/').status_code,200)
        self.assertEqual(self.client.get(f'/pdv/vendas/{sale.public_id}/').status_code,200)
    def test_vendor_central_survives_disabled_cash_module(self):
        with tenant_context(self.a):ModuloOrganizacao.objects.create(codigo='pdv',habilitado=False)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get('/vendedor/').status_code,200)
        self.assertEqual(self.client.get('/pdv/').status_code,403)
    def test_manifest_scopes_start_urls_workers_are_independent_and_public(self):
        self.client.logout()
        for app,name in [('pdv','VERTYX PDV'),('vendedor','VERTYX Vendedor')]:
            response=self.client.get(f'/{app}/manifest.webmanifest');data=response.json()
            self.assertEqual((data['id'],data['scope'],data['start_url'],data['name']),(f'/{app}/',f'/{app}/',f'/{app}/',name))
            worker=self.client.get(f'/{app}/sw.js')
            self.assertEqual(worker.status_code,200);self.assertEqual(worker['Service-Worker-Allowed'],f'/{app}/')
            self.assertNotIn("cache.put",worker.content.decode())
        self.assertEqual(self.client.get('/manifest.webmanifest').json()['id'],'/tecnico/')
    def test_scoped_login_enters_expected_app_without_separate_accounts(self):
        self.operator.set_password('synthetic-split');self.operator.save()
        self.client.logout()
        self.assertRedirects(self.client.get('/pdv/'),'/pdv/entrar/?next=/pdv/')
        self.assertRedirects(self.client.post('/pdv/entrar/',{'username':self.operator.username,'password':'synthetic-split'}),'/pdv/')
        self.client.logout()
        self.assertRedirects(self.client.post('/vendedor/entrar/',{'username':self.operator.username,'password':'synthetic-split'}),'/vendedor/')
    def test_vendor_own_sale_read_only_without_cash_permission(self):
        with tenant_context(self.a):sale=c.new_sale(self.admin,self.session.public_id,self.depot.pk,seller_id=self.seller.pk)
        self.client.force_login(self.seller);url=f'/vendedor/vendas/{sale.public_id}/'
        self.assertContains(self.client.get(url),str(sale));self.assertEqual(self.client.post(url,{'action':'cancelar'}).status_code,405)
        self.assertEqual(self.client.get(f'/pdv/vendas/{sale.public_id}/').status_code,403)
        self.client.force_login(self.operator);self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.admin_b);self.assertEqual(self.client.get(url).status_code,404)
    def test_impact_command_is_read_only_and_reports_vendor_cash_history(self):
        with tenant_context(self.a):
            self.grant();cash=m.ContaBancaria.objects.create(nome='Caixa vendedor sintético',tipo='CAIXA');session=c.open_cash(self.seller,cash.pk,0,uuid.uuid4())
            before=list(m.SessaoCaixa.objects.values());perms=list(PermissaoMembership.objects.values())
        output=StringIO();call_command('auditar_operadores_pdv',organization=self.a.slug,stdout=output)
        data=json.loads(output.getvalue());self.assertEqual(data['vendedores_afetados'][0]['usuario'],self.seller.username)
        with tenant_context(self.a):self.assertEqual(list(m.SessaoCaixa.objects.values()),before);self.assertEqual(list(PermissaoMembership.objects.values()),perms)

class OfflinePDVTests(SplitPWAData,TestCase):
    def setUp(self):self.setup_split()
    def submit(self,data):return self.client.post('/pdv/sincronizacao/',json.dumps(data),content_type='application/json')
    def test_prepare_snapshot_read_only_own_cash_products_payments(self):
        with tenant_context(self.a):before=list(m.SessaoCaixa.objects.values());sales=m.Venda.objects.count()
        response=self.client.get('/pdv/offline/preparar/',{'caixa':self.session.public_id,'deposito':self.depot.pk})
        self.assertEqual(response.status_code,200);data=response.json()
        self.assertEqual(data['organization'],str(self.a.public_id));self.assertEqual(data['user'],self.operator.pk)
        self.assertEqual(data['catalog'][0]['price'],'10.00');self.assertNotIn('CREDIARIO',[f['kind'] for f in data['forms']])
        with tenant_context(self.a):self.assertEqual(list(m.SessaoCaixa.objects.values()),before);self.assertEqual(m.Venda.objects.count(),sales)
    def test_prepare_rejects_other_operator_and_foreign_depot(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/pdv/offline/preparar/',{'caixa':self.session.public_id,'deposito':self.depot.pk}).status_code,403)
        self.client.force_login(self.operator)
        with tenant_context(self.b):foreign_depot=m.Deposito.objects.create(nome='Outro tenant')
        self.assertEqual(self.client.get('/pdv/offline/preparar/',{'caixa':self.session.public_id,'deposito':foreign_depot.pk}).status_code,400)
    def test_mixed_payment_fefo_decimal_and_immutable_sync_receipt(self):
        with tenant_context(self.a):
            early=self.incoming(1,7,'2.25');late=self.incoming(2,60,'7.33')
            data=self.payload();data['items'][0]['quantity']='2';data['payments']=[{'forma':self.cash_method.pk,'valor':'8.00','recebido':'10.00'},{'forma':self.pix.pk,'valor':'12.00'}]
        response=self.submit(data);self.assertEqual(response.status_code,200,response.content)
        with tenant_context(self.a):
            receipt=m.SincronizacaoPDV.objects.get();sale=receipt.venda;self.assertEqual(sale.conta.saldo,0)
            self.assertEqual(sale.itens.get().custo_total,Decimal('9.58'))
            self.assertEqual([r['id'] for r in sale.snapshot['itens'][0]['lotes']],[early.pk,late.pk])
            self.assertEqual(sale.pagamentos_pdv.get(forma=self.cash_method).troco,2)
            with self.assertRaises(ValidationError):receipt.payload_hash='change';receipt.save()
    def test_lost_response_retry_does_not_duplicate_after_cash_closed(self):
        with tenant_context(self.a):self.incoming(2);data=self.payload()
        first=self.submit(data);self.assertEqual(first.status_code,200,first.content)
        with tenant_context(self.a):c.close_cash(self.operator,self.session.public_id,10)
        second=self.submit(data);self.assertEqual(first.json(),second.json())
        with tenant_context(self.a):self.assertEqual((m.Venda.objects.count(),m.SincronizacaoPDV.objects.count(),m.Pagamento.objects.count()),(1,1,1));self.session.refresh_from_db();self.assertIsNotNone(self.session.fechado_em)
    def test_same_uuid_changed_payload_rejected_without_altering_confirmed_sale(self):
        with tenant_context(self.a):self.incoming(2);data=self.payload()
        self.assertEqual(self.submit(data).status_code,200);data['reason']='modified'
        self.assertEqual(self.submit(data).status_code,409)
        with tenant_context(self.a):self.assertEqual(m.Venda.objects.count(),1)
    def test_stock_conflict_rolls_back_all_financial_and_stock_operations(self):
        response=self.submit(self.payload());self.assertEqual(response.status_code,409)
        with tenant_context(self.a):self.assertEqual((m.Venda.objects.count(),m.Pagamento.objects.count(),m.SincronizacaoPDV.objects.count(),g.Lancamento.objects.count()),(0,0,0,0))
    def test_price_conflict_and_expired_lot_rejected(self):
        with tenant_context(self.a):self.incoming(2,1);data=self.payload();self.part.refresh_from_db();self.part.preco_venda=Decimal('11');self.part.save()
        self.assertEqual(self.submit(data).status_code,409)
        with tenant_context(self.a):self.part.refresh_from_db();self.part.preco_venda=Decimal('10');self.part.save()
        with patch('django.utils.timezone.localdate',return_value=self.today+__import__('datetime').timedelta(days=3)):
            self.assertEqual(self.submit(data).status_code,409)
    def test_closed_cash_never_reopens(self):
        with tenant_context(self.a):self.incoming(1);data=self.payload();c.close_cash(self.operator,self.session.public_id,0);before=list(m.SessaoCaixa.objects.values())
        self.assertEqual(self.submit(data).status_code,409)
        with tenant_context(self.a):self.assertEqual(list(m.SessaoCaixa.objects.values()),before);self.assertEqual(m.Venda.objects.count(),0)
    def test_wrong_user_organization_and_tampered_signed_grant(self):
        data=self.payload()
        for name,value,status in [('organization',str(self.b.public_id),403),('user',self.admin.pk,403),('grant','invalid',409)]:
            row=copy.deepcopy(data);row[name]=value;self.assertEqual(self.submit(row).status_code,status)
        self.client.force_login(self.admin);self.assertEqual(self.submit(data).status_code,403)
        self.client.force_login(self.admin_b);self.assertEqual(self.submit(data).status_code,403)
    def test_grant_expiry_preserves_no_server_side_partial_records(self):
        with tenant_context(self.a),patch('operacao.pdv_offline.signing.loads',side_effect=signing.SignatureExpired()):
            with self.assertRaises(ValidationError):off.accept(self.operator,self.payload())
        with tenant_context(self.a):self.assertEqual(m.Venda.objects.count(),0)
    def test_revoked_capability_rejects_prepared_intent(self):
        with tenant_context(self.a):
            member=OrganizationMembership.objects.get(user=self.operator,organization=self.a);PermissaoMembership.objects.create(membership=member,capacidade='operar_pdv',permitido=False)
        self.assertEqual(self.submit(self.payload()).status_code,403)
    def test_invalid_payment_discount_and_quantity_rejected_atomically(self):
        with tenant_context(self.a):self.incoming(3)
        for mutation in ['payment','discount','quantity','credit']:
            data=self.payload()
            if mutation=='payment':data['payments'][0]['valor']='9.99'
            elif mutation=='quantity':data['items'][0]['quantity']='0'
            elif mutation=='credit':data['payments'][0]['forma']=self.credit.pk
            else:data['discount']='9.00';data['reason']='forged';data['payments'][0]['valor']='1.00'
            with self.subTest(mutation=mutation):self.assertIn(self.submit(data).status_code,[403,409])
        with tenant_context(self.a):self.assertEqual(m.Venda.objects.count(),0)
    def test_bad_json_and_csrf_enforced(self):
        self.assertEqual(self.client.post('/pdv/sincronizacao/','{',content_type='application/json').status_code,409)
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.operator)
        self.assertEqual(client.post('/pdv/sincronizacao/',json.dumps(self.payload()),content_type='application/json').status_code,403)

@skipUnless(connection.vendor=='postgresql','Concurrency uses PostgreSQL locks')
class OfflineConcurrencyTests(SplitPWAData,TransactionTestCase):
    def setUp(self):self.setup_split()
    def test_parallel_duplicate_submission_confirms_one_sale(self):
        with tenant_context(self.a):self.incoming(3);data=self.payload()
        def run(_):
            close_old_connections()
            try:
                with tenant_context(self.a):return off.accept(self.operator,data).pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(run,range(2)))
        self.assertEqual(ids[0],ids[1])
        with tenant_context(self.a):self.assertEqual((m.Venda.objects.count(),m.SincronizacaoPDV.objects.count(),m.Pagamento.objects.count()),(1,1,1))

class OfflineMigrationPreservationTests(SplitPWAData,TransactionTestCase):
    def test_0018_adds_only_sync_receipt_without_changing_existing_tables_or_rows(self):
        from django.db.migrations.executor import MigrationExecutor
        from django.conf import settings
        self.assertEqual(settings.DATABASES['default']['HOST'],'127.0.0.1')
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        executor=MigrationExecutor(connection)
        self.setup_split()
        with tenant_context(self.a):self.incoming(2);sale,item=self.sale();self.paid(sale)
        executor.migrate([('operacao','0017_seller_central')])
        try:
            tables=set(connection.introspection.table_names())-{'django_migrations'}
            def snapshot():
                result={}
                with connection.cursor() as cursor:
                    for table in sorted(tables):
                        cursor.execute('SELECT * FROM '+connection.ops.quote_name(table))
                        result[table]=sorted(repr(row) for row in cursor.fetchall())
                return result
            before=snapshot()
            MigrationExecutor(connection).migrate([('operacao','0018_pdv_offline_sync')])
            self.assertEqual(snapshot(),before)
            self.assertEqual(set(connection.introspection.table_names())-tables-{'django_migrations'},{'operacao_sincronizacaopdv'})
        finally:
            executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
