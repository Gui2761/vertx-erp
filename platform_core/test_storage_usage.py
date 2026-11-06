"""Synthetic storage measurements: no real keys, network or database required."""
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.stub import Stubber
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, storages
from django.test import SimpleTestCase

from ordens.storage import PrivateStorage
from tecnolmed.deployment import homologation_storage
from .logging_utils import operation_failure
from .saas_services import _storage_usage_bytes, verificar_limite
from .storage import StorageUnavailable
from .test_deployment import environment


class StorageUsageTests(SimpleTestCase):
    def setUp(self):
        self.org = SimpleNamespace(pk=1, public_id=uuid.uuid4())
        self.prefix = f'organizations/{self.org.public_id}/'
        definition = homologation_storage(environment({
            'HOMOLOGATION_STORAGE': 'r2', 'S3_BUCKET_NAME': 'vertyx-homologacao',
            'S3_ENDPOINT_URL': 'https://' + 'a' * 32 + '.r2.cloudflarestorage.com',
            'AWS_ACCESS_KEY_ID': 'synthetic-only', 'AWS_SECRET_ACCESS_KEY': 'synthetic-only',
        }))
        definition['OPTIONS']['location'] = 'private'
        self.storage = storages.create_storage(definition)
        self.path = 'private/' + self.prefix
        self.stub = Stubber(self.storage.connection.meta.client)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)
        self.addCleanup(self.stub.assert_no_pending_responses)

    def page(self, contents, **extra):
        return {'IsTruncated': False, 'Contents': contents, **extra}

    def expected(self, **extra):
        return {'Bucket': 'vertyx-homologacao', 'Prefix': self.path, **extra}

    def measure(self):
        with patch.object(PrivateStorage, 'backend', new_callable=PropertyMock, return_value=self.storage):
            return _storage_usage_bytes(self.org)

    def test_empty_tenant_is_zero_without_head_or_bucket_wide_listing(self):
        self.stub.add_response('list_objects_v2', self.page([]), self.expected())
        self.assertEqual(self.measure(), 0)

    def test_pagination_includes_nested_keys_and_sizes_without_head(self):
        self.stub.add_response('list_objects_v2', self.page([
            {'Key': self.path + 'docs/a.pdf', 'Size': 7}],
            IsTruncated=True, NextContinuationToken='synthetic-page-2'), self.expected())
        self.stub.add_response('list_objects_v2', self.page([
            {'Key': self.path + 'photos/b.png', 'Size': 11},
            {'Key': self.path, 'Size': 0}]), self.expected(ContinuationToken='synthetic-page-2'))
        self.assertEqual(self.measure(), 18)

    def test_two_tenants_have_different_exact_slash_bounded_prefixes(self):
        other = SimpleNamespace(public_id=uuid.uuid4())
        other_path = f'private/organizations/{other.public_id}/'
        self.stub.add_response('list_objects_v2', self.page([
            {'Key': self.path + 'a', 'Size': 7}]), self.expected())
        self.stub.add_response('list_objects_v2', self.page([
            {'Key': other_path + 'b', 'Size': 11}]),
            {'Bucket': 'vertyx-homologacao', 'Prefix': other_path})
        with patch.object(PrivateStorage, 'backend', new_callable=PropertyMock, return_value=self.storage):
            self.assertEqual(_storage_usage_bytes(self.org), 7)
            self.assertEqual(_storage_usage_bytes(other), 11)

    def test_invalid_or_root_prefixes_are_rejected_before_network(self):
        for prefix in ('', '/', 'organizations/', self.prefix.rstrip('/'),
                       self.prefix + '../', 'organizations/not-a-uuid/', None):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                self.storage.usage_bytes(prefix)

    def test_foreign_key_in_provider_response_fails_closed(self):
        self.stub.add_response('list_objects_v2', self.page([
            {'Key': 'private/organizations/' + str(uuid.uuid4()) + '/foreign', 'Size': 8}]), self.expected())
        with self.assertLogs('vertyx.operations', level='ERROR') as logs:
            self.assertIsNone(self.measure())
        self.assertIn('ValueError', ''.join(logs.output))

    def test_invalid_size_fails_closed_without_partial_usage(self):
        paginator = Mock()
        paginator.paginate.return_value = [{'Contents': [{'Key': self.path + 'a', 'Size': True}]}]
        with patch.object(self.storage.connection.meta.client, 'get_paginator', return_value=paginator), self.assertLogs('vertyx.operations'):
            self.assertIsNone(self.measure())

    def test_later_page_failure_discards_partial_sum(self):
        self.stub.add_response('list_objects_v2', self.page([
            {'Key': self.path + 'a', 'Size': 10}], IsTruncated=True,
            NextContinuationToken='synthetic-page-2'), self.expected())
        self.stub.add_client_error('list_objects_v2', service_error_code='AccessDenied',
            service_message='DO-NOT-LOG-SYNTHETIC-SECRET', http_status_code=403,
            expected_params=self.expected(ContinuationToken='synthetic-page-2'))
        with self.assertLogs('vertyx.operations', level='ERROR') as logs:
            self.assertIsNone(self.measure())
        text = ''.join(logs.output)
        self.assertIn('s3_code=AccessDenied', text)
        self.assertIn('operation=ListObjectsV2', text)
        self.assertIn('http_status=403', text)
        self.assertNotIn('DO-NOT-LOG', text)
        self.assertNotIn(str(self.org.public_id), text)

    def test_missing_bucket_is_unknown_usage_not_empty_tenant(self):
        self.stub.add_client_error('list_objects_v2', service_error_code='NoSuchBucket',
            http_status_code=404, expected_params=self.expected())
        with self.assertLogs('vertyx.operations', level='ERROR') as logs:
            self.assertIsNone(self.measure())
        self.assertIn('s3_code=NoSuchBucket', ''.join(logs.output))

    def test_connectivity_error_is_sanitized_and_never_falls_back(self):
        with patch.object(self.storage.connection.meta.client, 'get_paginator',
                          side_effect=EndpointConnectionError(endpoint_url='https://SYNTHETIC-SECRET.invalid')), self.assertLogs('vertyx.operations') as logs:
            self.assertIsNone(self.measure())
        self.assertIn('EndpointConnectionError', ''.join(logs.output))
        self.assertNotIn('SYNTHETIC-SECRET', ''.join(logs.output))

    def test_existing_filesystem_measurement_preserves_tenant_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = FileSystemStorage(location=directory)
            storage.save(self.prefix + 'nested/a', ContentFile(b'1234567'))
            storage.save(f'organizations/{uuid.uuid4()}/other', ContentFile(b'123456789'))
            with patch.object(PrivateStorage, 'backend', new_callable=PropertyMock, return_value=storage):
                self.assertEqual(_storage_usage_bytes(self.org), 7)
                self.assertEqual(_storage_usage_bytes(SimpleNamespace(public_id=uuid.uuid4())), 0)

    def test_unknown_backend_exception_is_logged_without_payload(self):
        backend = SimpleNamespace(usage_bytes=Mock(side_effect=RuntimeError('SYNTHETIC-SECRET')))
        with patch.object(PrivateStorage, 'backend', new_callable=PropertyMock, return_value=backend), self.assertLogs('vertyx.operations') as logs:
            self.assertIsNone(_storage_usage_bytes(self.org))
        self.assertIn('RuntimeError', ''.join(logs.output))
        self.assertNotIn('SYNTHETIC-SECRET', ''.join(logs.output))

    def test_unknown_usage_still_blocks_quota(self):
        with patch('platform_core.saas_services.Organization'), patch(
                'platform_core.saas_services._contract_quota', return_value=(False, None)), patch(
                'platform_core.saas_services._legacy_quota_limit', return_value=1), patch(
                'platform_core.saas_services._storage_usage_bytes', return_value=None):
            with self.assertRaisesMessage(ValidationError, 'Medição não disponível'):
                verificar_limite.__wrapped__(self.org, 'armazenamento_mb', incremento=1)

    def test_full_quota_still_blocks_and_exact_limit_remains_allowed(self):
        with patch('platform_core.saas_services.Organization'), patch(
                'platform_core.saas_services._contract_quota', return_value=(False, None)), patch(
                'platform_core.saas_services._legacy_quota_limit', return_value=1), patch(
                'platform_core.saas_services._storage_usage_bytes', return_value=1024 * 1024 - 1):
            verificar_limite.__wrapped__(self.org, 'armazenamento_mb', incremento=1)
            with self.assertRaisesMessage(ValidationError, 'Limite de armazenamento'):
                verificar_limite.__wrapped__(self.org, 'armazenamento_mb', incremento=2)


