"""Homologation without persistent file storage. No disk or cloud fallback."""
from django.conf import settings
from django.core.files.storage import Storage
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

UPLOADS_DISABLED_MESSAGE = (
    'Uploads de fotos, documentos e logos estão desativados nesta homologação. '
    'Nenhum arquivo foi salvo. As demais operações continuam disponíveis.'
)


class UploadsDisabled(OSError):
    pass


class DisabledStorage(Storage):
    def __init__(self, **kwargs):
        pass

    def _save(self, name, content):
        raise UploadsDisabled(UPLOADS_DISABLED_MESSAGE)

    def _open(self, name, mode='rb'):
        raise UploadsDisabled('Arquivos não estão disponíveis nesta homologação sem armazenamento.')

    def exists(self, name):
        return False

    def delete(self, name):
        raise UploadsDisabled(UPLOADS_DISABLED_MESSAGE)

    def size(self, name):
        raise UploadsDisabled('Arquivo indisponível nesta homologação.')

    def url(self, name):
        return ''


class DisabledUploadHandler(FileUploadHandler):
    def new_file(self, *args, **kwargs):
        self.request._disabled_upload_attempt = True
        # Reject before receiving/storing file chunks, including large files.
        raise StopUpload(connection_reset=False)

    def receive_data_chunk(self, raw_data, start):
        raise StopUpload(connection_reset=False)

    def file_complete(self, file_size):
        return None


def disabled_response(request, message=UPLOADS_DISABLED_MESSAGE):
    response = render(request, 'uploads_disabled.html', {'upload_message': message}, status=409)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class DisabledUploadsMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(settings, 'FILE_UPLOADS_ENABLED', True) and request.method in ('POST', 'PUT', 'PATCH'):
            files = request.FILES
            if files or getattr(request, '_disabled_upload_attempt', False):
                return disabled_response(request)

    def process_exception(self, request, exception):
        if not getattr(settings, 'FILE_UPLOADS_ENABLED', True) and isinstance(exception, UploadsDisabled):
            return disabled_response(request)


def upload_context(request):
    return {'uploads_disabled': not getattr(settings, 'FILE_UPLOADS_ENABLED', True)}
