"""Settings and fail-closed checks without keys, database access or migrations."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

from decouple import Config, RepositoryEmpty
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from . import clinical_services
from . import phase_g_services as services


class HealthEncryptionSettingsTests(SimpleTestCase):
    def load_settings(self, value=None):
        environment = {'DEBUG': 'True', 'UPLOAD_STORAGE': 'local'}
        if value is not None:
            environment['MUNICIPAL_HEALTH_ENCRYPTION_KEY'] = value
        path = Path(__file__).resolve().parents[1] / 'tecnolmed' / 'settings.py'
        spec = importlib.util.spec_from_file_location('tecnolmed._health_settings_probe', path)
        module = importlib.util.module_from_spec(spec)
        # Ignore operational environment variables and the real .env entirely.
        with patch.dict('os.environ', environment, clear=True), patch(
            'decouple.config', Config(RepositoryEmpty())
        ):
            spec.loader.exec_module(module)
        return module

    def test_environment_value_is_loaded_without_key_generation(self):
        # An opaque marker tests configuration transport, not a cryptographic key.
        marker = 'synthetic-configuration-marker'
        with patch.object(services.Fernet, 'generate_key', side_effect=AssertionError('Forbidden')):
            self.assertEqual(self.load_settings(marker).MUNICIPAL_HEALTH_ENCRYPTION_KEY, marker)

    def test_absent_key_defaults_to_empty_and_settings_still_load(self):
        self.assertEqual(self.load_settings().MUNICIPAL_HEALTH_ENCRYPTION_KEY, '')

    def test_empty_environment_value_remains_empty(self):
        self.assertEqual(self.load_settings('').MUNICIPAL_HEALTH_ENCRYPTION_KEY, '')

    def test_configured_value_is_forwarded_to_fernet(self):
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY='synthetic-marker'), patch.object(
            services, 'Fernet'
        ) as cipher:
            self.assertIs(services._fernet(), cipher.return_value)
            cipher.assert_called_once_with(b'synthetic-marker')

    def test_missing_key_blocks_encryption_and_decryption(self):
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=''):
            with self.assertRaisesMessage(ValidationError, 'não está provisionada'):
                services._fernet()
            with self.assertRaises(ValidationError):
                clinical_services._decrypt(b'not-a-clinical-token')

    def test_malformed_loaded_key_blocks_encryption_and_decryption(self):
        value = self.load_settings('malformed').MUNICIPAL_HEALTH_ENCRYPTION_KEY
        with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=value):
            with self.assertRaisesMessage(ValidationError, 'inválida'):
                services._fernet()
            with self.assertRaises(ValidationError):
                clinical_services._decrypt(b'not-a-clinical-token')

    def test_writer_never_constructs_or_saves_plaintext_when_key_is_unusable(self):
        for value in ('', 'malformed'):
            with self.subTest(key_state='absent' if not value else 'malformed'):
                with override_settings(MUNICIPAL_HEALTH_ENCRYPTION_KEY=value), patch.object(
                    services, 'current_organization', return_value=None
                ), patch.object(services.m, 'EvolucaoClinicaMunicipal') as entry, patch.object(
                    services, '_audit'
                ) as audit:
                    with self.assertRaises(ValidationError):
                        services._persist_clinical_entry(None, None, 'SYNTHETIC CLINICAL CONTENT')
                    entry.assert_not_called()
                    entry.return_value.save.assert_not_called()
                    audit.assert_not_called()
