from django.db import migrations, models


def set_reporting_tiers(apps, schema_editor):
    Plan = apps.get_model('platform_core', 'PlanoSaaS')
    database = schema_editor.connection.alias
    commercial_tiers = {
        'basico': 'BASICO',
        'profissional': 'AVANCADO',
        'empresarial': 'COMPLETO',
    }
    for plan in Plan.objects.using(database).select_related('plano_comercial').all():
        modules = list(plan.modulos or [])
        if 'relatorios_basicos' not in modules:
            modules.append('relatorios_basicos')
        public_slug = plan.plano_comercial.slug if plan.plano_comercial_id else plan.slug
        level = commercial_tiers.get(public_slug, 'BASICO')
        Plan.objects.using(database).filter(pk=plan.pk).update(
            modulos=modules,
            nivel_indicadores=level,
        )


class Migration(migrations.Migration):
    dependencies = [('platform_core', '0011_alter_moduloorganizacao_codigo')]

    operations = [
        migrations.AddField(
            model_name='planosaas',
            name='nivel_indicadores',
            field=models.CharField(
                choices=[('BASICO', 'Básico'), ('AVANCADO', 'Avançado'), ('COMPLETO', 'Completo')],
                default='BASICO',
                help_text='Gráficos básicos estão incluídos em todos os planos; este nível controla detalhamento e comparativos.',
                max_length=12,
                verbose_name='Nível de indicadores',
            ),
        ),
        migrations.RunPython(set_reporting_tiers, migrations.RunPython.noop),
    ]
