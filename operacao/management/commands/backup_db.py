import os
import gzip
import json
from datetime import datetime
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

class Command(BaseCommand):
    help = 'Gera backup integral comprimido (.json.gz) dos dados do ERP com rotação automática.'

    def add_arguments(self, parser):
        parser.add_argument('--retention', type=int, default=14, help='Quantidade máxima de backups mantidos (padrão: 14)')
        parser.add_argument('--output-dir', type=str, default='', help='Diretório personalizado para salvar os backups')

    def handle(self, *args, **options):
        retention = options['retention']
        custom_dir = options['output_dir']
        
        backup_dir = custom_dir if custom_dir else os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"backup_vertyx_{timestamp}.json.gz"
        filepath = os.path.join(backup_dir, filename)
        
        self.stdout.write(f"Iniciando backup em: {filename}...")
        
        try:
            # Dump de dados do Django em stream comprimido com gzip
            from io import StringIO
            buffer = StringIO()
            
            # Exporta todas as tabelas essenciais excluindo contenttypes e sessões efêmeras
            call_command(
                'dumpdata',
                natural_foreign=True,
                natural_primary=True,
                indent=2,
                exclude=['contenttypes', 'sessions', 'admin.logentry', 'auth.permission'],
                stdout=buffer
            )
            
            data_str = buffer.getvalue()
            with gzip.open(filepath, 'wt', encoding='utf-8') as f:
                f.write(data_str)
                
            file_size_kb = os.path.getsize(filepath) / 1024
            self.stdout.write(self.style.SUCCESS(
                f"Backup gerado com sucesso: {filename} ({file_size_kb:.1f} KB)"
            ))
            
            # Rotação de backups antigos (mantém os últimos N)
            existing_backups = sorted([
                f for f in os.listdir(backup_dir)
                if f.startswith('backup_vertyx_') and f.endswith('.json.gz')
            ])
            
            if len(existing_backups) > retention:
                to_remove = existing_backups[:-retention]
                for old_file in to_remove:
                    try:
                        os.remove(os.path.join(backup_dir, old_file))
                        self.stdout.write(f"Backup antigo removido pela política de retenção: {old_file}")
                    except OSError:
                        pass
                        
            return json.dumps({
                'status': 'success',
                'filename': filename,
                'path': filepath,
                'size_kb': round(file_size_kb, 2),
                'timestamp': timestamp,
            })
            
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Erro ao gerar backup: {exc}"))
            raise CommandError(str(exc))
