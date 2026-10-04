"""Controle operacional de contingência, sem mudança de schema ou permissões."""
from django.conf import settings
from django.core.exceptions import PermissionDenied


def journey_suspended():
    return bool(getattr(settings, 'CONTINGENCIA_JORNADA_CONTRATUAL', False))


def require_journey_writable():
    if journey_suspended():
        raise PermissionDenied(
            'Jornada Contratual suspensa em contingência. '
            'Histórico preservado; atendimentos continuam pelo fluxo da OS.'
        )


def context(request):
    return {'contingencia_jornada_contratual': journey_suspended()}
