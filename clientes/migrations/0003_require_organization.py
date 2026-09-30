from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('clientes', '0002_cliente_organization_alter_cliente_cpf_cnpj_and_more'), ('platform_core', '0002_tecnolmed_backfill')]
    operations = [migrations.AlterField(model_name='cliente', name='organization', field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='platform_core.organization'))]
