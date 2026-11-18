"""Contexto local à execução, nunca variável global compartilhada entre requests."""
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from django.conf import settings

_organization = ContextVar('vertyx_organization', default=None)
_PROD_TTL_CACHE = {}
_PROD_TTL_SECONDS = 60.0


def is_prod_cache_enabled():
    return not getattr(settings, 'DEBUG', False) and 'test' not in sys.argv and 'pytest' not in sys.modules


def get_org_cache_dict(org):
    if org is None:
        return None
    if is_prod_cache_enabled() and getattr(org, 'pk', None) is not None:
        now = time.monotonic()
        entry = _PROD_TTL_CACHE.get(org.pk)
        if entry is not None and (now - entry[0]) < _PROD_TTL_SECONDS:
            return entry[1]
        d = {}
        _PROD_TTL_CACHE[org.pk] = (now, d)
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
        if not is_prod_cache_enabled():
            clear_org_cache(organization)
        _organization.reset(token)
