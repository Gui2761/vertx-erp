"""Synthetic-only storage validation. No Cloudflare account is contacted."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from tecnolmed.deployment import homologation_storage
from .test_deployment import environment
from . import test_deployment as deployment_tests


class R2ConfigurationTests(SimpleTestCase):
    def config(self, **changes):
        values = dict(HOMOLOGATION_STORAGE='r2', S3_BUCKET_NAME='vertyx-homologacao',
            S3_ENDPOINT_URL='https://' + 'a' * 32 + '.r2.cloudflarestorage.com',
            AWS_ACCESS_KEY_ID='synthetic-id', AWS_SECRET_ACCESS_KEY='synthetic-secret')
        values.update(changes)
        return values

    def test_disabled_default_does_not_read_any_provider_credentials(self):
        def config(name, default=None):
            self.assertEqual(name, 'HOMOLOGATION_STORAGE')
            return default
        self.assertIn('DisabledStorage', homologation_storage(config)['BACKEND'])

    def test_r2_reuses_private_s3_without_aws_session_or_public_urls(self):
        config = self.config(AWS_SESSION_TOKEN='synthetic-inherited-ignored')
        with patch('boto3.client', side_effect=AssertionError('No network during configuration')):
            result = homologation_storage(environment(config))
        self.assertEqual(result['BACKEND'], 'platform_core.storage.AuthenticatedS3Storage')
        options = result['OPTIONS']
        self.assertEqual(options['bucket_name'], 'vertyx-homologacao')
        self.assertEqual(options['region_name'], 'auto')
        self.assertIsNone(options['security_token'])
        self.assertIsNone(options['default_acl'])
        self.assertIsNone(options['custom_domain'])
        self.assertFalse(options['file_overwrite'])
        self.assertEqual(options['client_config'].signature_version, 's3v4')
        self.assertEqual(options['client_config'].s3['addressing_style'], 'path')

    def test_each_missing_required_variable_disables_without_filesystem_fallback(self):
        for name in ('S3_BUCKET_NAME', 'S3_ENDPOINT_URL', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'):
            with self.subTest(variable=name):
                result = homologation_storage(environment(self.config(**{name: ''})))
                self.assertIn('DisabledStorage', result['BACKEND'])

    def test_rejects_other_bucket_provider_unsafe_endpoint_region_and_mode(self):
        cases = [dict(HOMOLOGATION_STORAGE='local'), dict(S3_BUCKET_NAME='another-bucket'),
            dict(S3_REGION_NAME='us-east-1'), dict(S3_ADDRESSING_STYLE='virtual')]
        for endpoint in ('http://' + 'a'*32 + '.r2.cloudflarestorage.com',
            'https://s3.amazonaws.com', 'https://synthetic:secret@example.test',
            self.config()['S3_ENDPOINT_URL'] + '/path', self.config()['S3_ENDPOINT_URL'] + '?token=synthetic'):
            cases.append(dict(S3_ENDPOINT_URL=endpoint))
        for changes in cases:
            with self.subTest(names=list(changes)), self.assertRaises(ImproperlyConfigured) as error:
                homologation_storage(environment(self.config(**changes)))
            self.assertNotIn('synthetic', str(error.exception))

    def test_actual_homologation_settings_enable_only_complete_r2(self):
        import sys
        from decouple import Config, RepositoryEmpty
        root = Path(__file__).resolve().parents[1] / 'tecnolmed'
        for complete in (True, False):
            values = self.config()
            if not complete:
                values.pop('AWS_SECRET_ACCESS_KEY')
            values.update(DJANGO_SETTINGS_MODULE='tecnolmed.homologation_settings', DEBUG='False',
                SECRET_KEY='synthetic-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ-abcdefghijklmnop',
                DATABASE_URL='postgresql://demo@127.0.0.1:55437/unused',
                ALLOWED_HOSTS='test.example.test')
            with patch.dict('os.environ', values, clear=True), patch('decouple.config', Config(RepositoryEmpty())):
                spec = importlib.util.spec_from_file_location('tecnolmed.settings', root/'settings.py')
                base = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(base)
                with patch.dict(sys.modules, {'tecnolmed.settings': base}):
                    spec = importlib.util.spec_from_file_location('tecnolmed._r2_probe', root/'homologation_settings.py')
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                self.assertFalse(module.DEBUG)
                self.assertEqual(module.FILE_UPLOADS_ENABLED, complete)
                self.assertEqual(module.PRIVATE_STORAGE['OPTIONS']['location'], 'private')
                self.assertEqual(module.STORAGES['default']['OPTIONS']['location'], 'media')
                self.assertEqual('FILE_UPLOAD_HANDLERS' in vars(module), not complete)


class R2ProtectedFilesTests(TestCase):
    # Reuse synthetic fixtures, without re-running inherited test methods.
    setUp = deployment_tests.RemoteStorageTests.setUp
    make_user = deployment_tests.RemoteStorageTests.make_user
    make_data = deployment_tests.RemoteStorageTests.make_data

    def prepare_metered_documents(self):
        from .saas_models import PlanoSaaS, AssinaturaSaaS
        from .saas_services import aplicar_modulos
        user = self.make_user('metered-admin', self.a, 'ADMIN')
        plan = PlanoSaaS.objects.create(slug='metered-synthetic', nome='Synthetic metered',
            modulos=['assistencia', 'documentos'], limites={'armazenamento_mb': 1})
        AssinaturaSaaS.objects.create(organization=self.a, plano=plan, status='ATIVA')
        aplicar_modulos(self.a, plan)
        self.client.force_login(user)

    def test_metered_document_upload_and_download_use_v2_and_ignore_other_tenant(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from operacao.models import Documento
        from .context import tenant_context
        self.prepare_metered_documents()
        self.s3.put_object(Bucket=self.bucket,
            Key=f'private/organizations/{self.b.public_id}/large-synthetic.bin', Body=b'x' * (2 * 1024 * 1024))
        payload = b'%PDF-1.4 synthetic acceptance only'
        with patch('storages.backends.s3.S3Storage.listdir', side_effect=AssertionError('Legacy listing must not be used')):
            response = self.client.post(reverse('operacao:documento_novo'), {
                'titulo': 'Metered fictitious document', 'tipo': 'PDF', 'categoria': 'OUTRO',
                'cliente': self.data_a['client'].pk,
                'arquivo': SimpleUploadedFile('synthetic.pdf', payload, content_type='application/pdf')})
        self.assertEqual(response.status_code, 302)
        with tenant_context(self.a):
            document = Documento.objects.get(titulo='Metered fictitious document')
        response = self.client.get(reverse('operacao:documento_arquivo', args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), payload)
        self.client.force_login(self.tech_b)
        self.assertEqual(self.client.get(reverse('operacao:documento_arquivo', args=[document.pk])).status_code, 404)

    def test_meter_failure_blocks_upload_before_any_object_or_document_is_created(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from operacao.models import Documento
        from .context import tenant_context
        from .storage import StorageUnavailable
        self.prepare_metered_documents()
        with tenant_context(self.a):
            before = Documento.objects.count()
        with patch('platform_core.storage.AuthenticatedS3Storage.usage_bytes', side_effect=StorageUnavailable()), patch(
                'platform_core.storage.AuthenticatedS3Storage._save', side_effect=AssertionError('Must not upload on unknown usage')):
            response = self.client.post(reverse('operacao:documento_novo'), {
                'titulo': 'Rejected fictitious document', 'tipo': 'PDF',
                'arquivo': SimpleUploadedFile('synthetic.pdf', b'%PDF-1.4 synthetic', content_type='application/pdf')})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Medição não disponível', status_code=400)
        with tenant_context(self.a):
            self.assertEqual(Documento.objects.count(), before)

    def test_r2_configuration_roundtrip_with_simulated_endpoint_and_private_bucket(self):
        from django.core.files.storage import storages
        endpoint = 'https://' + 'a'*32 + '.r2.cloudflarestorage.com'
        self.s3.create_bucket(Bucket='vertyx-homologacao')
        definition = homologation_storage(environment(dict(HOMOLOGATION_STORAGE='r2',
            S3_BUCKET_NAME='vertyx-homologacao', S3_ENDPOINT_URL=endpoint,
            AWS_ACCESS_KEY_ID='synthetic', AWS_SECRET_ACCESS_KEY='synthetic')))
        definition['OPTIONS']['location'] = 'private'
        with patch.dict('os.environ', {'MOTO_S3_CUSTOM_ENDPOINTS': endpoint}):
            storage = storages.create_storage(definition)
            name = storage.save(f'organizations/{self.a.public_id}/branding/r2.txt', ContentFile(b'fictional-r2'))
            with storage.open(name) as stream:
                self.assertEqual(stream.read(), b'fictional-r2')
            self.assertNotIn('X-Amz', storage.url(name))
            self.assertTrue(storage.exists(name))
            storage.delete(name)
            self.assertFalse(storage.exists(name))

    def test_logo_download_is_authenticated_tenant_scoped_and_private(self):
        from ordens.storage import private_storage
        name = f'organizations/{self.a.public_id}/branding/synthetic.png'
        name = private_storage.save(name, ContentFile(b'synthetic-logo'))
        self.a.logo_key = name
        self.a.save(update_fields=['logo_key'])
        url = reverse('legacy_media', kwargs={'name': name})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'synthetic-logo')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.client.force_login(self.tech_b)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_document_attachment_download_and_direct_id_are_tenant_scoped(self):
        from operacao.models import Documento
        from .context import tenant_context
        with tenant_context(self.a):
            document = Documento.objects.create(titulo='Anexo fictício', cliente=self.data_a['client'],
                ordem=self.data_a['order'], enviado_por=self.tech_a,
                arquivo=ContentFile(b'synthetic-document', name='attachment.txt'), sha256='a'*64)
        url = reverse('operacao:documento_arquivo', args=[document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'synthetic-document')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertIn(f'private/organizations/{self.a.public_id}/',
            'private/' + document.arquivo.name)
        self.client.force_login(self.tech_b)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_connection_failure_is_sanitized_and_never_uses_local_storage(self):
        from botocore.exceptions import EndpointConnectionError
        from ordens.storage import private_storage
        from .storage import StorageUnavailable
        error = EndpointConnectionError(endpoint_url='https://synthetic-secret.invalid')
        with patch('storages.backends.s3.S3Storage._save', side_effect=error), patch(
            'django.core.files.storage.FileSystemStorage._save', side_effect=AssertionError('No local fallback')):
            with self.assertLogs('vertyx.operations', level='ERROR') as logs:
                with self.assertRaises(StorageUnavailable) as caught:
                    private_storage.save('synthetic.txt', ContentFile(b'synthetic'))
        self.assertNotIn('synthetic-secret', str(caught.exception) + ''.join(logs.output))

    def test_download_connection_failure_returns_generic_503(self):
        from botocore.exceptions import ReadTimeoutError
        url = reverse('ordens:foto', args=[self.data_a['order'].pk, self.data_a['photo'].pk])
        with patch('storages.backends.s3.S3Storage._open', side_effect=ReadTimeoutError(endpoint_url='synthetic-secret')):
            with self.assertLogs('vertyx.operations', level='ERROR') as logs:
                response = self.client.get(url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('synthetic-secret', response.content.decode() + ''.join(logs.output))
