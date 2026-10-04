import io,tempfile,uuid
from pathlib import Path
from django.test import TestCase,override_settings
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from platform_core.context import tenant_context
from platform_core.models import ModuloOrganizacao
from . import models as m,services as s,permissions,block3_notices,inventory as inv
from .forms import DocumentoForm
from .test_block3_workforce import WorkforceData

class NewRoleSecurityTests(WorkforceData,TestCase):
    def test_menu_has_accessible_name_and_stock_alert_actions_keep_their_routes(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('gestao:peca_lista'))
        self.assertContains(response,'aria-label="Abrir ou recolher menu principal"')
        self.assertContains(response,'aria-controls="menuPrincipal"')
        self.assertContains(response,'class="btn btn-outline-dark" href="?minimo=1"')
        self.assertContains(response,'class="btn btn-outline-dark" href="'+reverse('operacao:stock_occurrences')+'"')
        self.assertEqual(self.client.get(reverse('gestao:peca_lista'),{'minimo':'1'}).status_code,200)
        self.assertEqual(self.client.get(reverse('operacao:stock_occurrences')).status_code,200)

    def setUp(self):
        self.setup_workforce()
        self.rh=self.user('rh-ged-b3',self.a,'RH')
        self.pdv=self.user('pdv-ged-b3',self.a,'PDV')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.settings_override=override_settings(PRIVATE_MEDIA_ROOT=Path(self.temp.name))
        self.settings_override.enable();self.addCleanup(self.settings_override.disable)

    def document(self,**extra):
        from PIL import Image
        data=io.BytesIO();Image.new('RGB',(30,20),(0,111,116)).save(data,format='PNG')
        values={'titulo':'Documento privado QA','tipo':'IMAGEM','categoria':'TECNICO'};values.update(extra)
        form=DocumentoForm(values,{'arquivo':SimpleUploadedFile('qa.png',data.getvalue(),content_type='image/png')})
        self.assertTrue(form.is_valid(),form.errors)
        return s.documento_salvar(self.admin,form)

    def test_employee_document_private_to_rh_and_foreign_organization(self):
        with tenant_context(self.a):
            doc=self.document(funcionario=self.employee.pk)
            self.assertTrue(permissions.document_allowed(self.rh,doc))
            self.assertFalse(permissions.document_allowed(self.worker,doc))
            self.assertFalse(permissions.document_allowed(self.pdv,doc))
        self.client.force_login(self.rh)
        self.assertEqual(self.client.get(reverse('operacao:documento_lista')).status_code,200)
        response=self.client.get(reverse('operacao:documento_arquivo',args=[doc.pk]))
        self.assertEqual(response.status_code,200);self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'\x89PNG'))
        for user in (self.worker,self.pdv,self.admin_b):
            self.client.force_login(user);self.assertEqual(self.client.get(reverse('operacao:documento_arquivo',args=[doc.pk])).status_code,404)

    def test_product_image_and_ged_module_cannot_cross_organization(self):
        with tenant_context(self.a):
            doc=self.document(peca=self.part.pk);self.part.imagem=doc;self.part.save()
        self.assertEqual(self.client.get(reverse('gestao:peca_detalhe',args=[self.part.pk])).status_code,200)
        with tenant_context(self.b):
            part=self.db['part'];part.imagem=doc
            with self.assertRaises(ValidationError): part.save()
        with tenant_context(self.a):ModuloOrganizacao.objects.create(codigo='documentos',habilitado=False)
        self.assertEqual(self.client.get(reverse('operacao:documento_arquivo',args=[doc.pk])).status_code,403)

    def test_inventory_notifications_update_resolve_without_erasing_read_state(self):
        with tenant_context(self.a):
            self.incoming(3);header=inv.open_inventory(self.admin,self.depot.pk,'Contagem divergente');item=header.itens.get()
            inv.count(self.admin,header.public_id,item.pk,2,uuid.uuid4())
            block3_notices.scan(self.admin);first=m.Notificacao.objects.get(usuario=self.admin,chave=f'ops-inventario:{header.pk}')
            first.lida_em=self.instant(8);first.save()
            block3_notices.scan(self.admin);first.refresh_from_db()
            self.assertIsNotNone(first.lida_em);self.assertEqual(m.Notificacao.objects.filter(usuario=self.admin,chave=first.chave).count(),1)
            inv.approve_inventory(self.admin,header.public_id);block3_notices.scan(self.admin);first.refresh_from_db()
            self.assertIsNotNone(first.resolvida_em)

    def test_purchase_creation_and_pdv_search_are_available_without_financial_privilege(self):
        buyer=self.user('comprador-ui-b3',self.a,'COMPRAS');self.client.force_login(buyer)
        self.assertContains(self.client.get(reverse('operacao:compra_lista')),reverse('operacao:compra_novo'))
        self.assertEqual(self.client.get(reverse('operacao:compra_novo')).status_code,200)
        self.assertEqual(self.client.get(reverse('operacao:banco_lista')).status_code,403)

    def test_credit_limit_is_rendered_only_for_authorized_customer_editor(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('clientes:cliente_update',args=[self.da['customer'].pk]))
        self.assertContains(response,'name="limite_credito"')
        self.assertContains(response,'for="id_limite_credito"')
        self.client.force_login(self.pdv)
        response=self.client.get(reverse('clientes:cliente_create'))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'name="limite_credito"')
