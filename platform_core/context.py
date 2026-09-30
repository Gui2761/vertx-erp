"""Contexto local à execução, nunca variável global compartilhada entre requests."""
from contextlib import contextmanager
from contextvars import ContextVar

_organization = ContextVar('vertyx_organization', default=None)


def current_organization():
    return _organization.get()


@contextmanager
def tenant_context(organization):
    token = _organization.set(organization)
    try:
        yield organization
    finally:
        _organization.reset(token)
