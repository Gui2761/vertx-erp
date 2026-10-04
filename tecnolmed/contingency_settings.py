"""Mesmo schema e código do piloto; suspende somente a Jornada Contratual.

Usar exclusivamente como contingência autorizada, sem desfazer migrations.
Credenciais, banco, storage, segurança e models continuam nas settings usuais.
"""
from .settings import *  # noqa: F403,F401

CONTINGENCIA_JORNADA_CONTRATUAL = True
