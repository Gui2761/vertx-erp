"""Read-only preflight and Django migration plan for one named Render database.

No apply/migrate entry point exists in this preparation stage. Never imports
project settings, reads .env, starts Django HTTP, or loads R2 credentials.
"""
import argparse
import ast
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import sys
from urllib.parse import unquote, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATABASE = 'vertyx_testes'
USER = 'vertyx_testes_user'
RESOURCE = 'dpg-dbm7jfc9v7es7393tsig-a'
HOSTS = (RESOURCE, RESOURCE + '.oregon-postgres.render.com')


class SafetyError(Exception):
    """Only fixed, non-secret messages may reach the operator."""


def target_parameters(environ):
    value = environ.get('VERTYX_TEST_DATABASE_URL', '')
    if not value:
        raise SafetyError('Configure VERTYX_TEST_DATABASE_URL no ambiente temporário do executor.')
    try:
        url = urlsplit(value)
        valid = (url.scheme in ('postgres', 'postgresql') and url.hostname in HOSTS
                 and url.port in (None, 5432) and url.path == '/' + DATABASE
                 and unquote(url.username or '') == USER and bool(url.password)
                 and not url.query and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise SafetyError('Destino recusado: host, porta, banco, usuário ou formato não autorizado.')
    ca = Path(environ.get('VERTYX_TEST_SSLROOTCERT', ''))
    if not ca.is_file():
        raise SafetyError('Configure VERTYX_TEST_SSLROOTCERT com um arquivo CA confiável existente.')
    return dict(host=url.hostname, port=5432, dbname=DATABASE, user=USER,
                password=unquote(url.password), sslmode='verify-full', sslrootcert=str(ca.resolve()),
                connect_timeout=5, application_name='vertyx_readonly_migration_plan',
                options='-c default_transaction_read_only=on -c lock_timeout=5000 '
                        '-c statement_timeout=30000 -c search_path=public')


def validate_identity(row):
    expected = {'database_name': DATABASE, 'session_user': USER, 'current_user': USER,
                'server_port': 5432, 'read_only': 'on', 'in_recovery': False,
                'tls': True, 'owns_database': True}
    if any(row.get(key) != value for key, value in expected.items()):
        raise SafetyError('Identidade PostgreSQL, TLS, permissões ou modo somente leitura incompatível.')
    if not str(row.get('server_version', '')).startswith('16.') or row.get('tls_version') not in ('TLSv1.2', 'TLSv1.3'):
        raise SafetyError('Exige PostgreSQL 16 e TLS 1.2 ou superior.')
    if row.get('application_tables') != 0 or row.get('has_migrations') is not False:
        raise SafetyError('Banco deixou de estar vazio; interromper e revisar o plano.')
    if row.get('other_clients') != 0:
        raise SafetyError('Existem outras conexões de cliente; interromper e verificar isolamento.')


def inspect_target(parameters):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    # Parameters were validated before the very first network connection.
    connection = psycopg2.connect(**parameters)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT current_database() AS database_name, session_user::text AS session_user,
                    current_user::text AS current_user, inet_server_port() AS server_port,
                    current_setting('server_version') AS server_version,
                    current_setting('transaction_read_only') AS read_only,
                    pg_is_in_recovery() AS in_recovery,
                    (SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()) AS tls,
                    (SELECT version FROM pg_stat_ssl WHERE pid=pg_backend_pid()) AS tls_version,
                    (SELECT pg_get_userbyid(datdba)=current_user FROM pg_database
                        WHERE datname=current_database()) AS owns_database,
                    (SELECT count(*) FROM information_schema.tables WHERE table_schema
                        NOT IN ('pg_catalog','information_schema') AND table_type='BASE TABLE') AS application_tables,
                    to_regclass('public.django_migrations') IS NOT NULL AS has_migrations,
                    (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()
                        AND backend_type='client backend' AND pid<>pg_backend_pid()) AS other_clients
            """)
            identity = dict(cursor.fetchone())
            validate_identity(identity)
            return identity
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def migration_plan():
    """Load the actual Django graph, without opening any database or bucket."""
    sys.path.insert(0, str(ROOT))
    from django.conf import settings
    if settings.configured:
        raise SafetyError('Execute em processo novo; settings Django já estavam carregadas.')
    tree = ast.parse((ROOT / 'tecnolmed/settings.py').read_text(encoding='utf-8'))
    apps = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'INSTALLED_APPS' for t in n.targets))
    settings.configure(INSTALLED_APPS=apps, AUTH_USER_MODEL='contas.Usuario',
        DATABASES={'default': {'ENGINE': 'django.db.backends.dummy'}},
        DEFAULT_AUTO_FIELD='django.db.models.BigAutoField', USE_TZ=True,
        SECRET_KEY='offline-planner-not-an-application-credential',
        STORAGES={'default': {'BACKEND': 'platform_core.uploads.DisabledStorage'},
                  'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
    from django.db.backends.base.base import BaseDatabaseWrapper
    import django
    with patch.object(BaseDatabaseWrapper, 'ensure_connection', side_effect=SafetyError('Conexão Django bloqueada.')), patch.object(
            socket.socket, 'connect', side_effect=SafetyError('Rede bloqueada durante leitura do grafo.')):
        django.setup()
        from django.db.migrations.loader import MigrationLoader
        loader = MigrationLoader(None, ignore_no_migrations=True)
        if loader.detect_conflicts():
            raise SafetyError('Conflitos encontrados no grafo de migrations.')
        records, seen = [], set()
        for leaf in sorted(loader.graph.leaf_nodes()):
            for node in loader.graph.forwards_plan(leaf):
                if node in seen:
                    continue
                seen.add(node)
                migration = loader.disk_migrations[node]
                source = Path(sys.modules[migration.__module__].__file__)
                records.append(dict(app=node[0], migration=node[1],
                    dependencies=[list(dep) for dep in migration.dependencies],
                    operations=[op.describe() for op in migration.operations],
                    contains_data_operations=any(type(op).__name__ in ('RunPython', 'RunSQL') for op in migration.operations),
                    source_sha256=hashlib.sha256(source.read_text(encoding='utf-8').encode()).hexdigest()))
        digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
        return {'mode': 'plan_only_no_migrations_executed', 'expected_database': DATABASE,
                'count': len(records), 'plan_sha256': digest,
                'leaf_nodes': [list(n) for n in sorted(loader.graph.leaf_nodes())], 'migrations': records}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Grafo para banco vazio, sem nenhuma conexão.')
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        identity = None
        if not args.offline:
            parameters = target_parameters(os.environ)
            identity = inspect_target(parameters)
            parameters.clear()
        result = migration_plan()
        result['identity'] = identity
        result['destination_verified'] = identity is not None
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except SafetyError as error:
        print('PRECHECK_RECUSADO: ' + str(error), file=sys.stderr)
    except Exception:
        # Driver exceptions can contain connection strings; never print them.
        print('PRECHECK_RECUSADO: falha de conexão, TLS ou grafo; nenhum detalhe sensível foi registrado.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
