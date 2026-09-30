from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('ordens', '0004_conferencia_issuer'), ('platform_core', '0002_tecnolmed_backfill')]
    operations = [migrations.AlterField(model_name='ordemservico', name='organization', field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='platform_core.organization'))]
