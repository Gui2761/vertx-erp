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
    logging.getLogger('vertyx.operations').error('event=%s error=%s', event, type(exc).__name__)
