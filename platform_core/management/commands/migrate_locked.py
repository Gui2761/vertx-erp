"""Serializa migrations de deploy com advisory lock na sessão PostgreSQL."""
import time
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection

LOCK_ID = 864210730


class Command(BaseCommand):
    help = 'Aplica migrations versionadas, evitando dois migradores simultâneos.'

    def add_arguments(self, parser):
        parser.add_argument('--noinput', action='store_true')
        parser.add_argument('--lock-timeout', type=int, default=120)

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('migrate_locked exige PostgreSQL; use migrate em testes SQLite explícitos.')
        deadline = time.monotonic() + options['lock_timeout']
        acquired = False
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute('SELECT pg_try_advisory_lock(%s)', [LOCK_ID])
                if cursor.fetchone()[0]:
                    acquired = True
                    break
                time.sleep(.5)
        if not acquired:
            raise CommandError('Outro processo está migrando. Tente novamente após o deploy atual.')
        try:
            call_command('migrate', interactive=not options['noinput'], verbosity=options['verbosity'])
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [LOCK_ID])
