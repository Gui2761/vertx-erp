from .models import PlatformAudit, ERPCatalog


def previous_values(form):
    if not form.instance.pk:
        return {}
    previous = type(form.instance).objects.get(pk=form.instance.pk)
    return {name: str(getattr(previous, name, '')) for name in form.changed_data if name not in ['password', 'password1', 'password2']}


def record_write(request, instance, previous):
    changed = {name: {'anterior': old, 'posterior': str(getattr(instance, name, ''))} for name, old in previous.items() if old != str(getattr(instance, name, ''))}
    if not previous:
        changed = {field.name: {'anterior': None, 'posterior': str(getattr(instance, field.name, ''))} for field in instance._meta.concrete_fields if field.name not in ['password','password1','password2'] and (field.editable or field.name == 'id')}
    PlatformAudit.objects.create(organization=request.organization, erp=ERPCatalog.objects.get(code='assistencia'), user=request.user, action='CADASTRO_ALTERADO' if previous else 'CADASTRO_SALVO', record=f'{instance._meta.label}:{instance.pk}', changes=changed)
