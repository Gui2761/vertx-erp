import re
import uuid
from pathlib import Path
from PIL import Image
from django.conf import settings
from django.test import TestCase
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership, MembershipERP
from .test_block3_commerce import CommerceData
from . import models as m, commerce as c


class AdministrativePDVTests(CommerceData,TestCase):
    def setUp(self):
        self.setup_commerce()
        self.client.force_login(self.admin)

    def test_admin_and_gestor_modules_are_ordered_and_collapsed_on_every_page(self):
        expected=['Financeiro','PDV','Vendas','Estoque','Compras','RH','Relatórios','Configurações','Operacional']
        for user in [self.admin,self.users['GESTOR']]:
            self.client.force_login(user)
            for url in ['/assistencia/','/vertyx/']:
                response=self.client.get(url)
                self.assertEqual(response.status_code,200)
                html=response.content.decode()
                groups=re.findall(r'<details class="vx-module"([^>]*)><summary>(.*?)</summary>',html)
                self.assertEqual([label for attrs,label in groups],expected)
                self.assertTrue(all('open' not in attrs for attrs,label in groups))
                self.assertContains(response,'href="/pdv/"')
                self.assertNotContains(response,'VERTYX | ASSISTÊNCIA')
                self.assertContains(response,'/rh/horas-extras/')

    def test_admin_terminal_reuses_open_cash_without_get_writes(self):
        with tenant_context(self.a):
            cash=m.ContaBancaria.objects.create(nome='OKOK sintético',tipo='CAIXA')
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

    def test_admin_can_open_professional_draft_and_keep_legacy_management(self):
        with tenant_context(self.a):
            sale=c.new_sale(self.admin,self.session.public_id,self.depot.pk)
        response=self.client.get(f'/pdv/vendas/{sale.public_id}/')
        self.assertTemplateUsed(response,'operacao/seller_pdv.html')
        self.assertContains(response,'Resumo da venda')
        self.assertContains(response,'css/seller.css')
        self.assertContains(response,'data-connection-status')
        self.assertTemplateUsed(self.client.get('/pdv/?gestao=1'),'operacao/pdv_home.html')
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

    def test_seller_cannot_use_administrative_cash_management(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get('/pdv/?gestao=1').status_code,403)
        self.assertTemplateUsed(self.client.get('/pdv/'),'operacao/seller_terminal.html')
        self.assertNotContains(self.client.get('/pdv/'),'Gestão de caixas')

    def test_technician_navigation_and_pwa_identity_are_preserved(self):
        self.client.force_login(self.users['TECNICO'])
        response=self.client.get('/tecnico/')
        self.assertNotContains(response,'vx-module')
        self.assertNotContains(response,'Central do PDV')
        self.assertContains(response,'Atalhos do técnico')
        self.assertContains(response,'href="/manifest.webmanifest"')
        self.assertEqual(self.client.get('/pdv/').status_code,403)
        manifest=self.client.get('/manifest.webmanifest').json()
        self.assertEqual((manifest['id'],manifest['start_url']),('/tecnico/','/vertyx/'))

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
