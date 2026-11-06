"""Uploads S3 privados; links apontam para a autorização Django, não para o bucket."""
from contextlib import contextmanager
import re
from botocore.exceptions import BotoCoreError, ClientError
from storages.backends.s3 import S3Storage
from django.urls import reverse
from .logging_utils import operation_failure


class StorageUnavailable(OSError):
    pass


@contextmanager
def storage_operation(event):
    try:
        yield
    except ClientError as exc:
        operation_failure(event, exc)
        if exc.response.get('Error', {}).get('Code') in ['404', 'NoSuchKey', 'NotFound']:
            raise FileNotFoundError('Arquivo privado indisponível.') from None
        raise StorageUnavailable('Armazenamento privado indisponível.') from None
    except BotoCoreError as exc:
        operation_failure(event, exc)
        raise StorageUnavailable('Armazenamento privado indisponível.') from None


class AuthenticatedS3Storage(S3Storage):
    def usage_bytes(self, prefix):
        """Measure one tenant with S3 V2 pagination, without downloading objects."""
        if not isinstance(prefix, str) or not re.fullmatch(
                r'organizations/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/', prefix):
            raise ValueError('Prefixo de medição inválido.')
        with storage_operation('storage_usage_failed'):
            # Respect the storage location (private/media), including its slash
            # boundary. No bucket-wide listing or per-object HEAD is necessary.
            path = self._normalize_name(prefix)
            paginator = self.connection.meta.client.get_paginator('list_objects_v2')
            total = 0
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=path):
                for item in page.get('Contents', ()):
                    key, size = item.get('Key'), item.get('Size')
                    if (not isinstance(key, str) or not key.startswith(path)
                            or type(size) is not int or size < 0):
                        raise ValueError('Resposta de medição inválida.')
                    total += size
            return total

    def url(self, name, parameters=None, expire=None, http_method=None):
        return reverse('legacy_media', kwargs={'name': name})

    def _open(self, name, mode='rb'):
        with storage_operation('storage_open_failed'):
            handle = super()._open(name, mode)
            try:
                if 'r' in mode:
                    handle.file  # Baixa antes de enviar headers; falhas podem retornar 503.
                return handle
            except Exception:
                handle.close()
                raise

    def _save(self, name, content):
        with storage_operation('storage_upload_failed'):
            return super()._save(name, content)

    def exists(self, name):
        with storage_operation('storage_exists_failed'):
            return super().exists(name)

    def size(self, name):
        with storage_operation('storage_metadata_failed'):
            return super().size(name)

    def delete(self, name):
        with storage_operation('storage_delete_failed'):
            return super().delete(name)
