import json
import time
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, OperationalError, InterfaceError
from operacao.stock_scheduler import run, organizations

class Command(BaseCommand):
    help = 'Executa alertas e relatório semanal de estoque; --loop mantém runner local independente.'
    def add_arguments(self, parser):
        parser.add_argument('--organization')
        parser.add_argument('--loop',action='store_true')
        parser.add_argument('--poll-seconds',type=int,default=30)
    def handle(self,*args,**options):
        if not 1 <= options['poll_seconds'] <= 60:
            raise CommandError('Polling deve estar entre 1 e 60 segundos.')
        if options['organization'] and not organizations(options['organization']).exists():
            raise CommandError('Organização ativa com ERP habilitado não encontrada.')
        try:
            while True:
                close_old_connections()
                try:
                    results = run(options['organization'])
                except (OperationalError, InterfaceError) as exc:
                    results = [{'erro':type(exc).__name__}]
                self.stdout.write(json.dumps(results,ensure_ascii=False))
                if any('erro' in row for row in results) and not options['loop']:
                    raise CommandError('Execução incompleta; consulte os códigos de erro por organização.')
                if not options['loop']:
                    return
                time.sleep(options['poll_seconds'])
        except KeyboardInterrupt:
            self.stdout.write('Runner local encerrado.')
