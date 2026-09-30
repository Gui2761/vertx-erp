from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('contas', '0002_tecnico_organization_alter_tecnico_usuario_and_more'), ('platform_core', '0002_tecnolmed_backfill')]
    operations = [migrations.AlterField(model_name='tecnico', name='organization', field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='platform_core.organization'))]
