import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('rh_municipal', '0015_agendamentoregulacaosaude')]

    operations = [
        migrations.AlterField(
            model_name='itemprescricaosaude', name='medicamento_nome',
            field=models.CharField(max_length=140, blank=True),
        ),
        migrations.AddField(
            model_name='itemprescricaosaude', name='medicamento_nome_cifrado',
            field=models.BinaryField(blank=True, default=bytes),
        ),
        migrations.AddField(
            model_name='evolucaoclinicamunicipal', name='retifica',
            field=models.OneToOneField(blank=True, null=True,
                                      on_delete=django.db.models.deletion.PROTECT,
                                      related_name='retificacao', to='rh_municipal.evolucaoclinicamunicipal'),
        ),
    ]
