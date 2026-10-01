"""Confere pacote atual, source, migrations anteriores e exclusão de dados locais."""
import hashlib,json,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
package=root.parent/'vertyx_central_operacoes.zip'
secrets=set()
for name in ['local_test_environment.json','https_test_environment.json']:
    values=json.loads((root/'tmp/provision'/name).read_text())
    secrets.update(values[key].encode() for key in ['SECRET_KEY','DATABASE_URL','POSTGRES_PASSWORD','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','BROWSER_TEST_PASSWORD'] if values.get(key))
for path in (root/'tmp/validation').glob('browser-result*.json'):
    secrets.update(cookie['value'].encode() for cookie in json.loads(path.read_text()).get('cookies',[]))
manifest=json.loads((root/'AUDITORIA_OPERACOES_ARQUIVOS.json').read_text(encoding='utf-8'))
assert not manifest['arquivos_removidos']
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
for name,expected in manifest['sha256_migrations_originais'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected
with zipfile.ZipFile(root.parent/'vertyx_estoque_gestao.zip') as previous:
    for name in ['render.yaml','docker-compose.yml','.env.example','AUTOMACAO_ESTOQUE.md','operacao/stock.py','operacao/stock_scheduler.py']:
        assert previous.read('tecnolmed_erp/'+name)==(root/name).read_bytes(),name
    assert hashlib.sha256((root.parent/'vertyx_estoque_gestao.zip').read_bytes()).hexdigest()=='3a8249c4be2cfa82c86f801c9d6fb7393ae05b9ce43682a5e19bddf322160a52'
result={'package':package.name,'files':count,'crc':'PASS','source_match':'PASS','prior_migrations':'PASS','original_package_preserved':'PASS','stock_services_scheduler_infrastructure_preserved':'PASS','private_data_excluded':'PASS','known_local_secrets_and_sessions_absent':'PASS','bytes':package.stat().st_size,'sha256':hashlib.sha256(package.read_bytes()).hexdigest()}
(root/'tmp/validation/operations-package-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
