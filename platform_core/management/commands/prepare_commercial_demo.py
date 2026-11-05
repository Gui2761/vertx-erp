"""Operator-only setup. Never called automatically; writes no invitation to stdout."""
import json
import os
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction, DatabaseError
from django.urls import reverse
from platform_core.commercial_demo import preparar_demo


class Command(BaseCommand):
    help = 'Prepara DEMO fictícia em banco de homologação explicitamente confirmado.'

    def add_arguments(self, parser):
        parser.add_argument('--accounts-json', required=True)
        parser.add_argument('--expected-host', required=True)
        parser.add_argument('--expected-database', required=True)
        parser.add_argument('--private-output', required=True)
        parser.add_argument('--confirm-demo-database', action='store_true')

    def handle(self, *args, **opts):
        if not opts['confirm_demo_database'] or not getattr(settings, 'COMMERCIAL_DEMO_ENABLED', False):
            raise CommandError('Exige confirmação explícita e settings de homologação.')
        cfg = connection.settings_dict
        if connection.vendor != 'postgresql' or cfg['HOST'] != opts['expected_host'] or cfg['NAME'] != opts['expected_database']:
            raise CommandError('A conexão default não coincide com o banco confirmado.')
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), inet_server_port(), current_setting('server_version_num')::int, pg_is_in_recovery()")
            name, port, version, recovery = cursor.fetchone()
        if name != opts['expected_database'] or port != int(cfg.get('PORT') or 5432) or not 160000 <= version < 170000 or recovery:
            raise CommandError('Identidade ou estado do PostgreSQL incompatível.')
        target = Path(opts['private_output']).resolve()
        source = Path(opts['accounts_json']).resolve()
        if any(p.is_relative_to(Path(settings.BASE_DIR).resolve()) for p in (source, target)):
            raise CommandError('Os arquivos de entrada e saída devem ficar fora do repositório/imagem.')
        try:
            accounts = json.loads(source.read_text(encoding='utf-8-sig'))
            # Exclusive creation prevents overwriting previous links; mode 0600 on Linux.
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as out, transaction.atomic():
                org, people = preparar_demo(accounts)
                json.dump({'organization_id':org.pk, 'invitations':[
                    {'email':p['user'].email, 'role':p['membership'].role,
                     'url':'https://vertyx-erp.onrender.com'+reverse('platform_core:saas_first_access', args=[p['token']])}
                    for p in people]}, out)
                out.flush()
                os.fsync(out.fileno())
        except (OSError, ValueError, KeyError, TypeError, ValidationError, DatabaseError):
            raise CommandError('Preparação não concluída. Confira o arquivo de entrada e o destino privado; verifique o estado antes de repetir. Não sobrescreva convites existentes.') from None
        self.stdout.write(self.style.SUCCESS('Organização DEMO e três contas preparadas; convites somente no arquivo privado.'))
