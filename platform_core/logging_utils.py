"""Logs operacionais sem payloads, URLs, credenciais ou traceback com valores."""
import logging


class SafeLogFilter(logging.Filter):
    def filter(self, record):
        error = record.exc_info[0].__name__ if record.exc_info else '-'
        if not record.name.startswith('vertyx.operations'):
            record.msg = f'event=framework_log status={getattr(record, "status_code", "-")} error={error} source={record.module}:{record.lineno}'
            record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def logging_config(level='INFO'):
    if level not in ['INFO', 'WARNING', 'ERROR', 'CRITICAL']:
        level = 'INFO'
    return {
        'version': 1, 'disable_existing_loggers': False,
        'filters': {'safe': {'()': SafeLogFilter}},
        'formatters': {'safe': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'}},
        'handlers': {'console': {'class': 'logging.StreamHandler', 'filters': ['safe'], 'formatter': 'safe'}},
        'root': {'handlers': ['console'], 'level': level},
        'loggers': {
            'django': {'handlers': ['console'], 'level': level, 'propagate': False},
            'django.server': {'handlers': ['console'], 'level': level, 'propagate': False},
            'gunicorn.error': {'handlers': ['console'], 'level': level, 'propagate': False},
            'vertyx.operations': {'handlers': ['console'], 'level': level, 'propagate': False},
            'botocore': {'level': 'WARNING'}, 'boto3': {'level': 'WARNING'},
            's3transfer': {'level': 'WARNING'}, 'urllib3': {'level': 'WARNING'},
        },
    }


def operation_failure(event, exc):
    # Somente eventos fixos definidos no código; nunca passar texto do request.
    from botocore.exceptions import ClientError
    logger = logging.getLogger('vertyx.operations')
    if isinstance(exc, ClientError):
        # Provider messages, request IDs, URLs and arbitrary error codes may
        # contain secrets. Only fixed, recognized classifications are logged.
        codes = {'AccessDenied', 'InvalidAccessKeyId', 'SignatureDoesNotMatch',
                 'ExpiredToken', 'InvalidToken', 'NoSuchBucket', 'NoSuchKey',
                 'RequestTimeout', 'SlowDown', 'ServiceUnavailable', 'InternalError',
                 'NotImplemented', 'AuthorizationHeaderMalformed', 'InvalidRequest',
                 'NotFound', '404'}
        operations = {'ListObjects', 'ListObjectsV2', 'HeadObject', 'PutObject',
                      'GetObject', 'DeleteObject'}
        code = exc.response.get('Error', {}).get('Code')
        operation = exc.operation_name
        status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        logger.error('event=%s error=%s s3_code=%s operation=%s http_status=%s',
                     event, type(exc).__name__, code if code in codes else 'Other',
                     operation if operation in operations else 'Other',
                     status if type(status) is int and 400 <= status <= 599 else '-')
    else:
        logger.error('event=%s error=%s', event, type(exc).__name__)
