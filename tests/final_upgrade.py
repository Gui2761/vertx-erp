"""Ensaio de upgrade aditivo na base PostgreSQL local, preservando cada linha/coluna anterior."""
import hashlib
import json
import os
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
values=json.loads((root/'tmp/provision/local_test_environment.json').read_text())
assert values['DATABASE_URL'].split('@')[1]=='127.0.0.1:55432/vertyx_homologation'
os.environ.update(values)
os.environ['DJANGO_SETTINGS_MODULE']='tecnolmed.settings'
import django
django.setup()
from django.db import connection
from django.core.management import call_command
from psycopg2 import sql

snapshots=[]
with connection.cursor() as cursor:
    cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    tables=[row[0] for row in cursor.fetchall() if row[0]!='django_migrations']
    for table in tables:
        cursor.execute(sql.SQL('SELECT * FROM {} ORDER BY 1').format(sql.Identifier(table)))
        columns=[column[0] for column in cursor.description]
        snapshots.append((table,columns,cursor.fetchall()))
call_command('migrate',plan=True)
call_command('migrate_locked')
preserved=0
with connection.cursor() as cursor:
    for table,columns,rows in snapshots:
        cursor.execute(sql.SQL('SELECT {} FROM {} ORDER BY 1').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table)))
        actual=cursor.fetchall()
        identity=columns.index('id') if 'id' in columns else 0
        lookup={row[identity]:row for row in actual}
        assert all(lookup.get(row[identity])==row for row in rows),table
        preserved+=len(rows)
result={'postgresql_upgrade':'PASS','previous_tables_verified':len(snapshots),'previous_rows_preserved':preserved,'old_columns_identical':True}
(root/'tmp/validation/final-upgrade.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
