"""Preenche apenas o novo vínculo raiz; não altera contas, valores ou parcelas."""
from django.db import migrations


def populate_roots(apps, schema_editor):
    Entry = apps.get_model('gestao', 'Lancamento')
    Installment = apps.get_model('operacao', 'Parcela')
    database = schema_editor.connection.alias
    entries = {row['id']: row for row in Entry._base_manager.using(database).values('id','organization_id','origem_raiz_id')}
    parents = {}
    for row in Installment._base_manager.using(database).values('organization_id','lancamento_id','origem_id'):
        child, parent = entries[row['lancamento_id']], entries[row['origem_id']]
        if child['organization_id'] != parent['organization_id'] or child['organization_id'] != row['organization_id']:
            raise RuntimeError('Vínculo de parcela incompatível com organização; migration interrompida.')
        parents[child['id']] = parent['id']
    updates = []
    for child in parents:
        if entries[child]['origem_raiz_id']:
            continue
        root, seen = child, set()
        while root in parents:
            if root in seen:
                raise RuntimeError('Ciclo na origem de parcelas; migration interrompida.')
            seen.add(root)
            root = parents[root]
        updates.append((child, root))
    for child, root in updates:
        Entry._base_manager.using(database).filter(pk=child, origem_raiz__isnull=True).update(origem_raiz_id=root)


class Migration(migrations.Migration):
    dependencies = [('gestao','0006_estabilizacao_bloco1'), ('operacao','0006_estabilizacao_bloco1')]
    operations = [migrations.RunPython(populate_roots, migrations.RunPython.noop)]
