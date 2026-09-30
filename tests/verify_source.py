"""Compara o código com o ZIP original e gera um pacote sem dados de validação."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
original = Path(sys.argv[1])
destination = Path(sys.argv[2])
manifest_name = sys.argv[3] if len(sys.argv) > 3 else 'AUDITORIA_ARQUIVOS.json'
assert Path(manifest_name).name == manifest_name and manifest_name.endswith('.json')
excluded = {'__pycache__', '.git', '.venv', 'tmp', 'media', 'media_private', 'staticfiles'}


def source(path):
    relative = path.relative_to(root)
    return not any(part in excluded for part in relative.parts) and path.suffix not in {'.pyc', '.sqlite3'} and (not path.name.startswith('.env') or path.name == '.env.example')


unchanged, modified, removed, migration_hashes = [], [], [], {}
with zipfile.ZipFile(original) as archive:
    originals = {}
    for entry in archive.infolist():
        if entry.is_dir():
            continue
        name = entry.filename.removeprefix('tecnolmed_erp/')
        raw = archive.read(entry)
        originals[name] = raw
        target = root / name
        if not target.is_file():
            removed.append(name)
        elif target.read_bytes() == raw:
            unchanged.append(name)
        else:
            modified.append(name)
        if '/migrations/' in name:
            assert target.is_file() and target.read_bytes() == raw, f'Migration original alterada: {name}'
            migration_hashes[name] = hashlib.sha256(raw).hexdigest()
assert not removed, f'Arquivos originais ausentes: {removed}'
new = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and source(p) and p.relative_to(root).as_posix() not in originals)
manifest = {'referencia': original.name, 'arquivos_preservados': sorted(unchanged), 'arquivos_modificados': sorted(modified), 'arquivos_criados': sorted(set(new + [manifest_name])), 'arquivos_removidos': removed, 'sha256_migrations_originais': migration_hashes}
(root / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        if path.is_file() and source(path):
            archive.write(path, 'tecnolmed_erp/' + path.relative_to(root).as_posix())
print(json.dumps({'preservados': len(unchanged), 'modificados': len(modified), 'novos': len(manifest['arquivos_criados']), 'removidos': len(removed), 'migrations_originais_intactas': True, 'pacote': destination.name}, ensure_ascii=False))
