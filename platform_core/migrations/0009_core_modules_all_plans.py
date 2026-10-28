from django.db import migrations


CORE_MODULES = (
    'assistencia',
    'estoque_basico',
    'financeiro_basico',
    'pdv',
    'fiscal',
)
CORE_COMMERCIAL_FEATURES = (
    'clientes',
    'produtos',
    'estoque',
    'pdv',
    'financeiro',
    'fiscal',
)


def include_operational_core(apps, schema_editor):
    database = schema_editor.connection.alias
    Plan = apps.get_model('platform_core', 'PlanoSaaS')
    Offer = apps.get_model('commercial', 'PlanoComercial')

    # Plans are global catalog configuration. Preserve all existing optional
    # modules, limits, prices, links, and active states.
    for plan in Plan.objects.using(database).all():
        modules = list(plan.modulos or [])
        updated = False
        for code in CORE_MODULES:
            if code not in modules:
                modules.append(code)
                updated = True
        if updated:
            Plan.objects.using(database).filter(pk=plan.pk).update(modulos=modules)

    # The public catalog describes module access, not tax authorization. Set
    # the core resources included while retaining every other catalog choice.
    for offer in Offer.objects.using(database).all():
        resources = dict(offer.recursos or {})
        updated = False
        for code in CORE_COMMERCIAL_FEATURES:
            if resources.get(code) != 'INCLUIDO':
                resources[code] = 'INCLUIDO'
                updated = True
        if updated:
            Offer.objects.using(database).filter(pk=offer.pk).update(recursos=resources)


class Migration(migrations.Migration):
    dependencies = [
        ('platform_core', '0008_expand_saas_entitlements'),
        ('commercial', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(include_operational_core, migrations.RunPython.noop),
    ]
