from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from django.core.files.storage import Storage, storages


@deconstructible
class PrivateStorage(Storage):
    @property
    def backend(self):
        definition = getattr(settings, 'PRIVATE_STORAGE', None)
        if definition:
            return storages.create_storage(definition)
        return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)

    def _open(self, name, mode='rb'):
        return self.backend.open(name, mode)

    def _save(self, name, content):
        return self.backend.save(name, content)

    def exists(self, name):
        return self.backend.exists(name)

    def size(self, name):
        return self.backend.size(name)

    def delete(self, name):
        return self.backend.delete(name)

    def url(self, name):
        raise ValueError('Arquivos privados exigem acesso pela view autenticada.')


private_storage = PrivateStorage()