class StorageDiagnosticTests(SimpleTestCase):
    def test_allowlisted_authentication_code_without_provider_message(self):
        for code in ('InvalidAccessKeyId', 'SignatureDoesNotMatch', 'AccessDenied'):
            error = ClientError({'Error': {'Code': code, 'Message': 'SYNTHETIC-SECRET'},
                'ResponseMetadata': {'HTTPStatusCode': 403, 'RequestId': 'SYNTHETIC-SECRET'}}, 'ListObjectsV2')
            with self.subTest(code=code), self.assertLogs('vertyx.operations') as logs:
                operation_failure('storage_usage_failed', error)
            self.assertIn('s3_code=' + code, ''.join(logs.output))
            self.assertNotIn('SYNTHETIC-SECRET', ''.join(logs.output))

    def test_unknown_code_operation_and_http_status_are_not_logged(self):
        error = ClientError({'Error': {'Code': 'SYNTHETIC-SECRET', 'Message': 'SYNTHETIC-SECRET'},
            'ResponseMetadata': {'HTTPStatusCode': 'SYNTHETIC-SECRET'}}, 'SYNTHETIC-SECRET')
        with self.assertLogs('vertyx.operations') as logs:
            operation_failure('storage_usage_failed', error)
        self.assertNotIn('SYNTHETIC-SECRET', ''.join(logs.output))
        self.assertIn('s3_code=Other operation=Other http_status=-', ''.join(logs.output))
