"""Offline safety tests. No real database, provider or filesystem uploads."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('homologation_guard', ROOT/'scripts/homologation_migrations.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class DestinationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ca = Path(self.directory.name)/'synthetic-ca.pem'
        self.ca.write_text('synthetic fixture, not a certificate')
        self.env = {'VERTYX_TEST_DATABASE_URL':
            'postgresql://vertyx_testes_user:synthetic@dpg-dbm7jfc9v7es7393tsig-a.oregon-postgres.render.com/vertyx_testes',
            'VERTYX_TEST_SSLROOTCERT': str(self.ca)}
        self.identity = dict(database_name='vertyx_testes', session_user='vertyx_testes_user',
            current_user='vertyx_testes_user', server_port=5432, read_only='on',
            in_recovery=False, tls=True, tls_version='TLSv1.3', server_version='16.15',
            owns_database=True, application_tables=0, has_migrations=False, other_clients=0)

    def test_only_exact_target_with_verified_tls_readonly_and_timeouts(self):
        result = guard.target_parameters(self.env)
        self.assertEqual(result['sslmode'], 'verify-full')
        self.assertIn('default_transaction_read_only=on', result['options'])
        self.assertIn('statement_timeout=30000', result['options'])
        self.assertEqual(result['dbname'], 'vertyx_testes')
        self.assertEqual(result['user'], 'vertyx_testes_user')

    def test_wrong_host_database_user_port_queries_and_malformed_url_rejected_before_connect(self):
        original = self.env['VERTYX_TEST_DATABASE_URL']
        bad = [original.replace('dbm7jfc9v7es7393tsig', 'production'),
            original.replace('/vertyx_testes', '/vertyx'), original.replace('vertyx_testes_user:', 'postgres:'),
            original.replace('/vertyx_testes', ':55433/vertyx_testes'),
            original + '?sslmode=disable', original + '#fragment', 'postgresql://[invalid',
            original.replace('synthetic@', '@'), original.replace('postgresql:', 'sqlite:')]
        with patch('psycopg2.connect', side_effect=AssertionError('No network')):
            for url in bad:
                with self.subTest(case=bad.index(url)), self.assertRaises(guard.SafetyError) as caught:
                    guard.target_parameters({**self.env, 'VERTYX_TEST_DATABASE_URL': url})
                self.assertNotIn('synthetic', str(caught.exception))

    def test_missing_dedicated_environment_never_uses_operational_database_url(self):
        with self.assertRaises(guard.SafetyError):
            guard.target_parameters({'DATABASE_URL': self.env['VERTYX_TEST_DATABASE_URL']})
        with self.assertRaises(guard.SafetyError):
            guard.target_parameters({**self.env, 'VERTYX_TEST_SSLROOTCERT': ''})

    def test_wrong_server_identity_tls_nonempty_or_concurrency_rejected(self):
        bad = dict(database_name='vertyx', session_user='postgres', current_user='postgres',
            server_port=55433, read_only='off', in_recovery=True, tls=False,
            tls_version='TLSv1.1', server_version='15.1', owns_database=False,
            application_tables=1, has_migrations=True, other_clients=1)
        guard.validate_identity(self.identity)
        for key, value in bad.items():
            with self.subTest(field=key), self.assertRaises(guard.SafetyError):
                guard.validate_identity({**self.identity, key: value})

    def test_preflight_uses_only_select_and_always_rolls_back_and_closes(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = self.identity
        with patch('psycopg2.connect', return_value=connection):
            self.assertEqual(guard.inspect_target(guard.target_parameters(self.env)), self.identity)
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertTrue(cursor.execute.call_args.args[0].lstrip().startswith('SELECT'))
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    def test_identity_failure_closes_without_any_data_operation(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {**self.identity, 'database_name':'vertyx'}
        with patch('psycopg2.connect', return_value=connection), self.assertRaises(guard.SafetyError):
            guard.inspect_target(guard.target_parameters(self.env))
        self.assertEqual(cursor.execute.call_count, 1)
        connection.commit.assert_not_called()
        connection.close.assert_called_once()

    def test_connection_error_never_prints_credentials_or_traceback(self):
        import contextlib
        import io
        output = io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), patch('psycopg2.connect',
            side_effect=RuntimeError('synthetic-secret')), contextlib.redirect_stderr(output):
            self.assertEqual(guard.main([]), 1)
        self.assertNotIn('synthetic-secret', output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())


class OfflineAndStartupTests(unittest.TestCase):
    def test_offline_graph_ignores_operational_environment_and_resolves_dependencies(self):
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='should.never.be.imported',
            DATABASE_URL='postgresql://sensitive.invalid/production', AWS_SECRET_ACCESS_KEY='synthetic-secret')
        result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/homologation_migrations.py'), '--offline'],
            env=env, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['destination_verified'])
        self.assertEqual(data['mode'], 'plan_only_no_migrations_executed')
        self.assertNotIn('synthetic-secret', result.stdout + result.stderr)
        seen = set()
        for item in data['migrations']:
            for app, name in item['dependencies']:
                if name == '__first__':
                    self.assertTrue(any(a == app for a, _ in seen))
                else:
                    self.assertIn((app, name), seen)
            seen.add((item['app'], item['migration']))
        self.assertEqual(len(seen), data['count'])
        self.assertIn(('rh_municipal', '0016_itemprescricao_nome_protegido'), seen)

    def test_apply_argument_has_no_executable_path(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/homologation_migrations.py'), '--apply'],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('unrecognized arguments', result.stderr)

    def test_homologation_startup_is_separate_and_never_migrates(self):
        startup = (ROOT/'scripts/start-homologation.sh').read_text()
        self.assertIn('exec gunicorn tecnolmed.wsgi:application --config gunicorn.conf.py', startup)
        self.assertIn('tecnolmed.homologation_settings', startup)
        commands = '\n'.join(line for line in startup.splitlines() if not line.lstrip().startswith('#'))
        self.assertNotIn('manage.py', commands)
        self.assertNotIn('migrate', commands)
        self.assertNotIn('prepare_commercial_demo', commands)
        self.assertIn('python manage.py migrate_locked --noinput', (ROOT/'scripts/start.sh').read_text())


if __name__ == '__main__':
    unittest.main()
