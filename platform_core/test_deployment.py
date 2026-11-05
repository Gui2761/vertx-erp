import io
import logging
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from tecnolmed.deployment import postgres_database, upload_storage, validate_public_settings
from .logging_utils import SafeLogFilter


def environment(values):
    def getter(name, default=None, cast=None):
        value = values.get(name, default)
        if cast is bool:
            return str(value).lower() in ['true', '1', 'yes']
        return cast(value) if cast else value
    return getter


class ProductionConfigurationTests(SimpleTestCase):
    def test_homologacao_desabilita_email_e_fiscal_sem_mudar_settings_principais(self):
        from tecnolmed import homologation_settings
        self.assertEqual(homologation_settings.EMAIL_BACKEND, 'django.core.mail.backends.dummy.EmailBackend')
        self.assertFalse(homologation_settings.FISCAL_SIMULATION_ENABLED)
        self.assertFalse(homologation_settings.FISCAL_NFCE_LOCAL_ENABLED)
        self.assertEqual(homologation_settings.SESSION_COOKIE_NAME, 'vertyx_homologacao_sessionid')
        self.assertEqual(homologation_settings.CSRF_COOKIE_NAME, 'vertyx_homologacao_csrftoken')

    @override_settings(FISCAL_SIMULATION_ENABLED=False, FISCAL_NFCE_LOCAL_ENABLED=False)
    def test_fiscal_desabilitado_rejeita_execucao_antes_de_operar(self):
        from django.core.exceptions import ValidationError
        from fiscal.foundation import simulacao
        from fiscal.nfce.services import local
        with self.assertRaises(ValidationError):
            simulacao()
        with self.assertRaises(ValidationError):
            local()

    def test_render_internal_database_url_preserva_host_banco_e_ssl(self):
        data = postgres_database(environment({
            'DATABASE_URL': 'postgresql://demo:synthetic@dpg-demo-internal/vertyx_demo',
        }), False)
        self.assertEqual(data['HOST'], 'dpg-demo-internal')
        self.assertEqual(data['NAME'], 'vertyx_demo')
        self.assertEqual(data['OPTIONS']['sslmode'], 'require')

    def test_sem_database_url_producao_falha_sem_fallback(self):
        with self.assertRaises(ImproperlyConfigured):
            postgres_database(environment({}), False)

    def test_urls_invalida_sqlite_mysql_rejeitadas_sem_expor_senha(self):
        for value in ['invalid', 'sqlite:///db.sqlite3', 'mysql://user:SENHA_PRIVADA@localhost/database']:
            with self.assertRaises(ImproperlyConfigured) as error:
                postgres_database(environment({'DATABASE_URL': value}), False)
            self.assertNotIn('SENHA_PRIVADA', str(error.exception))

    def test_postgres_conexao_healthcheck_ssl_e_timeout(self):
        data = postgres_database(environment({'DATABASE_URL': 'postgresql://localhost/database', 'CONN_MAX_AGE': '30'}), False)
        self.assertEqual(data['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(data['CONN_MAX_AGE'], 30)
        self.assertTrue(data['CONN_HEALTH_CHECKS'])
        self.assertEqual(data['OPTIONS'], {'connect_timeout': 5, 'sslmode': 'require'})

    def test_chave_insegura_e_hosts_abertos_rejeitados(self):
        for secret in ['', 'dev-secret-key-nao-use-em-producao', 'A' * 60]:
            with self.assertRaises(ImproperlyConfigured):
                validate_public_settings(secret, ['localhost'], [], False)
        for hosts in [[], ['*'], ['https://localhost']]:
            with self.assertRaises(ImproperlyConfigured):
                validate_public_settings('0123456789abcdef' * 4, hosts, [], False)

    def test_csrf_rejeita_http_wildcard_e_credenciais(self):
        for origin in ['http://localhost', 'https://*.invalid', 'https://user:secret@localhost', 'https://localhost/path']:
            with self.assertRaises(ImproperlyConfigured):
                validate_public_settings('0123456789abcdef' * 4, ['localhost'], [origin], False)

    def test_storage_local_nao_silenciosamente_utilizado_em_producao(self):
        for mode in ['', 'local']:
            with self.assertRaises(ImproperlyConfigured):
                upload_storage(environment({'UPLOAD_STORAGE': mode}), False)

    def test_s3_exige_variaveis_sem_inventar_endpoint_credenciais(self):
        with self.assertRaises(ImproperlyConfigured):
            upload_storage(environment({'UPLOAD_STORAGE': 's3'}), False)

    def test_logs_nao_incluem_url_token_payload_nem_excecao_sensivel(self):
        try:
            raise DatabaseError('SENHA_PRIVADA token=TOKEN_PRIVADO')
        except DatabaseError:
            import sys
            record = logging.LogRecord('django.request', logging.ERROR, __file__, 1, '/ordens/conferencia/TOKEN_PRIVADO %s', ('ASSINATURA_BASE64',), sys.exc_info())
        SafeLogFilter().filter(record)
        self.assertNotIn('PRIVADO', record.getMessage())
        self.assertNotIn('BASE64', record.getMessage())
        self.assertIn('DatabaseError', record.getMessage())
        self.assertIsNone(record.exc_info)


class HealthTests(TestCase):
    def test_health_sem_login_e_sem_dados_internos(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_banco_indisponivel_retoma_503_sem_segredos(self):
        with patch('platform_core.health.connection.cursor', side_effect=DatabaseError('SENHA_PRIVADA')):
            with self.assertLogs('vertyx.operations', level='ERROR') as logs:
                response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})
        self.assertNotIn('SENHA_PRIVADA', ''.join(logs.output))

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r'^health/$'], SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_https_redirecionamento_com_health_compativel_com_proxy(self):
        self.assertEqual(self.client.get('/health/').status_code, 200)
        self.assertEqual(self.client.get('/contas/login/').status_code, 301)
        self.assertEqual(self.client.get('/contas/login/', secure=True).status_code, 200)


