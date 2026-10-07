import io
import re
import tempfile
import uuid
from html.parser import HTMLParser
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from clientes.models import Cliente, Unidade
from equipamentos.models import Equipamento
from contas.models import Tecnico
from ordens.models import OrdemServico, TecnicoAuxiliar
from ordens import services as os_services
from ordens.views import token_conferencia
from gestao import models as g, services as gs
from platform_core.context import tenant_context
from platform_core.models import OrganizationMembership, MembershipERP, PermissaoMembership
from platform_core.tests import sample_signature
from .test_block2 import Block2Fixtures
from . import models as m, contract_workday as w, permissions


class NavigationLinks(HTMLParser):
    """Read actual server-rendered links, independent of CSS or JavaScript."""
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = {'href': dict(attrs).get('href'), 'text': ''}
            self.links.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a':
            self.current = None


class TechnicianPWATests(Block2Fixtures, TestCase):
    def setUp(self):
        self.setup_operations()
        self.tech = self.users['TECNICO']
        for user in [self.tech, self.admin]:
            user.set_password('synthetic-local-test-only'); user.save()
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=self.directory.name)
        override.enable(); self.addCleanup(override.disable)
        with tenant_context(self.a):
            self.other_user = self.user('other-mobile', self.a, 'TECNICO')
            customer=Cliente.objects.create(nome_razao_social='CLIENTE RESTRITO MOBILE',cpf_cnpj='OUTRO-DOC')
            unit=Unidade.objects.create(cliente=customer,nome='UNIDADE RESTRITA')
            equipment=Equipamento.objects.create(nome='EQUIPAMENTO RESTRITO MOBILE',cliente=customer,unidade=unit,categoria=self.da['equipment'].categoria)
            tech=Tecnico.objects.create(nome='OUTRO TECNICO',usuario=self.other_user)
            order=OrdemServico.objects.create(cliente=customer,unidade=unit,equipamento=equipment,tecnico=tech,defeito='RESTRITO')
            self.other={'customer':customer,'unit':unit,'equipment':equipment,'tech':tech,'order':order}
            self.call = m.Chamado.objects.create(criado_por=self.admin,cliente=self.da['customer'],unidade=self.da['unit'],equipamento=self.da['equipment'],tecnico=self.da['tech'],titulo='MEU CHAMADO MOBILE',descricao='Atendimento sintético')
            self.other_call=m.Chamado.objects.create(criado_por=self.admin,cliente=self.other['customer'],unidade=self.other['unit'],equipamento=self.other['equipment'],tecnico=self.other['tech'],titulo='CHAMADO RESTRITO',descricao='Não divulgar')
        self.client.force_login(self.tech)

    def url(self, name, *args):
        return reverse(name, args=args)

    def menu_html(self, response):
        return response.content.decode().split('id="menuPrincipal">', 1)[1].split('</div>', 1)[0]

    def test_technician_menu_is_operational_in_server_html_not_css_hiding(self):
        response = self.client.get(self.url('operacao:tecnico'))
        menu = self.menu_html(response)
        self.assertEqual(
            [(link['href'], link['text'].strip()) for link in NavigationLinks(menu).links],
            [('/tecnico/', 'Meu atendimento / Atender'), ('/planejamento/', 'Minha agenda'),
             ('/ordens/', 'Minhas OS'), ('/chamados/', 'Meus chamados'),
             ('/tecnico/qr/', 'Ler QR / código'), ('/ponto/', 'Meu ponto'),
             ('/notificacoes/', 'Alertas / notificações'), ('/conhecimento/', 'Conhecimento técnico')],
        )
        self.assertIn('Sair', menu)
        for text in ['Voltar para VERTYX', 'Recolher menu', 'Painel', 'Clientes', 'Equipamentos',
                     'Peças e Estoque', 'Orçamentos', 'Contratos', 'Financeiro', 'Relatórios',
                     'Compras', 'Vendas', 'Fiscal', 'Usuários', 'Configurações', 'Trocar organização',
                     'disabled', 'aria-disabled', 'display:none', 'display: none']:
            with self.subTest(text=text):
                self.assertNotIn(text, menu)
        self.assertIsNone(response.context.get('executive_navigation'))

    def test_menu_omits_operational_links_when_capability_is_denied(self):
        with tenant_context(self.a):
            member = OrganizationMembership.objects.get(user=self.tech, organization=self.a)
            for capability in ['ponto', 'operacional']:
                PermissaoMembership.objects.create(membership=member, capacidade=capability, permitido=False)
        response = self.client.get(self.url('operacao:tecnico'))
        links = {link['href'] for link in NavigationLinks(self.menu_html(response)).links}
        self.assertNotIn('/ponto/', links)
        self.assertNotIn('/conhecimento/', links)
        self.assertNotIn('/chamados/', links)
        for path in ['/ponto/', '/conhecimento/', '/chamados/']:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_admin_and_manager_menus_keep_complete_existing_navigation(self):
        for user in [self.admin, self.users['GESTOR']]:
            self.client.force_login(user)
            menu = self.menu_html(self.client.get(self.url('core:painel')))
            links = {link['href'] for link in NavigationLinks(menu).links}
            for path in ['/vertyx/', '/assistencia/', '/planejamento/', '/clientes/',
                         '/equipamentos/', '/estoque/', '/orcamentos/', '/contratos/',
                         '/financeiro/', '/relatorios/', '/compras/', '/vendas/', '/pdv/']:
                self.assertIn(path, links)
            self.assertIn('Voltar para VERTYX', menu)
            if user == self.admin:
                self.assertIn('/contas/usuarios/', links)
                self.assertIn('/configuracoes/', links)

    def test_logo_and_all_breadcrumb_links_keep_technician_in_technical_home(self):
        for name in ['operacao:tecnico', 'ordens:lista', 'operacao:chamado_lista',
                     'operacao:calendario', 'operacao:notificacoes']:
            html = self.client.get(self.url(name)).content.decode()
            brand = re.search(r'<a class="navbar-brand".*?</a>', html, re.S).group()
            breadcrumb = re.search(r'<nav class="vx-breadcrumb".*?</nav>', html, re.S).group()
            for link in NavigationLinks(brand + breadcrumb).links:
                self.assertEqual(link['href'], '/tecnico/')
                clicked = self.client.get(link['href'], follow=True)
                self.assertEqual(clicked.request['PATH_INFO'], '/tecnico/')
            self.assertNotIn('href="/vertyx/"', html)
            self.assertNotIn('href="/assistencia/"', html)
        # Previously saved/admin-oriented navigation remains guarded on the server.
        for name in ['platform_core:home', 'core:painel']:
            response = self.client.get(self.url(name), follow=True)
            self.assertEqual(response.request['PATH_INFO'], '/tecnico/')
        self.assertEqual(self.client.get('/vertyx/empresa/').status_code, 403)
        self.assertEqual(self.client.get('/financeiro/').status_code, 403)

    def test_organization_selection_uses_operational_wording_and_direct_destination(self):
        response = self.client.get(self.url('platform_core:home'), {'organizacoes': '1'})
        self.assertContains(response, 'Acessar meus atendimentos')
        self.assertNotContains(response, 'Entrar no ERP Assistência')
        self.assertNotContains(response, 'href="/assistencia/"')
        self.assertRedirects(self.client.post(self.url('platform_core:select_organization'),
                            {'organization': str(self.a.public_id)}), '/tecnico/')

    def test_organization_selection_does_not_grant_disabled_erp_access(self):
        member = OrganizationMembership.objects.get(user=self.tech, organization=self.a)
        MembershipERP.objects.filter(membership=member).update(enabled=False)
        self.assertRedirects(self.client.post(self.url('platform_core:select_organization'),
                            {'organization': str(self.a.public_id)}), self.url('platform_core:home'))
        self.assertEqual(self.client.get('/tecnico/').status_code, 403)
        response = self.client.get(self.url('platform_core:home'), {'organizacoes': '1'})
        self.assertNotContains(response, 'Acessar meus atendimentos')
        self.assertEqual(NavigationLinks(self.menu_html(response)).links, [])

    def test_bottom_navigation_has_four_authorized_operational_destinations(self):
        html = self.client.get('/tecnico/').content.decode()
        bottom = re.search(r'<nav class="vx-bottom".*?</nav>', html, re.S).group()
        links = NavigationLinks(bottom).links
        self.assertEqual([(link['href'], link['text']) for link in links],
                         [('/tecnico/', 'Atender'), ('/planejamento/', 'Agenda'),
                          ('/ordens/', 'OS'), ('/notificacoes/', 'Alertas')])
        for link in links:
            self.assertEqual(self.client.get(link['href']).status_code, 200)

    def test_seller_organization_home_still_routes_to_pdv(self):
        seller = self.user('seller-navigation', self.a, 'VENDEDOR')
        self.client.force_login(seller)
        self.assertRedirects(self.client.get(self.url('platform_core:home')),
                             self.url('operacao:seller_home'), fetch_redirect_response=False)
        response = self.client.get(self.url('platform_core:home'), {'organizacoes': '1'})
        self.assertContains(response, 'href="/vendedor/"')
        self.assertNotContains(response, 'Acessar meus atendimentos')

    def test_real_login_uses_membership_role_even_with_admin_global_profile(self):
        self.client.logout()
        response=self.client.post(self.url('contas:login')+'?next=/financeiro/',{'username':self.tech.username,'password':'synthetic-local-test-only'})
        self.assertRedirects(response,self.url('operacao:tecnico'))
        self.assertEqual(self.tech.perfil,'ADMIN')

    def test_home_panel_and_root_route_to_operational_home(self):
        response=self.client.get('/',follow=True)
        self.assertEqual(response.request['PATH_INFO'],self.url('operacao:tecnico'))
        for url in [self.url('platform_core:home'),self.url('core:painel')]:
            self.assertRedirects(self.client.get(url),self.url('operacao:tecnico'),fetch_redirect_response=False)
        response=self.client.get(self.url('operacao:tecnico'))
        for title in ['Meus atendimentos hoje','Meus chamados','Minhas Ordens de Serviço','Próximos atendimentos','Atendimentos atrasados']:
            self.assertContains(response,title)
        for url in ['/financeiro/','/bancos/','/compras/','/contas/usuarios/','/configuracoes/','/vendas/','/gestao/executiva/']:
            self.assertNotContains(response,'href="'+url+'"')
        self.assertEqual(response['Cache-Control'],'private, no-store')

    def test_assigned_calls_and_orders_only(self):
        for url in [self.url('operacao:tecnico'),self.url('operacao:chamado_lista')]:
            response=self.client.get(url)
            self.assertContains(response,self.call.titulo)
            self.assertNotContains(response,self.other_call.titulo)
        response=self.client.get(self.url('ordens:lista'))
        self.assertContains(response,self.da['order'].numero)
        self.assertNotContains(response,self.other['order'].numero)
        self.assertEqual(self.client.get(self.url('ordens:detalhe',self.other['order'].pk)).status_code,403)
        self.assertEqual(self.client.get(self.url('operacao:chamado_detalhe',self.other_call.pk)).status_code,404)

    def test_auxiliary_assignment_is_authorized_without_showing_other_orders(self):
        with tenant_context(self.a):
            TecnicoAuxiliar.objects.create(ordem=self.other['order'],tecnico=self.da['tech'])
        self.assertContains(self.client.get(self.url('ordens:lista')),self.other['order'].numero)
        self.assertEqual(self.client.get(self.url('ordens:detalhe',self.other['order'].pk)).status_code,200)

    def test_administrative_urls_get_and_post_denied_even_with_capability_override(self):
        with tenant_context(self.a):
            membership=OrganizationMembership.objects.get(user=self.tech,organization=self.a)
            for capability in ['financeiro','compras','estoque_escrever','config_empresa']:
                PermissaoMembership.objects.create(membership=membership,capacidade=capability,permitido=True)
        urls=['/financeiro/','/financeiro/lancamentos/','/bancos/','/fiscal/','/compras/','/vendas/','/pdv/','/relatorios/','/contas/usuarios/','/contas/tecnicos/','/configuracoes/','/vertyx/empresa/','/vertyx/empresa/permissoes/','/estoque/','/estoque/lotes/','/admin/','/gestao/executiva/','/contratos/jornadas/']
        for url in urls:
            for method in [self.client.get,self.client.post]:
                with self.subTest(url=url,method=method.__name__):
                    response=method(url)
                    self.assertEqual(response.status_code,403)
                    self.assertEqual(response['Cache-Control'],'private, no-store')

    def test_admin_and_manager_keep_complete_erp(self):
        for user in [self.admin,self.users['GESTOR']]:
            self.client.force_login(user)
            for name in ['core:painel','gestao:financeiro','operacao:compra_lista','operacao:venda_lista','gestao:relatorios']:
                self.assertEqual(self.client.get(self.url(name)).status_code,200,name)
            self.assertRedirects(self.client.get(self.url('operacao:tecnico')),self.url('core:painel'))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url('contas:usuario_list')).status_code,200)
        self.assertEqual(self.client.get(self.url('operacao:configuracao')).status_code,200)

    def test_logout_login_switch_changes_experience_and_never_caches_authenticated_html(self):
        self.assertContains(self.client.get(self.url('operacao:tecnico')),'ASSISTÊNCIA EM CAMPO')
        response=self.client.post(self.url('contas:logout'))
        self.assertEqual(response['Cache-Control'],'private, no-store')
        response=self.client.post(self.url('contas:login'),{'username':self.admin.username,'password':'synthetic-local-test-only'})
        self.assertRedirects(response,self.url('platform_core:home'))
        self.assertEqual(self.client.get(self.url('gestao:financeiro')).status_code,200)
        self.client.post(self.url('contas:logout'))
        self.client.post(self.url('contas:login'),{'username':self.tech.username,'password':'synthetic-local-test-only'})
        self.assertEqual(self.client.get(self.url('gestao:financeiro')).status_code,403)

    def test_organization_switch_recomputes_role_without_trusting_previous_session(self):
        member=OrganizationMembership.objects.create(user=self.tech,organization=self.b,role='GESTOR')
        MembershipERP.objects.create(membership=member,erp=self.erp)
        self.assertRedirects(self.client.post(self.url('platform_core:select_organization'),{'organization':str(self.b.public_id)}),self.url('platform_core:home'))
        self.assertEqual(self.client.get(self.url('gestao:financeiro')).status_code,200)
        manager_menu = self.menu_html(self.client.get(self.url('core:painel')))
        self.assertIn('href="/financeiro/"', manager_menu)
        self.assertIn('Voltar para VERTYX', manager_menu)
        self.assertRedirects(self.client.post(self.url('platform_core:select_organization'),{'organization':str(self.a.public_id)}), '/tecnico/')
        self.assertRedirects(self.client.get(self.url('platform_core:home')),self.url('operacao:tecnico'))
        self.assertEqual(self.client.get(self.url('gestao:financeiro')).status_code,403)
        technician_menu = self.menu_html(self.client.get('/tecnico/'))
        self.assertNotIn('href="/financeiro/"', technician_menu)
        self.assertNotIn('Voltar para VERTYX', technician_menu)
        self.assertIn('Minha agenda', technician_menu)

    def test_cross_organization_order_equipment_customer_and_call_denied(self):
        with tenant_context(self.b):
            call=m.Chamado.objects.create(criado_por=self.admin_b,cliente=self.db['customer'],tecnico=self.db['tech'],titulo='OTHER TENANT',descricao='Teste de isolamento')
        for name,pk in [('ordens:detalhe',self.db['order'].pk),('equipamentos:equipamento_detail',self.db['equipment'].pk),('clientes:cliente_detail',self.db['customer'].pk),('operacao:chamado_detalhe',call.pk)]:
            self.assertEqual(self.client.get(self.url(name,pk)).status_code,404,name)

    def test_customer_unit_equipment_scope_and_qr_are_not_global(self):
        for name,key in [('clientes:cliente_detail','customer'),('equipamentos:equipamento_detail','equipment')]:
            self.assertEqual(self.client.get(self.url(name,self.da[key].pk)).status_code,200)
            self.assertEqual(self.client.get(self.url(name,self.other[key].pk)).status_code,404)
        for name,key in [('clientes:cliente_list','customer'),('equipamentos:equipamento_list','equipment')]:
            self.assertNotContains(self.client.get(self.url(name)),str(self.other[key]))
        self.assertEqual(self.client.get(self.url('equipamentos:equipamento_qr',self.other['equipment'].codigo_publico)).status_code,404)

    def test_only_valid_os_can_open_piece_form_and_consume_fefo(self):
        with tenant_context(self.a):
            later=self.incoming(2,days=60,cost=9)
            first=self.incoming(2,days=7,cost=3)
        url=self.url('gestao:movimentar')
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.get(url,{'ordem':self.other['order'].pk}).status_code,403)
        response=self.client.get(url,{'ordem':self.da['order'].pk})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['form'].fields['tipo'].choices,[('OS','Utilização em OS'),('DEVOLUCAO','Devolução da OS')])
        response=self.client.post(url,{'ordem':self.da['order'].pk,'tipo':'OS','peca':self.part.pk,'quantidade':'1','origem':self.depot.pk,'request_id':str(uuid.uuid4())})
        self.assertRedirects(response,self.url('ordens:detalhe',self.da['order'].pk))
        with tenant_context(self.a):
            first.refresh_from_db();later.refresh_from_db()
            self.assertEqual((first.quantidade,later.quantidade),(Decimal('1'),Decimal('2')))

    def test_stock_override_cannot_allow_administrative_movement(self):
        with tenant_context(self.a):
            membership=OrganizationMembership.objects.get(user=self.tech,organization=self.a)
            PermissaoMembership.objects.create(membership=membership,capacidade='estoque_escrever',permitido=True)
            with self.assertRaises(PermissionDenied):
                gs.movimentar(self.tech,self.part.pk,'ENTRADA',1,destino_id=self.depot.pk)
        response=self.client.post(self.url('gestao:movimentar'),{'ordem':self.da['order'].pk,'tipo':'ENTRADA','peca':self.part.pk,'quantidade':'1','request_id':str(uuid.uuid4())})
        self.assertEqual(response.status_code,400)

    def test_contract_gate_remains_until_technician_starts_activity(self):
        with tenant_context(self.a):
            contract=g.Contrato.objects.create(numero='MOBILE',cliente=self.da['customer'],data_inicial=self.today,data_final=self.today+timezone.timedelta(days=10),valor=0)
            g.ContratoEquipamento.objects.create(contrato=contract,equipamento=self.da['equipment'])
            order=self.da['order'];order.contrato=contract;order.save()
            w.Config.objects.create(contrato=contract,habilitada=True,exigir_inicio=True,tarifas={'Assistência técnica':'10.00'})
            self.call.ordem=order;gs.write(self.call)
            gs.audit(self.admin,'CHAMADO_CONVERTIDO',self.call,{'ordem':order.pk})
        self.assertEqual(self.client.get(self.url('ordens:detalhe',order.pk)).status_code,403)
        self.assertContains(self.client.get(self.url('operacao:tecnico')),'INICIAR ATIVIDADE DO DIA')
        self.assertNotContains(self.client.get(self.url('operacao:tecnico')),self.call.titulo)
        self.assertEqual(self.client.get(self.url('operacao:chamado_detalhe',self.call.pk)).status_code,404)
        response=self.client.post(self.url('operacao:contract_activity',order.pk),{'acao':'INICIO','categoria':'Assistência técnica','resultado':'NEGADA'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get(self.url('ordens:detalhe',order.pk)).status_code,200)

    def test_existing_mobile_flow_geo_photos_diagnosis_signature_and_pdf(self):
        order=self.da['order']
        self.assertEqual(self.client.post(self.url('ordens:iniciar',order.pk),{'resultado':'NEGADA'}).status_code,302)
        order.refresh_from_db()
        response=self.client.post(self.url('ordens:editar',order.pk),{'revisao':order.revisao,'diagnostico':'DIAGNOSTICO MOBILE','servico_executado':'SERVICO MOBILE','condicao_final':'OK','observacoes':'Teste em campo'})
        self.assertEqual(response.status_code,302)
        raw=io.BytesIO();Image.new('RGB',(16,16),'white').save(raw,format='PNG')
        for category in ['ANTES','DEPOIS']:
            response=self.client.post(self.url('ordens:foto_adicionar',order.pk),{'categoria':category,'descricao':'FOTO MOBILE','arquivo':SimpleUploadedFile('teste.png',raw.getvalue(),content_type='image/png')})
            self.assertEqual(response.status_code,302)
        response=self.client.post(self.url('ordens:preparar',order.pk),{'resultado':'NEGADA'})
        self.assertEqual(response.status_code,302)
        response=self.client.get(response['Location'])
        self.assertEqual(response.status_code,200)
        token=response.context['form']['token'].value()
        response=self.client.post(self.url('ordens:finalizar',order.pk),{'token':token,'nome':'RESPONSAVEL TESTE','cargo':'Teste','imagem':sample_signature(),'imagem_tecnico':sample_signature(),'confirmacao':True})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.a):
            order.refresh_from_db();self.assertEqual(order.status,'FINALIZADA')
            signature=order.assinaturas.get();self.assertEqual(order.fotos.count(),2)
        response=self.client.get(self.url('ordens:pdf',order.pk,signature.pk))
        self.assertEqual(response.status_code,200)
        content=b''.join(response.streaming_content) if response.streaming else response.content
        self.assertTrue(content.startswith(b'%PDF'))

    def test_document_and_upload_choices_obey_client_scope(self):
        with tenant_context(self.a):
            doc=m.Documento.objects.create(enviado_por=self.admin,titulo='OUTRO DOCUMENTO',tipo='PDF',cliente=self.other['customer'],arquivo='synthetic.pdf')
            self.assertFalse(permissions.document_allowed(self.tech,doc))
            self.assertFalse(permissions.documents(self.tech).filter(pk=doc.pk).exists())
        self.assertEqual(self.client.get(self.url('operacao:documento_arquivo',doc.pk)).status_code,404)
        form=self.client.get(self.url('operacao:documento_novo')).context['form']
        self.assertNotIn(self.other['customer'].pk,form.fields['cliente'].queryset.values_list('pk',flat=True))

    def test_single_pwa_identity_and_role_independent_launch(self):
        response=self.client.get(self.url('operacao:manifest'))
        self.assertEqual(response.json()['id'],'/tecnico/')
        self.assertEqual(response.json()['start_url'],self.url('platform_core:home'))
        self.assertEqual(response.json()['scope'],'/')
        self.client.logout()
        self.assertEqual(self.client.get(self.url('operacao:manifest')).json(),response.json())

    def test_existing_operational_os_export_is_scoped_and_financial_export_denied(self):
        response=self.client.get(self.url('gestao:relatorio','os_periodo'),{'export':'csv'})
        self.assertContains(response,self.da['order'].numero)
        self.assertNotContains(response,self.other['order'].numero)
        for key in ['receitas','despesas','contratos_ativos','movimentacao_estoque']:
            self.assertEqual(self.client.get(self.url('gestao:relatorio',key)).status_code,403)

    def test_global_superuser_cannot_bypass_technician_membership_routes(self):
        self.tech.is_superuser=True;self.tech.is_staff=True;self.tech.save()
        for url in ['/admin/','/financeiro/','/vertyx/empresa/']:
            self.assertEqual(self.client.get(url).status_code,403)

    def test_private_equipment_media_cannot_bypass_technician_scope(self):
        with tenant_context(self.a):
            equipment=self.other['equipment'];equipment.manual='qa/unassigned-manual.pdf';equipment.save()
        self.assertEqual(self.client.get('/media/qa/unassigned-manual.pdf').status_code,404)
