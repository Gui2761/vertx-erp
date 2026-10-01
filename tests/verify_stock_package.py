"""Verifica ZIP novo, migrations e exclusão de dados privados locais."""
import hashlib, json, zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
package=root.parent/'vertyx_estoque_gestao.zip'
secrets=set()
for name in ['local_test_environment.json','https_test_environment.json']:
    values=json.loads((root/'tmp/provision'/name).read_text())
    secrets.update(values[key].encode() for key in ['SECRET_KEY','DATABASE_URL','POSTGRES_PASSWORD','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','BROWSER_TEST_PASSWORD'] if values.get(key))
for path in (root/'tmp/validation').glob('browser-result*.json'):
    secrets.update(cookie['value'].encode() for cookie in json.loads(path.read_text()).get('cookies',[]))
with zipfile.ZipFile(package) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist())==len(set(archive.namelist()))
    for entry in archive.infolist():
        relative=Path(entry.filename.removeprefix('tecnolmed_erp/'))
        assert not relative.is_absolute() and '..' not in relative.parts
        assert not set(relative.parts)&{'tmp','.venv','__pycache__','media','media_private','staticfiles','.git'}
        assert relative.suffix not in ['.pyc','.sqlite3','.key','.pem','.crt']
        assert not relative.name.startswith('.env') or relative.name=='.env.example'
        content=archive.read(entry)
        assert content==(root/relative).read_bytes(),str(relative)
        assert all(secret not in content for secret in secrets if len(secret)>10),str(relative)
    count=len(archive.infolist())
manifest=json.loads((root/'AUDITORIA_ESTOQUE_ARQUIVOS.json').read_text(encoding='utf-8'))
assert manifest['arquivos_removidos']==[]
for name,expected in manifest['sha256_migrations_originais'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected
with zipfile.ZipFile(root.parent/'vertyx_final.zip') as previous:
    assert previous.read('tecnolmed_erp/render.yaml')==(root/'render.yaml').read_bytes()
result={'package':package.name,'files':count,'crc':'PASS','live_source_match':'PASS','original_migrations':'PASS','excluded_private_data':'PASS','known_local_secrets_and_sessions_absent':'PASS','render_yaml_preserved':'PASS','bytes':package.stat().st_size,'sha256':hashlib.sha256(package.read_bytes()).hexdigest()}
(root/'tmp/validation/stock-package-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
