import importlib.util
from pathlib import Path
from unittest.mock import patch
from decouple import Config, RepositoryEmpty
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from .uploads import DisabledStorage, UploadsDisabled

DISABLED = {'BACKEND':'platform_core.uploads.DisabledStorage','OPTIONS':{}}


class DisabledStorageConfigurationTests(SimpleTestCase):
    def test_debug_false_homologation_starts_without_reading_aws_credentials(self):
        environment = {'DJANGO_SETTINGS_MODULE':'tecnolmed.homologation_settings',
            'DEBUG':'False', 'SECRET_KEY':'synthetic-config-only-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ-abcdef',
            'DATABASE_URL':'postgresql://demo@127.0.0.1:55437/unused',
            'ALLOWED_HOSTS':'vertyx-erp.onrender.com',
            'CSRF_TRUSTED_ORIGINS':'https://vertyx-erp.onrender.com',
            'UPLOAD_STORAGE':'s3', 'AWS_ACCESS_KEY_ID':'synthetic-old-ignored',
            'AWS_SECRET_ACCESS_KEY':'synthetic-old-ignored'}
        path=Path(__file__).resolve().parents[1]/'tecnolmed/settings.py'
        spec=importlib.util.spec_from_file_location('tecnolmed._disabled_storage_probe',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict('os.environ',environment,clear=True), patch('decouple.config',Config(RepositoryEmpty())), patch(
            'tecnolmed.deployment.required',side_effect=AssertionError('Must not read AWS/S3 credentials')
        ), patch('boto3.client',side_effect=AssertionError('No cloud client')):
            spec.loader.exec_module(module)
        self.assertFalse(module.DEBUG)
        self.assertEqual(module.PRIVATE_STORAGE['BACKEND'], DISABLED['BACKEND'])
        self.assertEqual(module.STORAGES['default']['BACKEND'], DISABLED['BACKEND'])

    def test_production_still_requires_s3_and_does_not_accept_disabled_env_mode(self):
        from tecnolmed.deployment import upload_storage
        from .test_deployment import environment
        for mode in ('disabled', 'local', ''):
            with self.assertRaises(ImproperlyConfigured):
                upload_storage(environment({'UPLOAD_STORAGE':mode}),False)

    def test_direct_storage_has_no_disk_or_cloud_fallback(self):
        from ordens.storage import private_storage
        from django.core.files.storage import default_storage
        with override_settings(PRIVATE_STORAGE=DISABLED,STORAGES={
            'default':DISABLED,'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}
        }), patch('django.core.files.storage.FileSystemStorage._save',side_effect=AssertionError('No disk writes')), patch(
            'boto3.client',side_effect=AssertionError('No cloud client')
        ):
            for storage in (private_storage,default_storage,DisabledStorage()):
                self.assertFalse(storage.exists('demo.txt'))
                with self.assertRaises(UploadsDisabled): storage.save('demo.txt',ContentFile(b'synthetic'))
                with self.assertRaises(UploadsDisabled): storage.open('demo.txt')
                with self.assertRaises(UploadsDisabled): storage.delete('demo.txt')


@override_settings(FILE_UPLOADS_ENABLED=False,COMMERCIAL_DEMO_ENABLED=True,
    PRIVATE_STORAGE=DISABLED,
    FILE_UPLOAD_HANDLERS=['platform_core.uploads.DisabledUploadHandler'])
class DisabledUploadsHTTPTests(TestCase):
    def setUp(self):
        from django.conf import settings
        from .commercial_demo import preparar_demo
        from .context import tenant_context
        from ordens.models import OrdemServico
        self.org, self.people=preparar_demo([
            {'nome':f'Pessoa Fictícia {i}','email':f'no-upload-{i}@example.test'} for i in range(3)
        ])
        self.owner=self.people[0]['user']
        self.client.force_login(self.owner)
        self.override=override_settings(
            MIDDLEWARE=[*settings.MIDDLEWARE,'platform_core.uploads.DisabledUploadsMiddleware'],
            STORAGES={'default':DISABLED,'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}},
        )
        self.override.enable(); self.addCleanup(self.override.disable)
        with tenant_context(self.org): self.order=OrdemServico.objects.get()

    def test_small_and_large_uploads_are_rejected_before_any_file_is_written(self):
        from ordens.models import Foto
        from .context import tenant_context
        for size in (16,3*1024*1024):
            with patch('django.core.files.uploadhandler.TemporaryFileUploadHandler.new_file',side_effect=AssertionError('No temporary files')), patch(
                'django.core.files.storage.FileSystemStorage._save',side_effect=AssertionError('No file writes')
            ), patch('boto3.client',side_effect=AssertionError('No cloud client')):
                response=self.client.post(reverse('ordens:foto_adicionar',args=[self.order.pk]),{
                    'arquivo':SimpleUploadedFile('synthetic.jpg',b'x'*size,content_type='image/jpeg')})
            self.assertEqual(response.status_code,409)
            self.assertContains(response,'Nenhum arquivo foi salvo',status_code=409)
            self.assertEqual(response['Cache-Control'],'private, no-store')
            with tenant_context(self.org): self.assertEqual(Foto.objects.count(),0)

    def test_ordinary_forms_without_files_are_not_blocked(self):
        from ordens.models import OrdemServico
        from .context import tenant_context
        response=self.client.post(reverse('ordens:criar'),{
            'cliente':self.order.cliente_id,'unidade':self.order.unidade_id,
            'equipamento':self.order.equipamento_id,'tecnico':self.order.tecnico_id,
            'tipo_atendimento':'CORRETIVA','defeito':'Avaliação DEMO sem arquivo'})
        self.assertEqual(response.status_code,302)
        with tenant_context(self.org): self.assertEqual(OrdemServico.objects.count(),2)

    def test_os_signature_remains_in_database_but_persistent_pdf_is_clearly_unavailable(self):
        from .context import tenant_context
        from .tests import sample_signature
        from ordens import services
        from ordens.forms import AssinaturaForm
        from ordens.models import Status,Assinatura,DocumentoOSAssinado
        with tenant_context(self.org):
            services.iniciar(self.owner,self.order.pk,{'resultado':'NEGADA','latitude':None,'longitude':None,'precisao':None})
            self.order.refresh_from_db()
            self.order.diagnostico='Diagnóstico DEMO'; self.order.servico_executado='Serviço DEMO'; self.order.save()
            conference=services.preparar(self.owner,self.order.pk,{'resultado':'NEGADA','latitude':None,'longitude':None,'precisao':None})
            form=AssinaturaForm({'token':'synthetic','nome':'Responsável DEMO','cargo':'Avaliador',
                                 'imagem':sample_signature(),'confirmacao':True})
            self.assertTrue(form.is_valid(),form.errors)
            signature=services.finalizar(self.owner,self.order.pk,conference.pk,form.cleaned_data)
            self.order.refresh_from_db(); self.assertEqual(self.order.status,Status.FINALIZADA)
            self.assertEqual(Assinatura.objects.count(),1)
        response=self.client.get(reverse('ordens:pdf',args=[self.order.pk,signature.pk]))
        self.assertContains(response,'A OS e a assinatura permanecem registradas no banco',status_code=409)
        with tenant_context(self.org): self.assertEqual(DocumentoOSAssinado.objects.count(),0)
