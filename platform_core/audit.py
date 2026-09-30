from .models import PlatformAudit, ERPCatalog


def previous_values(form):
    if not form.instance.pk:
        return {}
    previous = type(form.instance).objects.get(pk=form.instance.pk)
    return {name: str(getattr(previous, name, '')) for name in form.changed_data if name not in ['password', 'password1', 'password2']}


def record_write(request, instance, previous):
    changed = {name: {'anterior': old, 'posterior': str(getattr(instance, name, ''))} for name, old in previous.items() if old != str(getattr(instance, name, ''))}
    PlatformAudit.objects.create(organization=request.organization, erp=ERPCatalog.objects.get(code='assistencia'), user=request.user, action='CADASTRO_ALTERADO' if previous else 'CADASTRO_SALVO', record=f'{instance._meta.label}:{instance.pk}', changes=changed)
