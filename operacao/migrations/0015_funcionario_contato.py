from django.db import migrations, models


def preserve_contacts(apps, schema_editor):
    employee = apps.get_model('operacao', 'Funcionario')
    alias = schema_editor.connection.alias
    for row in employee._base_manager.using(alias).select_related('usuario').iterator():
        employee._base_manager.using(alias).filter(pk=row.pk).update(
            telefone=row.usuario.telefone, email=row.usuario.email)


class Migration(migrations.Migration):
    dependencies = [('operacao', '0014_piloto_jornada_contratual')]
    operations = [
        migrations.AddField(model_name='funcionario', name='telefone',
                            field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='funcionario', name='email',
                            field=models.EmailField(blank=True, max_length=254)),
        migrations.RunPython(preserve_contacts, migrations.RunPython.noop),
    ]
