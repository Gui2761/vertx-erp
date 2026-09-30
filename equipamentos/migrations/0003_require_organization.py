from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('equipamentos', '0002_categoriaequipamento_organization_and_more'), ('platform_core', '0002_tecnolmed_backfill')]
    operations = [migrations.AlterField(model_name=model, name='organization', field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='platform_core.organization')) for model in ['categoriaequipamento', 'equipamento']]
