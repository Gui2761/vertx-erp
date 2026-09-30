"""Ambiente isolado de validação; não altera a configuração PostgreSQL de produção."""
import os
os.environ['DEBUG'] = 'True'
os.environ['UPLOAD_STORAGE'] = 'local'
from .settings import *  # noqa

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'validation.sqlite3'}}
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
DEBUG = True
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