class RemoteStorageTests(TestCase):
    # Reutiliza builders, sem herdar e duplicar os testes anteriores.
    from .tests import MultiTenantTests
    make_user = MultiTenantTests.make_user
    make_data = MultiTenantTests.make_data

    def setUp(self):
        import boto3
        from moto import mock_aws
        from .models import Organization, OrganizationERP, ERPCatalog
        mocked = mock_aws()
        mocked.start()
        self.addCleanup(mocked.stop)
        self.s3 = boto3.client('s3', region_name='us-east-1')
        self.bucket = 'vertyx-local-unit-tests'  # Bucket somente dentro do simulador.
        self.s3.create_bucket(Bucket=self.bucket)
        common = {'bucket_name': self.bucket, 'region_name': 'us-east-1', 'default_acl': None, 'file_overwrite': False, 'custom_domain': None}
        self.private_definition = {'BACKEND': 'platform_core.storage.AuthenticatedS3Storage', 'OPTIONS': {**common, 'location': 'private'}}
        self.media_definition = {'BACKEND': 'platform_core.storage.AuthenticatedS3Storage', 'OPTIONS': {**common, 'location': 'media'}}
        # Django 5.0 override_settings reconstrói o alias legado sem OPTIONS;
        # globals equivalentes são somente da fixture Moto, não da produção.
        override = override_settings(PRIVATE_STORAGE=self.private_definition, STORAGES={'default': self.media_definition, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}, AWS_STORAGE_BUCKET_NAME=self.bucket, AWS_S3_REGION_NAME='us-east-1', AWS_LOCATION='media', AWS_DEFAULT_ACL=None, AWS_S3_FILE_OVERWRITE=False)
        override.enable()
        self.addCleanup(override.disable)
        self.erp = ERPCatalog.objects.get(code='assistencia')
        self.a = Organization.objects.get(slug='tecnolmed')
        self.b = Organization.objects.create(slug='remote-test-b', razao_social='Empresa Teste Remoto')
        OrganizationERP.objects.create(organization=self.b, erp=self.erp)
        self.tech_a = self.make_user('remote-user-a', self.a)
        self.tech_b = self.make_user('remote-user-b', self.b)
        self.data_a = self.make_data(self.a, self.tech_a)
        self.data_b = self.make_data(self.b, self.tech_b)
        self.client.force_login(self.tech_a)

    def test_upload_stream_fresh_storage_pdf_e_acl_privada(self):
        from django.core.files.storage import storages
        from ordens.reports import gerar_pdf
        from .context import tenant_context
        from ordens.storage import private_storage
        item = self.data_a['photo']
        with tenant_context(self.a):
            fresh = storages.create_storage(self.private_definition)
            with fresh.open(item.arquivo.name, 'rb') as stream:
                self.assertTrue(stream.read().startswith(b'\xff\xd8'))
            with self.assertRaises(NotImplementedError):
                fresh.path(item.arquivo.name)
            with self.assertRaises(ValueError):
                private_storage.url(item.arquivo.name)
            pdf = gerar_pdf(self.data_a['signature'])
            self.assertTrue(pdf.startswith(b'%PDF-'))
            self.assertIn(b'TECNOLMED', pdf)
        grants = self.s3.get_object_acl(Bucket=self.bucket, Key='private/' + item.arquivo.name)['Grants']
        self.assertFalse(any(g['Grantee'].get('URI', '').endswith('AllUsers') for g in grants))
        with tenant_context(self.b):
            self.assertIn(b'Empresa Teste Remoto', gerar_pdf(self.data_b['signature']))

    def test_foto_assinatura_pdf_e_os_negados_entre_empresas_s3(self):
        from django.urls import reverse
        for user, other in [(self.tech_a, self.data_b), (self.tech_b, self.data_a)]:
            self.client.force_login(user)
            order = other['order'].pk
            urls = [reverse('ordens:detalhe', args=[order]), reverse('ordens:foto', args=[order, other['photo'].pk]), reverse('ordens:assinatura_imagem', args=[order, other['signature'].pk]), reverse('ordens:pdf', args=[order, other['signature'].pk])]
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_midias_de_equipamento_s3_url_django_sem_presigned(self):
        from django.core.files.base import ContentFile
        from django.urls import reverse
        from .context import tenant_context
        equipment = self.data_a['equipment']
        with tenant_context(self.a):
            equipment.manual.save('manual.pdf', ContentFile(b'%PDF-manual'), save=False)
            equipment.save()
            url = equipment.manual.url
        self.assertTrue(url.startswith('/media/organizations/'))
        self.assertNotIn('X-Amz', url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-manual')
        self.client.force_login(self.tech_b)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_falha_s3_upload_nao_finaliza_operacao_nem_expoe_credenciais(self):
        from botocore.exceptions import ClientError
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        from ordens.models import OrdemServico, Foto
        from ordens import services
        from ordens.tests import png
        from .context import tenant_context
        own = self.data_a
        with tenant_context(self.a):
            order = OrdemServico.objects.create(cliente=own['client'], equipamento=own['equipment'], unidade=own['unit'], tecnico=own['tech'], defeito='Teste de indisponibilidade')
            services.iniciar(self.tech_a, order.pk, {'resultado': 'NEGADA'})
        error = ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'SENHA_PRIVADA'}}, 'PutObject')
        with patch('storages.backends.s3.S3Storage._save', side_effect=error):
            with self.assertLogs('vertyx.operations', level='ERROR') as logs:
                response = self.client.post(reverse('ordens:foto_adicionar', args=[order.pk]), {'arquivo': SimpleUploadedFile('foto.png', png(), content_type='image/png')})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('SENHA_PRIVADA', response.content.decode() + ''.join(logs.output))
        with tenant_context(self.a):
            self.assertFalse(Foto.objects.filter(ordem=order).exists())
            self.assertFalse(order.historico.filter(acao='FOTO_ADICIONADA').exists())

    def test_migracao_uploads_planeja_copia_verifica_e_recusa_sobrescrita(self):
        import json
        import tempfile
        from pathlib import Path
        from django.core.management import call_command, CommandError
        from ordens.storage import private_storage
        from .context import tenant_context
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for data in [self.data_a, self.data_b]:
                name = data['photo'].arquivo.name
                with private_storage.open(name, 'rb') as stream:
                    original = stream.read()
                path = root / 'private' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
                self.s3.delete_object(Bucket=self.bucket, Key='private/' + name)
            kwargs = {'source_private': str(root / 'private'), 'source_media': str(root / 'media'), 'manifest': str(root / 'manifest.json'), 'stdout': io.StringIO()}
            call_command('migrate_uploads', **kwargs)
            records = json.loads((root / 'manifest.json').read_text())['records']
            self.assertTrue(all(r['status'] == 'planned' for r in records))
            self.assertFalse(private_storage.exists(self.data_a['photo'].arquivo.name))
            call_command('migrate_uploads', apply=True, **kwargs)
            self.assertTrue(all(r['status'] == 'copied_verified' for r in json.loads((root / 'manifest.json').read_text())['records']))
            call_command('migrate_uploads', apply=True, **kwargs)
            self.assertTrue(all(r['status'] == 'already_verified' for r in json.loads((root / 'manifest.json').read_text())['records']))
            (root / 'private' / self.data_a['photo'].arquivo.name).write_bytes(b'alterado')
            with self.assertRaises(CommandError):
                call_command('migrate_uploads', apply=True, **kwargs)
            with tenant_context(self.a):
                self.data_a['conference'].refresh_from_db()
                from ordens import services
                self.assertEqual(services.digest(self.data_a['conference'].dados), self.data_a['conference'].digest)

class CommercialHomologationBoundaryTests(TestCase):
    """An Assistance-only organization must not reach unreleased municipal flows."""
    from .tests import MultiTenantTests
    setUp = MultiTenantTests.setUp
    make_user = MultiTenantTests.make_user
    make_data = MultiTenantTests.make_data

    def test_assistance_users_cannot_read_or_write_clinical_or_procurement_routes(self):
        from uuid import UUID
        patient = UUID('00000000-0000-0000-0000-000000000001')
        paths = [
            '/gestao-publica/licitacoes/',
            '/gestao-publica/saude/prontuarios/',
            f'/gestao-publica/saude/prontuarios/{patient}/',
            f'/gestao-publica/saude/prontuarios/{patient}/atendimentos/',
        ]
        for user in (self.admin_a, self.tech_a):
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
            self.client.force_login(user)
            for path in paths:
                for method in ('get', 'post'):
                    with self.subTest(role=user.username, path=path, method=method):
                        response = getattr(self.client, method)(path)
                        self.assertIn(response.status_code, (403, 404))
