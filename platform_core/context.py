"""Contexto local à execução, nunca variável global compartilhada entre requests."""
from contextlib import contextmanager
from contextvars import ContextVar

_organization = ContextVar('vertyx_organization', default=None)


def current_organization():
    return _organization.get()


def clear_org_cache(org=None):
    target = org or _organization.get()
    if target is not None:
        for attr in ('_pmo_cache', '_pme_cache', '_req_cache'):
            try:
                target.__dict__.pop(attr, None)
            except (AttributeError, TypeError):
                pass


@contextmanager
def tenant_context(organization):
    prev = _organization.get()
    if prev is not organization:
        clear_org_cache(organization)
    token = _organization.set(organization)
    try:
        yield organization
    finally:
        clear_org_cache(organization)
        _organization.reset(token)
