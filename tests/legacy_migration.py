"""Migration forward-only em banco temporário: nenhum banco existente é revertido."""
import copy
import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['DJANGO_SETTINGS_MODULE'] = os.environ.get('VERTYX_LEGACY_SETTINGS_MODULE', 'tecnolmed.test_settings')
import django
django.setup()
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


def verify():
    with tempfile.TemporaryDirectory() as directory:
        alias = 'legacy_validation'
        database = copy.deepcopy(connections.databases['default'])
        postgres = connections['default'].vendor == 'postgresql'
        temporary_name = 'legacy_validation_' + uuid.uuid4().hex
        created = False
        if postgres:
            with connections['default'].cursor() as cursor:
                cursor.execute('CREATE DATABASE ' + connections['default'].ops.quote_name(temporary_name))
            created = True
            database['NAME'] = temporary_name
        else:
            database['NAME'] = str(Path(directory) / 'legacy.sqlite3')
        connections.databases[alias] = database
        connection = connections[alias]
        try:
            executor = MigrationExecutor(connection)
            initial = [('ordens', '0002_localizacao_geo_resultado_coerente_and_more')]
            executor.migrate(initial)
            old = executor.loader.project_state(initial).apps
            def create(app, name, **kwargs):
                return old.get_model(app, name).objects.using(alias).create(**kwargs)
            user = create('contas', 'Usuario', username='legacy-tech', perfil='TECNICO', password='!')
            inactive = create('contas', 'Usuario', username='legacy-inactive', perfil='GESTOR', password='!', is_active=False)
            superuser = create('contas', 'Usuario', username='legacy-platform', perfil='ADMIN', password='!', is_superuser=True, is_staff=True)
            client = create('clientes', 'Cliente', nome_razao_social='Cliente legado', cpf_cnpj='LEGACY')
            unit = create('clientes', 'Unidade', cliente=client, nome='Unidade legada')
            contact = create('clientes', 'ContatoCliente', cliente=client, nome='Contato legado')
            category = create('equipamentos', 'CategoriaEquipamento', nome='Categoria legada')
            equipment = create('equipamentos', 'Equipamento', cliente=client, unidade=unit, categoria=category, nome='Equipamento legado', manual='equipamentos/manuais/old.pdf')
            tech = create('contas', 'Tecnico', nome='Técnico legado', usuario=user)
            order = create('ordens', 'OrdemServico', cliente=client, unidade=unit, equipamento=equipment, tecnico=tech, defeito='Defeito legado', diagnostico='Diagnóstico legado', servico_executado='Serviço legado', status='FINALIZADA', inicio=timezone.now(), conclusao=timezone.now())
            geo = create('ordens', 'Localizacao', ordem=order, ciclo=1, evento='FINAL', resultado='NEGADA', usuario=user)
            photo = create('ordens', 'Foto', ordem=order, usuario=user, arquivo='ordens/legacy/old.jpg', descricao='Foto legada', sha256='f' * 64)
            snapshot = {'numero': 'OS-000001', 'cliente': 'Cliente legado', 'fotos': [{'id': photo.pk, 'sha256': photo.sha256}]}
            digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            conference = create('ordens', 'Conferencia', ordem=order, usuario=user, revisao=1, ciclo=1, dados=snapshot, digest=digest, localizacao_final=geo)
            signature = create('ordens', 'Assinatura', ordem=order, conferencia=conference, ciclo=1, nome='Responsável legado', cargo='Gerente', imagem='LEGACY-IMAGE-UNCHANGED', imagem_sha256='a' * 64, usuario=user)
            audit = create('ordens', 'Auditoria', ordem=order, usuario=user, acao='FINALIZACAO', alteracoes={'original': 'preservado'})
            preserved = {name: item.pk for name, item in [('Cliente', client), ('Unidade', unit), ('Equipamento', equipment), ('Foto', photo), ('Assinatura', signature), ('Auditoria', audit)]}
            executor = MigrationExecutor(connection)
            final = executor.loader.graph.leaf_nodes()
            executor.migrate(final)
            new = executor.loader.project_state(final).apps
            org = new.get_model('platform_core', 'Organization').objects.using(alias).get(slug='tecnolmed')
            catalog = new.get_model('platform_core', 'ERPCatalog')
            assistance = catalog.objects.using(alias).get(code='assistencia')
            assert 'entry_path' in {field.name for field in catalog._meta.get_fields()}
            assert assistance.entry_path == '/assistencia/'
            for app, name, original in [('clientes', 'Cliente', client), ('equipamentos', 'CategoriaEquipamento', category), ('equipamentos', 'Equipamento', equipment), ('contas', 'Tecnico', tech), ('ordens', 'OrdemServico', order)]:
                item = new.get_model(app, name).objects.using(alias).get(pk=original.pk)
                assert item.organization_id == org.pk
            for app, name, original in [('clientes', 'Unidade', unit), ('clientes', 'ContatoCliente', contact), ('ordens', 'Localizacao', geo), ('ordens', 'Foto', photo), ('ordens', 'Conferencia', conference), ('ordens', 'Assinatura', signature), ('ordens', 'Auditoria', audit)]:
                assert new.get_model(app, name).objects.using(alias).filter(pk=original.pk).exists()
            migrated_conference = new.get_model('ordens', 'Conferencia').objects.using(alias).get(pk=conference.pk)
            assert migrated_conference.dados == snapshot and migrated_conference.digest == digest
            assert migrated_conference.issuer['nome'] == 'TECNOLMED'
            assert new.get_model('ordens', 'Assinatura').objects.using(alias).get(pk=signature.pk).imagem == 'LEGACY-IMAGE-UNCHANGED'
            assert new.get_model('ordens', 'Foto').objects.using(alias).get(pk=photo.pk).arquivo.name == 'ordens/legacy/old.jpg'
            assert new.get_model('equipamentos', 'Equipamento').objects.using(alias).get(pk=equipment.pk).manual.name == 'equipamentos/manuais/old.pdf'
            membership_model = new.get_model('platform_core', 'OrganizationMembership')
            assert membership_model.objects.using(alias).get(user_id=user.pk).role == 'TECNICO'
            assert membership_model.objects.using(alias).get(user_id=inactive.pk).status == 'INATIVO'
            assert not membership_model.objects.using(alias).filter(user_id=superuser.pk).exists()
            print(json.dumps({'legacy_upgrade': 'PASS', 'backend': connection.vendor, 'organization': org.slug, 'ids_preserved': preserved, 'snapshot_and_digest_preserved': True, 'files_unchanged': True, 'superuser_not_enrolled': True}))
        finally:
            connection.close()
            del connections[alias]
            connections.databases.pop(alias, None)
            if created:
                assert temporary_name.startswith('legacy_validation_') and len(temporary_name) == 50
                with connections['default'].cursor() as cursor:
                    cursor.execute('DROP DATABASE ' + connections['default'].ops.quote_name(temporary_name))


if __name__ == '__main__':
    verify()
