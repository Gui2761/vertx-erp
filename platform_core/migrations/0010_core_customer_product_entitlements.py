from django.db import migrations


CORE_MODULES = ('clientes', 'produtos')


def include_customer_product_core(apps, schema_editor):
    database = schema_editor.connection.alias
    Plan = apps.get_model('platform_core', 'PlanoSaaS')
    for plan in Plan.objects.using(database).all():
        modules = list(plan.modulos or [])
        changed = False
        for code in CORE_MODULES:
            if code not in modules:
                modules.append(code)
                changed = True
        if changed:
            Plan.objects.using(database).filter(pk=plan.pk).update(modulos=modules)


class Migration(migrations.Migration):
    dependencies = [('platform_core', '0009_core_modules_all_plans')]

    operations = [
        migrations.RunPython(include_customer_product_core, migrations.RunPython.noop),
    ]
