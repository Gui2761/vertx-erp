"""Contexto local à execução, nunca variável global compartilhada entre requests."""
import sys
import time
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from django.conf import settings

_organization = ContextVar('vertyx_organization', default=None)
_PROD_TTL_CACHE = {}
_PROD_TTL_SECONDS = 60.0
_CACHE_LOCK = threading.Lock()


def is_prod_cache_enabled():
    return not getattr(settings, 'DEBUG', False) and 'test' not in sys.argv and 'pytest' not in sys.modules


def get_org_cache_dict(org):
    if org is None:
        return None
    org_pk = getattr(org, 'pk', None)
    if org_pk is not None:
        now = time.monotonic()
        with _CACHE_LOCK:
            entry = _PROD_TTL_CACHE.get(org_pk)
            ttl = _PROD_TTL_SECONDS if is_prod_cache_enabled() else 3600.0
            if entry is not None and (now - entry[0]) < ttl:
                return entry[1]
            d = {}
            _PROD_TTL_CACHE[org_pk] = (now, d)
            return d
    cache = getattr(org, '_req_cache', None)
    if cache is None:
        try:
            org._req_cache = {}
            cache = org._req_cache
        except (AttributeError, TypeError):
            return None
    return cache


def current_organization():
    return _organization.get()


def clear_org_cache(org=None):
    with _CACHE_LOCK:
        if org is not None and getattr(org, 'pk', None) is not None:
            _PROD_TTL_CACHE.pop(org.pk, None)
        else:
            _PROD_TTL_CACHE.clear()
    target = org or _organization.get()
    if target is not None:
        for attr in ('_pmo_cache', '_pme_cache', '_req_cache'):
            try:
                target.__dict__.pop(attr, None)
            except (AttributeError, TypeError):
                pass


@contextmanager
def tenant_context(organization):
    token = _organization.set(organization)
    try:
        yield organization
    finally:
        clear_org_cache(organization)
        _organization.reset(token)
