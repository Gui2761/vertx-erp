"""Compatibilidade das URLs antigas, agora autenticadas e filtradas por tenant."""
import mimetypes
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from equipamentos.models import Equipamento
from .access import require_erp
from .logging_utils import operation_failure


@login_required
def legacy_media(request, name):
    require_erp(request.user)
    from operacao.technician_access import scoped_records
    organization = request.organization
    if name == organization.logo_key and name.startswith(f'organizations/{organization.public_id}/branding/'):
        from ordens.storage import private_storage
        return private_file_response(private_storage.open, name)
    equipment = scoped_records(request.user, Equipamento.objects.filter(Q(foto=name) | Q(manual=name) | Q(qr_code=name)), 'equipamento').first()
    if not equipment:
        raise Http404()
    field = next(getattr(equipment, key) for key in ['foto', 'manual', 'qr_code'] if getattr(equipment, key).name == name)
    try:
        response = FileResponse(field.open('rb'), content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream', as_attachment=field is equipment.manual)
    except FileNotFoundError:
        raise Http404()
    except OSError as exc:
        operation_failure('equipment_download_failed', exc)
        return HttpResponse('Arquivo indisponível. Tente novamente.', status=503)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def private_file_response(opener, name):
    try:
        response = FileResponse(opener(name, 'rb'), content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
    except FileNotFoundError:
        raise Http404()
    except OSError as exc:
        operation_failure('branding_download_failed', exc)
        return HttpResponse('Arquivo indisponível. Tente novamente.', status=503, headers={'Cache-Control': 'private, no-store'})
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
