"""Cópia verificável de uploads legados; nunca apaga origem nem altera o banco."""
import hashlib
import json
from pathlib import Path
from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.core.management import BaseCommand, CommandError
from equipamentos.models import Equipamento
from ordens.models import Foto
from ordens.storage import private_storage
from platform_core.models import Organization


def sha256(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = 'Planeja/copia uploads referenciados no banco para S3, mantendo chaves e SHA-256.'

    def add_arguments(self, parser):
        parser.add_argument('--source-private', required=True)
        parser.add_argument('--source-media', required=True)
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--apply', action='store_true', help='Sem esta opção, somente planeja a cópia.')

    def handle(self, *args, **options):
        if not settings.PRIVATE_STORAGE or not settings.PRIVATE_STORAGE['BACKEND'].endswith('AuthenticatedS3Storage'):
            raise CommandError('Configure UPLOAD_STORAGE=s3 antes de planejar/copiar os uploads.')
        references = {'private': set(Foto.all_objects.exclude(arquivo='').values_list('arquivo', flat=True)), 'media': set()}
        references['private'].update(Organization.objects.exclude(logo_key='').values_list('logo_key', flat=True))
        for fields in Equipamento.all_objects.values_list('foto', 'manual', 'qr_code').iterator():
            references['media'].update(name for name in fields if name)
        sources = {'private': FileSystemStorage(location=options['source_private']), 'media': FileSystemStorage(location=options['source_media'])}
        targets = {'private': private_storage, 'media': storages['default']}
        manifest = []
        failed = False
        for namespace, names in references.items():
            for name in sorted(names):
                if not name:
                    continue
                record = {'namespace': namespace, 'name': name}
                try:
                    with sources[namespace].open(name, 'rb') as stream:
                        checksum = sha256(stream)
                    record['sha256'] = checksum
                    destination = targets[namespace]
                    if destination.exists(name):
                        with destination.open(name, 'rb') as stream:
                            if sha256(stream) != checksum:
                                raise CommandError('Objeto existente diverge da origem; não será sobrescrito.')
                        record['status'] = 'already_verified'
                    elif options['apply']:
                        with sources[namespace].open(name, 'rb') as stream:
                            saved = destination.save(name, stream, max_length=500)
                        if saved != name:
                            raise CommandError('Colisão no destino; chaves do banco permanecem inalteradas.')
                        with destination.open(name, 'rb') as stream:
                            if sha256(stream) != checksum:
                                raise CommandError('Verificação SHA-256 da cópia falhou.')
                        record['status'] = 'copied_verified'
                    else:
                        record['status'] = 'planned'
                except (OSError, CommandError) as exc:
                    failed = True
                    record['status'] = 'failed'
                    record['error_class'] = type(exc).__name__
                manifest.append(record)
        Path(options['manifest']).write_text(json.dumps({'apply': options['apply'], 'records': manifest}, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(f'Referências verificadas: {len(manifest)}. Originais e banco preservados.')
        if failed:
            raise CommandError('Há arquivos ausentes/conflitantes/indisponíveis. Consulte o manifesto antes de trocar o storage.')
