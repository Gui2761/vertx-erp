"""
Configurações do projeto TECNOLMED Gestão Clínica (ERP de assistência técnica).
"""
from pathlib import Path
from decouple import config, Csv
from django.core.exceptions import ImproperlyConfigured
from .deployment import postgres_database, upload_storage, validate_public_settings

BASE_DIR = Path(__file__).resolve().parent.parent

MUNICIPAL_HEALTH_ENCRYPTION_KEY = config('MUNICIPAL_HEALTH_ENCRYPTION_KEY', default='')

RENDER_EXTERNAL_HOSTNAME = config("RENDER_EXTERNAL_HOSTNAME", default=None)
DEBUG = config("DEBUG", default=not bool(RENDER_EXTERNAL_HOSTNAME), cast=bool)
SECRET_KEY = config("SECRET_KEY", default="dev-secret-key-nao-use-em-producao" if DEBUG else '')
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1" if DEBUG else '', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
# Optional one-time bootstrap gate for the first VERTYX platform administrator.
# Keep this value in the process environment/secret store, never in source control.
PLATFORM_BOOTSTRAP_TOKEN = config('PLATFORM_BOOTSTRAP_TOKEN', default='')
# Optional one-time bootstrap gate for the first VERTYX platform administrator.
# Keep this value in the process environment/secret store, never in source control.
PLATFORM_BOOTSTRAP_TOKEN = config('PLATFORM_BOOTSTRAP_TOKEN', default='')

# O Render injeta automaticamente o nome público do serviço nesta variável;
# adicionamos aos hosts/origens confiáveis sem precisar editar nada manualmente.
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')
validate_public_settings(SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "widget_tweaks",
    "django_htmx",
    # apps do sistema
    "contas",
    "clientes",
    "equipamentos",
    "core",
    "ordens",
    "platform_core",
    "gestao",
    "operacao",
    "rh_municipal",
    "commercial",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "platform_core.middleware.OrganizationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "tecnolmed.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "operacao.navigation.menu",
                "platform_core.contingency.context",
            ],
        },
    },
]

WSGI_APPLICATION = "tecnolmed.wsgi.application"

DATABASES = {'default': postgres_database(config, DEBUG)}

AUTH_USER_MODEL = "contas.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = config("TIME_ZONE", default="America/Maceio")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(config('MEDIA_ROOT', default=str(BASE_DIR / 'media')))
PRIVATE_MEDIA_ROOT = Path(config("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "media_private")))
# Definição BACKEND/OPTIONS opcional de Django Storage (ex.: bucket privado S3).
# Credenciais devem vir do ambiente/provedor, nunca de valores versionados.
PRIVATE_STORAGE = upload_storage(config, DEBUG)
if PRIVATE_STORAGE:
    from copy import deepcopy
    STORAGES['default'] = deepcopy(PRIVATE_STORAGE)
    STORAGES['default']['OPTIONS']['location'] = 'media'
    PRIVATE_STORAGE['OPTIONS']['location'] = 'private'
# Compatibilidade da variável legada; o PDF usa Organization.logo_key.
TECNOLMED_LOGO_PATH = config("TECNOLMED_LOGO_PATH", default="")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "contas:login"
LOGIN_REDIRECT_URL = "platform_core:home"
LOGOUT_REDIRECT_URL = "contas:login"

# Segurança para rodar atrás do proxy HTTPS do Render (ou qualquer PaaS
# equivalente). Em desenvolvimento local (DEBUG=True) isso fica desativado.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_REDIRECT_EXEMPT = [r'^health/$']
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
    SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
    SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

from platform_core.logging_utils import logging_config
LOGGING = logging_config(config('LOG_LEVEL', default='INFO'))

# Formatação de datas e números no padrão brasileiro
USE_THOUSAND_SEPARATOR = True
DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"
SHORT_DATE_FORMAT = "d/m/Y"

# Desativado na versão candidata. O entrypoint de contingência é explícito.
CONTINGENCIA_JORNADA_CONTRATUAL = False
