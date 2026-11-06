"""Configuração de infraestrutura; erros não incluem valores de credenciais."""
from urllib.parse import urlsplit
from django.core.exceptions import ImproperlyConfigured
import dj_database_url


def required(config, name):
    value = config(name, default='').strip()
    if not value:
        raise ImproperlyConfigured(f'Configure {name} no ambiente.')
    return value


def postgres_database(config, debug):
    url = config('DATABASE_URL', default='').strip()
    if not url and not debug:
        raise ImproperlyConfigured('DATABASE_URL PostgreSQL é obrigatória com DEBUG=False.')
    if url:
        try:
            database = dj_database_url.parse(url)
        except (ValueError, KeyError):
            raise ImproperlyConfigured('DATABASE_URL deve ser uma URL PostgreSQL válida.') from None
        if database['ENGINE'] != 'django.db.backends.postgresql' or not database.get('NAME'):
            raise ImproperlyConfigured('Somente PostgreSQL é permitido nas settings da aplicação.')
    else:
        database = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('POSTGRES_DB', default='tecnolmed'),
            'USER': config('POSTGRES_USER', default='tecnolmed'),
            'PASSWORD': config('POSTGRES_PASSWORD', default=''),
            'HOST': config('POSTGRES_HOST', default='db'),
            'PORT': config('POSTGRES_PORT', default='5432'),
        }
    database['CONN_MAX_AGE'] = config('CONN_MAX_AGE', default=60, cast=int)
    database['CONN_HEALTH_CHECKS'] = True
    database.setdefault('OPTIONS', {})['connect_timeout'] = 5
    if config('DATABASE_SSL_REQUIRE', default=not debug, cast=bool):
        database['OPTIONS']['sslmode'] = 'require'
    return database


def upload_storage(config, debug, *, disabled=False):
    if disabled:
        # Explicit opt-in by the dedicated homologation settings only. Do not
        # even read AWS/S3 configuration or instantiate a provider client.
        return {'BACKEND': 'platform_core.uploads.DisabledStorage', 'OPTIONS': {}}
    mode = config('UPLOAD_STORAGE', default='local' if debug else '').lower()
    if mode not in ['local', 's3'] or not debug and mode != 's3':
        raise ImproperlyConfigured('Configure UPLOAD_STORAGE=s3 em homologação/produção.')
    if mode == 'local':
        return None
    from botocore.config import Config
    bucket = required(config, 'S3_BUCKET_NAME')
    region = required(config, 'S3_REGION_NAME')
    access = required(config, 'AWS_ACCESS_KEY_ID')
    secret = required(config, 'AWS_SECRET_ACCESS_KEY')
    endpoint = config('S3_ENDPOINT_URL', default='').strip() or None
    if endpoint:
        parsed = urlsplit(endpoint)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme not in (['https', 'http'] if debug else ['https']):
            raise ImproperlyConfigured('S3_ENDPOINT_URL deve ser um endpoint HTTPS sem credenciais.')
    style = config('S3_ADDRESSING_STYLE', default='path')
    if style not in ['path', 'virtual']:
        raise ImproperlyConfigured('S3_ADDRESSING_STYLE deve ser path ou virtual.')
    return {
        'BACKEND': 'platform_core.storage.AuthenticatedS3Storage',
        'OPTIONS': {
            'bucket_name': bucket, 'region_name': region, 'endpoint_url': endpoint,
            'access_key': access, 'secret_key': secret,
            'security_token': config('AWS_SESSION_TOKEN', default=None),
            'default_acl': None, 'file_overwrite': False,
            'querystring_auth': True, 'querystring_expire': 60,
            'custom_domain': None, 'max_memory_size': 5 * 1024 * 1024,
            'object_parameters': {'CacheControl': 'private, no-store'},
            'client_config': Config(
                signature_version='s3v4', s3={'addressing_style': style},
                connect_timeout=5, read_timeout=20,
                retries={'total_max_attempts': 2, 'mode': 'standard'},
                request_checksum_calculation='when_required',
                response_checksum_validation='when_required',
            ),
        },
    }


def homologation_storage(config):
    """Explicit R2 opt-in; incomplete configuration never falls back to disk/AWS."""
    mode = config('HOMOLOGATION_STORAGE', default='disabled').strip().lower()
    if mode not in ('disabled', 'r2'):
        raise ImproperlyConfigured('HOMOLOGATION_STORAGE deve ser disabled ou r2.')
    disabled = {'BACKEND': 'platform_core.uploads.DisabledStorage', 'OPTIONS': {}}
    if mode == 'disabled':
        return disabled
    names = ('S3_BUCKET_NAME', 'S3_ENDPOINT_URL', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY')
    values = {name: config(name, default='').strip() for name in names}
    if not all(values.values()):
        return disabled
    endpoint = urlsplit(values['S3_ENDPOINT_URL'])
    import re
    if (endpoint.scheme != 'https' or not re.fullmatch(r'[a-fA-F0-9]{32}\.r2\.cloudflarestorage\.com', endpoint.netloc)
            or endpoint.path not in ('', '/') or endpoint.query or endpoint.fragment):
        raise ImproperlyConfigured('S3_ENDPOINT_URL deve ser o endpoint HTTPS S3 da conta R2, sem credenciais.')
    if values['S3_BUCKET_NAME'] != 'vertyx-homologacao':
        raise ImproperlyConfigured('R2 de homologação exige o bucket vertyx-homologacao.')
    if config('S3_REGION_NAME', default='auto') != 'auto' or config('S3_ADDRESSING_STYLE', default='path') != 'path':
        raise ImproperlyConfigured('R2 de homologação exige região auto e addressing style path.')
    # Explicit values prevent inherited AWS session tokens or AWS defaults from
    # selecting a different provider. No client/network is created at startup.
    values.update(UPLOAD_STORAGE='s3', S3_REGION_NAME='auto', S3_ADDRESSING_STYLE='path', AWS_SESSION_TOKEN=None)
    def r2_config(name, default=None, cast=None):
        value = values.get(name, default)
        return cast(value) if cast else value
    return upload_storage(r2_config, False)


def validate_public_settings(secret, hosts, origins, debug):
    if debug:
        return
    if len(secret) < 50 or len(set(secret)) < 5 or secret.startswith(('dev-', 'troque-', 'django-insecure-')):
        raise ImproperlyConfigured('SECRET_KEY forte, com pelo menos 50 caracteres, é obrigatória.')
    if not hosts or any('*' in host or '://' in host or '/' in host for host in hosts):
        raise ImproperlyConfigured('ALLOWED_HOSTS deve conter hosts explícitos, sem wildcard.')
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or '*' in origin or parsed.username or parsed.password or parsed.path not in ['', '/'] or parsed.query or parsed.fragment:
            raise ImproperlyConfigured('CSRF_TRUSTED_ORIGINS exige origens HTTPS explícitas.')
