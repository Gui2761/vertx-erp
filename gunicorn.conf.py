import os
from platform_core.logging_utils import logging_config

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = 2
timeout = 60
graceful_timeout = 30
accesslog = None  # URLs de conferência contêm tokens; não registrar access logs.
errorlog = '-'
capture_output = True
logconfig_dict = logging_config(os.environ.get('LOG_LEVEL', 'INFO'))
