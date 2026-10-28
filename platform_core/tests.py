import base64
import io
import tempfile
from contextlib import ExitStack
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw
from contas.models import Usuario, Tecnico
from clientes.models import Cliente, Unidade, ContatoCliente
from equipamentos.models import CategoriaEquipamento, Equipamento
from ordens.models import OrdemServico, Localizacao, Foto, Conferencia, Assinatura, Auditoria
from ordens import services
from ordens.forms import OrdemForm, AssinaturaForm
from ordens.reports import gerar_pdf
from ordens.views import token_conferencia
from .models import Organization, OrganizationMembership, OrganizationERP, MembershipERP, ERPCatalog, PlatformAudit
from .context import tenant_context, current_organization
from .validators import validate_cnpj


def sample_signature():
    image = Image.new('RGB', (900, 320), 'white')
    ImageDraw.Draw(image).line([(40, 150), (100, 50), (170, 220), (400, 110)], fill='black', width=5)
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


class MultiTenantTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(override_settings(PRIVATE_STORAGE={'BACKEND': 'django.core.files.storage.FileSystemStorage', 'OPTIONS': {'location': directory}}, MEDIA_ROOT=directory))
        self.erp = ERPCatalog.objects.get(code='assistencia')
        self.a = Organization.objects.create(slug='empresa-a', razao_social='Empresa A Ltda.', nome_fantasia='MARCA EMPRESA A')
        self.b = Organization.objects.create(slug='empresa-b', razao_social='Empresa B Ltda.', nome_fantasia='MARCA EMPRESA B')
        OrganizationERP.objects.create(organization=self.a, erp=self.erp)
        OrganizationERP.objects.create(organization=self.b, erp=self.erp)
        self.admin_a = self.make_user('admin-a', self.a, 'ADMIN')
        self.admin_b = self.make_user('admin-b', self.b, 'ADMIN')
        self.tech_a = self.make_user('tech-a', self.a, 'TECNICO')
        self.tech_b = self.make_user('tech-b', self.b, 'TECNICO')
        self.data_a = self.make_data(self.a, self.tech_a)
        self.data_b = self.make_data(self.b, self.tech_b)
        self.client.force_login(self.admin_a)

    def make_user(self, name, org, role='TECNICO', enabled=True):
        user = Usuario.objects.create_user(name, perfil='ADMIN')  # Papel global não concede permissão.
        membership = OrganizationMembership.objects.create(user=user, organization=org, role=role)
        MembershipERP.objects.create(membership=membership, erp=self.erp, enabled=enabled)
        return user

    def make_data(self, org, user):
        with tenant_context(org):
            client = Cliente.objects.create(nome_razao_social=f'Cliente {org.slug}', cpf_cnpj='DOCUMENTO-IGUAL')
            unit = Unidade.objects.create(cliente=client, nome=f'Unidade {org.slug}')
            contact = ContatoCliente.objects.create(cliente=client, nome='Responsável local')
            category = CategoriaEquipamento.objects.create(nome='Categoria comum')
            equipment = Equipamento.objects.create(nome=f'Equipamento {org.slug}', cliente=client, unidade=unit, categoria=category)
            tech = Tecnico.objects.create(nome=f'Técnico {org.slug}', usuario=user)
            order = OrdemServico.objects.create(cliente=client, unidade=unit, equipamento=equipment, tecnico=tech, defeito='Falha')
            services.iniciar(user, order.pk, {'resultado': 'OBTIDA', 'latitude': '-9', 'longitude': '-35', 'precisao': 8})
            order.refresh_from_db()
            order.diagnostico, order.servico_executado = 'Fonte', 'Troca da fonte'
            order.save()
            # Conteúdo JPEG válido, sem dependência de path local.
            image = Image.new('RGB', (80, 80), 'gray')
            buffer = io.BytesIO()
            image.save(buffer, 'JPEG')
            photo = services.adicionar_foto(user, order.pk, {'arquivo': ContentFile(buffer.getvalue(), name='foto.jpg'), 'descricao': 'Imagem'})
            conference = services.preparar(user, order.pk, {'resultado': 'NEGADA', 'latitude': None, 'longitude': None, 'precisao': None})
            form = AssinaturaForm({'token': token_conferencia(conference), 'nome': 'Responsável', 'cargo': 'Gerente', 'imagem': sample_signature(), 'confirmacao': True})
            self.assertTrue(form.is_valid(), form.errors)
            signature = services.finalizar(user, order.pk, conference.pk, form.cleaned_data)
            order.refresh_from_db()
            return {'client': client, 'unit': unit, 'contact': contact, 'category': category, 'equipment': equipment, 'tech': tech, 'order': order, 'photo': photo, 'conference': conference, 'signature': signature}

    def entity_urls(self, data):
        order = data['order'].pk
        return [reverse('clientes:cliente_detail', args=[data['client'].pk]), reverse('clientes:cliente_update', args=[data['client'].pk]), reverse('clientes:unidade_update', args=[data['unit'].pk]), reverse('equipamentos:equipamento_detail', args=[data['equipment'].pk]), reverse('equipamentos:equipamento_qr', args=[data['equipment'].codigo_publico]), reverse('equipamentos:equipamento_update', args=[data['equipment'].pk]), reverse('contas:tecnico_update', args=[data['tech'].pk]), reverse('ordens:detalhe', args=[order]), reverse('ordens:foto', args=[order, data['photo'].pk]), reverse('ordens:assinatura_imagem', args=[order, data['signature'].pk]), reverse('ordens:pdf', args=[order, data['signature'].pk]), reverse('ordens:conferencia', args=[order, token_conferencia(data['conference'])])]

    def test_a_e_b_isoladas_por_url_get(self):
        for user, own, other in [(self.admin_a, self.data_a, self.data_b), (self.admin_b, self.data_b, self.data_a)]:
            self.client.force_login(user)
            for url in self.entity_urls(other):
                with self.subTest(user=user.username, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 404)
            for url in [reverse('clientes:cliente_detail', args=[own['client'].pk]), reverse('equipamentos:equipamento_detail', args=[own['equipment'].pk]), reverse('ordens:detalhe', args=[own['order'].pk]), reverse('ordens:pdf', args=[own['order'].pk, own['signature'].pk])]:
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_idor_post_edicao_e_reabertura(self):
        for user, other in [(self.admin_a, self.data_b), (self.admin_b, self.data_a)]:
            self.client.force_login(user)
            for name in ['editar', 'iniciar', 'preparar', 'finalizar', 'reabrir', 'foto_adicionar']:
                self.assertEqual(self.client.post(reverse(f'ordens:{name}', args=[other['order'].pk]), {'justificativa': 'Tentativa de invasão'}).status_code, 404)
            for name, pk in [('clientes:cliente_update', other['client'].pk), ('clientes:unidade_update', other['unit'].pk), ('equipamentos:equipamento_update', other['equipment'].pk), ('contas:tecnico_update', other['tech'].pk), ('contas:usuario_update', self.tech_b.pk if user == self.admin_a else self.tech_a.pk)]:
                self.assertEqual(self.client.post(reverse(name, args=[pk]), {}).status_code, 404)

    def test_todas_entidades_filtradas_no_manager_e_relacoes(self):
        for org, own, other in [(self.a, self.data_a, self.data_b), (self.b, self.data_b, self.data_a)]:
            with tenant_context(org):
                for model in [Cliente, Unidade, ContatoCliente, CategoriaEquipamento, Equipamento, Tecnico, OrdemServico, Localizacao, Foto, Conferencia, Assinatura, Auditoria]:
                    self.assertGreater(model.objects.count(), 0)
                    if hasattr(model, 'organization_id'):
                        self.assertFalse(model.objects.exclude(organization=org).exists())
                self.assertFalse(Localizacao.objects.filter(ordem=other['order']).exists())
                self.assertFalse(own['client'].equipamentos.filter(pk=other['equipment'].pk).exists())
                self.assertFalse(own['order'].fotos.filter(pk=other['photo'].pk).exists())
                self.assertFalse(Assinatura.objects.filter(pk=other['signature'].pk).exists())
        self.assertIsNone(current_organization())
        self.assertEqual(Cliente.objects.count(), 0)

    def test_formularios_nao_aceitam_fk_de_outro_tenant(self):
        with tenant_context(self.a):
            form = OrdemForm({'cliente': self.data_b['client'].pk, 'unidade': self.data_b['unit'].pk, 'equipamento': self.data_b['equipment'].pk, 'tecnico': self.data_b['tech'].pk, 'tipo_atendimento': 'CORRETIVA', 'defeito': 'Invasão'})
            self.assertFalse(form.is_valid())
            self.assertIn('cliente', form.errors)
            self.assertNotIn(str(self.data_b['client']), str(form.fields['cliente'].queryset))

    def test_orm_rejeita_relacoes_cruzadas_e_transferencia(self):
        with tenant_context(self.a):
            with self.assertRaises(ValidationError):
                Equipamento.objects.create(nome='Invasão', cliente=self.data_b['client'], categoria=self.data_a['category'])
            with self.assertRaises(ValidationError):
                Foto.objects.create(ordem=self.data_b['order'], usuario=self.tech_a, descricao='Invasão')
            other = self.data_b['client']
            other.organization = self.a
            with self.assertRaises(ValidationError):
                other.save()

    def test_contexto_sem_tenant_falha_fechado_e_isolamento_apos_request(self):
        self.assertEqual(OrdemServico.objects.count(), 0)
        with self.assertRaises(PermissionDenied):
            Cliente.objects.create(nome_razao_social='Sem tenant', cpf_cnpj='ABC')
        self.client.get(reverse('ordens:lista'))
        self.assertIsNone(current_organization())
        with tenant_context(self.a):
            with tenant_context(self.b):
                self.assertEqual(current_organization(), self.b)
            self.assertEqual(current_organization(), self.a)
        self.assertIsNone(current_organization())

    def test_servicos_e_pdf_diretos_nao_aceitam_objeto_de_outro_tenant(self):
        with tenant_context(self.a):
            with self.assertRaises(PermissionDenied):
                services.autorizar(self.admin_a, self.data_b['order'])
            with self.assertRaises(ValidationError):
                gerar_pdf(self.data_b['signature'])

    def test_erp_habilitado_organizacao_e_membro_sao_ambos_obrigatorios(self):
        membership = OrganizationMembership.objects.get(user=self.admin_a, organization=self.a)
        access = MembershipERP.objects.get(membership=membership, erp=self.erp)
        access.enabled = False
        access.save()
        self.assertEqual(self.client.get(reverse('clientes:cliente_list')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('platform_core:home')), 'Entrar no ERP Assistência')
        access.enabled = True
        access.save()
        org_access = OrganizationERP.objects.get(organization=self.a, erp=self.erp)
        org_access.enabled = False
        org_access.save()
        self.assertEqual(self.client.get(reverse('ordens:lista')).status_code, 403)

    def test_catalogo_inativo_revoga_acesso(self):
        self.erp.active = False
        self.erp.save()
        self.assertEqual(self.client.get(reverse('equipamentos:equipamento_list')).status_code, 403)

    def test_suspensao_e_membership_bloqueado_invalidam_sessao(self):
        self.client.get(reverse('ordens:lista'))
        membership = OrganizationMembership.objects.get(user=self.admin_a, organization=self.a)
        membership.status = 'BLOQUEADO'
        membership.save()
        response = self.client.get(reverse('ordens:lista'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('organization_id', self.client.session)
        membership.status = 'ATIVO'
        membership.save()
        self.a.status = 'SUSPENSA'
        self.a.save()
        self.assertEqual(self.client.get(reverse('ordens:lista')).status_code, 302)

    def test_tecnico_nao_altera_cadastros_nem_usuarios(self):
        self.client.force_login(self.tech_a)
        for name, args in [('clientes:cliente_create', []), ('clientes:cliente_update', [self.data_a['client'].pk]), ('clientes:unidade_create', []), ('equipamentos:equipamento_create', []), ('equipamentos:equipamento_update', [self.data_a['equipment'].pk]), ('contas:usuario_create', []), ('contas:tecnico_create', [])]:
            self.assertEqual(self.client.post(reverse(name, args=args), {}).status_code, 403)
        self.assertEqual(self.client.get(reverse('ordens:detalhe', args=[self.data_a['order'].pk])).status_code, 200)

    def test_ajax_nao_vaza_unidades(self):
        response = self.client.get(reverse('equipamentos:unidades_por_cliente'), {'cliente': self.data_b['client'].pk})
        self.assertEqual(response.json(), {'unidades': []})

    def test_home_login_e_redirecionamentos(self):
        response = self.client.get(reverse('platform_core:home'))
        self.assertRedirects(response, '/assistencia/')
        selector = self.client.get(reverse('platform_core:home'), {'organizacoes': '1'})
        self.assertContains(selector, 'MARCA EMPRESA A')
        self.assertContains(selector, 'Entrar no ERP Assistência')
        self.assertNotContains(selector, 'MARCA EMPRESA B')
        self.assertEqual(self.client.get('/').status_code, 302)
        self.admin_a.set_password('test-password')
        self.admin_a.save()
        self.client.logout()
        self.assertContains(self.client.get(reverse('contas:login')), 'VERTYX')
        self.assertRedirects(self.client.post(reverse('contas:login'), {'username': self.admin_a.username, 'password': 'test-password'}), '/assistencia/')

    def test_multiplas_organizacoes_selecao_e_perfil_independentes(self):
        membership = OrganizationMembership.objects.create(user=self.admin_a, organization=self.b, role='TECNICO')
        MembershipERP.objects.create(membership=membership, erp=self.erp)
        session = self.client.session
        session.pop('organization_id', None)
        session.save()
        self.assertNotContains(self.client.get(reverse('platform_core:home')), 'Entrar no ERP Assistência')
        response = self.client.post(reverse('platform_core:select_organization'), {'organization': str(self.b.public_id)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session['organization_id'], self.b.pk)
        self.assertEqual(self.client.post(reverse('clientes:cliente_create'), {}).status_code, 403)
        self.assertTrue(PlatformAudit.objects.filter(organization=self.b, user=self.admin_a, action='ORGANIZACAO_SELECIONADA').exists())

    def test_selecao_organização_forjada_e_csrf(self):
        self.assertEqual(self.client.post(reverse('platform_core:select_organization'), {'organization': str(self.b.public_id)}).status_code, 404)
        self.assertEqual(self.client.post(reverse('platform_core:select_organization'), {'organization': 'bad'}).status_code, 400)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.admin_a)
        self.assertEqual(guarded.post(reverse('platform_core:select_organization'), {'organization': str(self.a.public_id)}).status_code, 403)

    def test_superuser_nao_recebe_acesso_empresarial_automatico(self):
        user = Usuario.objects.create_superuser('platform-admin', password='temporary-test')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('ordens:lista')).status_code, 302)
        self.assertNotContains(self.client.get(reverse('platform_core:home')), 'Entrar no ERP Assistência')
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)
        self.client.force_login(self.admin_a)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 403)

    def test_media_antiga_agora_privada_por_org(self):
        with tenant_context(self.b):
            equipment = self.data_b['equipment']
            equipment.manual.save('manual.txt', ContentFile(b'PRIVATE-B'), save=True)
            name = equipment.manual.name
        self.assertEqual(self.client.get('/media/' + name).status_code, 404)
        self.client.force_login(self.admin_b)
        response = self.client.get('/media/' + name)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content))
        self.client.logout()
        self.assertEqual(self.client.get('/media/' + name).status_code, 302)

    def test_branding_pdf_por_org_e_snapshot_preservado(self):
        with tenant_context(self.a):
            assinatura = self.data_a['signature']
            self.assertEqual(assinatura.conferencia.dados['organization']['nome'], 'MARCA EMPRESA A')
            self.a.nome_fantasia = 'Nome atualizado'
            self.a.save()
            output = gerar_pdf(assinatura)
            self.assertIn(b'MARCA EMPRESA A', output)
            self.assertNotIn(b'MARCA EMPRESA B', output)

    def test_cliente_categoria_e_tecnico_unicos_por_organizacao(self):
        with tenant_context(self.b):
            self.assertTrue(Cliente.objects.filter(cpf_cnpj='DOCUMENTO-IGUAL').exists())
            self.assertTrue(CategoriaEquipamento.objects.filter(nome='Categoria comum').exists())
            OrganizationMembership.objects.create(user=self.tech_a, organization=self.b)
            other_record = Tecnico.objects.create(nome='Técnico em duas empresas', usuario=self.tech_a)
            self.assertEqual(other_record.organization_id, self.b.pk)

    def test_admin_organização_cria_usuario_com_membership_e_sem_staff(self):
        response = self.client.post(reverse('contas:usuario_create'), {'username': 'new-member', 'first_name': 'Novo', 'perfil': 'TECNICO', 'password1': 'Super-Strong-Example-921!', 'password2': 'Super-Strong-Example-921!', 'acesso_assistencia': 'on', 'is_superuser': True, 'is_staff': True})
        self.assertEqual(response.status_code, 302)
        user = Usuario.objects.get(username='new-member')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(OrganizationMembership.objects.filter(user=user, organization=self.a).exists())
        self.assertFalse(OrganizationMembership.objects.filter(user=user, organization=self.b).exists())

    def test_admin_altera_somente_membership_da_propria_org(self):
        other_membership = OrganizationMembership.objects.create(user=self.tech_a, organization=self.b, role='GESTOR')
        response = self.client.post(reverse('contas:usuario_update', args=[self.tech_a.pk]), {'perfil': 'FINANCEIRO', 'status': 'INATIVO', 'is_active': False, 'is_superuser': True})
        self.assertEqual(response.status_code, 302)
        self.tech_a.refresh_from_db()
        other_membership.refresh_from_db()
        self.assertTrue(self.tech_a.is_active)
        self.assertFalse(self.tech_a.is_superuser)
        self.assertEqual(other_membership.role, 'GESTOR')
        self.assertEqual(other_membership.status, 'ATIVO')
        own = OrganizationMembership.objects.get(user=self.tech_a, organization=self.a)
        self.assertEqual(own.status, 'INATIVO')
        self.assertIsNotNone(own.left_at)

    def test_auditoria_determina_org_erp_autor_registro(self):
        with tenant_context(self.a):
            audit = Auditoria.objects.first()
            self.assertEqual(audit.organization, self.a)
            self.assertEqual(audit.erp_code, 'assistencia')
            self.assertEqual(audit.usuario, self.tech_a)
            self.assertIsNotNone(audit.ordem_id)
            self.assertIsNotNone(audit.data)

    def test_ids_de_arquivos_conferencias_de_b_na_url_de_a(self):
        own = self.data_a['order'].pk
        other = self.data_b
        for name, item in [('foto', other['photo']), ('assinatura_imagem', other['signature']), ('pdf', other['signature'])]:
            self.assertEqual(self.client.get(reverse(f'ordens:{name}', args=[own, item.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('ordens:conferencia', args=[own, token_conferencia(other['conference'])])).status_code, 400)

    def test_metricas_somente_org_atual_e_com_permissao(self):
        from .metrics import assistance_usage
        with tenant_context(self.a):
            usage = assistance_usage(self.admin_a)
            self.assertEqual(usage['clientes'], 1)
            self.assertEqual(usage['ordens'], 1)
            self.assertEqual(usage['fotos'], 1)
            with self.assertRaises(PermissionDenied):
                assistance_usage(self.tech_a)

    def test_categorias_criacao_edicao_e_idor(self):
        self.assertEqual(self.client.post(reverse('equipamentos:categoria_create'), {'nome': 'Nova categoria', 'descricao': 'Descrição'}).status_code, 302)
        with tenant_context(self.a):
            category = CategoriaEquipamento.objects.get(nome='Nova categoria')
        self.assertEqual(self.client.post(reverse('equipamentos:categoria_update', args=[category.pk]), {'nome': 'Categoria alterada', 'descricao': 'Nova descrição'}).status_code, 302)
        self.assertEqual(self.client.post(reverse('equipamentos:categoria_update', args=[self.data_b['category'].pk]), {'nome': 'Invasão'}).status_code, 404)

    def test_listas_de_cadastros_nao_incluem_empresa_b(self):
        for name, forbidden in [('clientes:cliente_list', str(self.data_b['client'])), ('equipamentos:equipamento_list', self.data_b['equipment'].nome), ('contas:tecnico_list', self.data_b['tech'].nome), ('contas:usuario_list', self.tech_b.username)]:
            self.assertNotContains(self.client.get(reverse(name)), forbidden)

    def test_form_cliente_unidade_e_equipamento_salvam_com_org_correta(self):
        from clientes.forms import ClienteForm
        from equipamentos.forms import EquipamentoForm
        with tenant_context(self.a):
            form = ClienteForm({'tipo_pessoa': 'PJ', 'nome_razao_social': 'Novo cliente A', 'cpf_cnpj': 'NOVO', 'ativo': True})
            self.assertTrue(form.is_valid(), form.errors)
            obj = form.save()
            self.assertEqual(obj.organization, self.a)
            form = EquipamentoForm({'nome': 'Novo equipamento', 'categoria': self.data_b['category'].pk, 'cliente': obj.pk, 'situacao_operacional': 'OK'})
            self.assertFalse(form.is_valid())
            form = EquipamentoForm({'nome': 'Novo equipamento', 'categoria': self.data_a['category'].pk, 'cliente': obj.pk, 'situacao_operacional': 'OK'})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.save().organization, self.a)

    def test_duplicados_no_tenant_dao_erro_no_form_sem_afetar_outro_tenant(self):
        from clientes.forms import ClienteForm
        from equipamentos.forms import CategoriaForm
        with tenant_context(self.a):
            form = ClienteForm({'tipo_pessoa': 'PJ', 'nome_razao_social': 'Duplicado', 'cpf_cnpj': 'DOCUMENTO-IGUAL', 'ativo': True})
            self.assertFalse(form.is_valid())
            self.assertIn('cpf_cnpj', form.errors)
            self.assertFalse(CategoriaForm({'nome': 'Categoria comum'}).is_valid())

    def test_cadastro_cliente_com_contato_e_unidade_sem_cliente_invalida(self):
        payload = {'tipo_pessoa': 'PJ', 'nome_razao_social': 'Cliente com contato', 'cpf_cnpj': 'CONTATO-A', 'ativo': 'on', 'contatos-TOTAL_FORMS': '1', 'contatos-INITIAL_FORMS': '0', 'contatos-MIN_NUM_FORMS': '0', 'contatos-MAX_NUM_FORMS': '1000', 'contatos-0-nome': 'Responsável do cadastro', 'contatos-0-cargo': 'Gerente'}
        response = self.client.post(reverse('clientes:cliente_create'), payload)
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.a):
            customer = Cliente.objects.get(cpf_cnpj='CONTATO-A')
            self.assertEqual(customer.organization, self.a)
            self.assertEqual(customer.contatos.get().nome, 'Responsável do cadastro')
        response = self.client.post(reverse('clientes:unidade_create'), {'nome': 'Sem cliente'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)

    def test_nao_desativa_proprio_admin_e_nao_altera_identidade_global(self):
        response = self.client.post(reverse('contas:usuario_update', args=[self.admin_a.pk]), {'perfil': 'TECNICO', 'status': 'INATIVO'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(OrganizationMembership.objects.get(user=self.admin_a, organization=self.a).role, 'ADMIN')

    def test_storage_url_privada_e_caminho_por_org(self):
        from ordens.storage import private_storage
        self.assertIn(str(self.a.public_id), self.data_a['photo'].arquivo.name)
        with self.assertRaises(ValueError):
            private_storage.url(self.data_a['photo'].arquivo.name)

    def test_contextos_concorrentes_nao_compartilham_organizacao(self):
        # ContextVar mantém tarefas concorrentes separadas sem depender de SQL SQLite.
        import asyncio
        async def runner():
            async def work(org):
                with tenant_context(org):
                    await asyncio.sleep(0)
                    return current_organization().pk
            return await asyncio.gather(work(self.a), work(self.b))
        self.assertEqual(asyncio.run(runner()), [self.a.pk, self.b.pk])

    def test_admin_empresarial_exige_membership_e_ambos_acessos_erp(self):
        operator = Usuario.objects.create_superuser('operador-testes', password='senha-apenas-teste')
        membership = OrganizationMembership.objects.create(user=operator, organization=self.a, role='ADMIN')
        grant = MembershipERP.objects.create(membership=membership, erp=self.erp)
        self.client.force_login(operator)
        for model in ['ordemservico', 'localizacao', 'foto', 'conferencia', 'assinatura', 'auditoria']:
            self.assertEqual(self.client.get(reverse(f'admin:ordens_{model}_changelist')).status_code, 200)
        grant.enabled = False
        grant.save()
        self.assertEqual(self.client.get(reverse('admin:ordens_ordemservico_changelist')).status_code, 403)
        grant.enabled = True
        grant.save()
        OrganizationERP.objects.filter(organization=self.a, erp=self.erp).update(enabled=False)
        self.assertEqual(self.client.get(reverse('admin:ordens_foto_changelist')).status_code, 403)


class CNPJTests(TestCase):
    def test_cnpj_numerico_e_alfanumerico(self):
        for value in ['11.222.333/0001-81', '12.ABC.345/01DE-35', '00.000.000/E08G-12']:
            validate_cnpj(value)

    def test_cnpj_invalido_rejeitado(self):
        for value in ['00000000000000', '11.222.333/0001-80', 'XX', '12.ABC.345/01DE-00']:
            with self.assertRaises(ValidationError):
                validate_cnpj(value)

    def test_normalizacao_formatacao_e_primeiro_tenant_sem_cnpj_ficticio(self):
        org = Organization.objects.create(slug='cnpj', razao_social='Exemplo', cnpj='12.abc.345/01de-35')
        self.assertEqual(org.cnpj, '12ABC34501DE35')
        self.assertEqual(org.cnpj_formatado, '12.ABC.345/01DE-35')
        self.assertEqual(Organization.objects.get(slug='tecnolmed').cnpj, '')


class LegacyMigrationTests(SimpleTestCase):
    def test_upgrade_com_dados_anteriores_sem_reverter_bancos_existentes(self):
        import subprocess
        import sys
        from pathlib import Path
        import os
        from django.conf import settings
        environment = os.environ.copy()
        environment['VERTYX_LEGACY_SETTINGS_MODULE'] = settings.SETTINGS_MODULE
        # The unchanged full legacy upgrade took 274.7s with the B3 graph on
        # local PostgreSQL. Keep a bounded budget without removing assertions.
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / 'tests' / 'legacy_migration.py')], capture_output=True, text=True, timeout=600, env=environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"legacy_upgrade": "PASS"', result.stdout)
