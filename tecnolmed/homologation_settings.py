"""Homologação comercial: banco/storage definidos pelo operador, sem envio real.

Selecionar explicitamente via DJANGO_SETTINGS_MODULE no serviço de testes.
Não cria banco, usuários, credenciais ou chave clínica.
"""
from .settings import *  # noqa: F403,F401

EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
FISCAL_SIMULATION_ENABLED = False
FISCAL_NFCE_LOCAL_ENABLED = False
SESSION_COOKIE_NAME = 'vertyx_homologacao_sessionid'
CSRF_COOKIE_NAME = 'vertyx_homologacao_csrftoken'
COMMERCIAL_DEMO_ENABLED = True
