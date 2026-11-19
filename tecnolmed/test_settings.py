"""Ambiente isolado de validação; não altera a configuração PostgreSQL de produção."""
import os
os.environ['DEBUG'] = 'True'
os.environ['UPLOAD_STORAGE'] = 'local'
from .settings import *  # noqa

database_url = os.environ.get('DATABASE_URL', '').strip()
if database_url:
    import dj_database_url
    DATABASES = {'default': dj_database_url.parse(database_url)}
    if not DATABASES['default'].get('HOST'):
        DATABASES['default']['HOST'] = '127.0.0.1'
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'test_validation.sqlite3',
            'HOST': '127.0.0.1',
        }
    }

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver'] + OFFICIAL_VERTYX_DOMAINS
DEBUG = True
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
