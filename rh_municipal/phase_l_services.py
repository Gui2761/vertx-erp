"""Fail-closed scaffolding for official public-sector integrations.

This phase records setup and idempotent, blocked attempts only. It deliberately
does not perform HTTP, read secret values, or persist request/response bodies.
"""
import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from platform_core.context import current_organization
from .phase_e_services import public_module_available
from .public_services import has_municipal_permission, require_municipal_permission
from .phase_l_models import INTEGRATION_MODULES
from . import phase_l_models as m


def _require(actor, provider, capability):
    organization = current_organization()
    module = INTEGRATION_MODULES.get(provider)
    if organization is None or module is None or not public_module_available(organization, module):
        raise PermissionDenied('O produto e o módulo necessários para esta integração não estão contratados e ativos.')
    require_municipal_permission(actor, capability, module=module)
    return organization, module


def _write_event(actor, organization, config, action, before=None, after=None):
    event = m.EventoIntegracaoMunicipal(
        organization=organization, configuracao=config, acao=action,
        antes=before or {}, depois=after or {}, ator=actor,
    )
    event._service_write = True
    event.save()
    return event


@transaction.atomic
def create_configuration(actor, *, provider, name, endpoint='', api_version='', environment=None, credential_reference=''):
    organization, _module = _require(actor, provider, 'integration.manage')
    config = m.ConfiguracaoIntegracaoMunicipal(
        organization=organization, provedor=provider, nome=name.strip(),
        endpoint=endpoint.strip(), versao_api=api_version.strip(),
        ambiente=environment or m.ConfiguracaoIntegracaoMunicipal.Ambiente.HOMOLOGACAO,
        referencia_credencial=credential_reference.strip(), criada_por=actor,
        habilitada=False,
    )
    config.full_clean()
    config.save()
    _write_event(actor, organization, config, 'CONFIGURACAO_CRIADA', after={
        'provedor': config.provedor, 'nome': config.nome,
        'endpoint': config.endpoint, 'versao_api': config.versao_api,
        'ambiente': config.ambiente,
        'referencia_credencial_configurada': bool(config.referencia_credencial),
        'habilitada': False,
    })
    return config


def _digest(body):
    if isinstance(body, bytes):
        encoded = body
    elif isinstance(body, str):
        encoded = body.encode('utf-8')
    else:
        encoded = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


@transaction.atomic
def request_transmission(actor, *, config_id, idempotency_key, request_body):
    """Record an idempotent blocked attempt; never sends data to a provider."""
    organization = current_organization()
    if organization is None:
        raise PermissionDenied('Selecione uma Prefeitura antes de acessar integrações.')
    config = m.ConfiguracaoIntegracaoMunicipal.objects.select_for_update().filter(
        organization=organization, pk=config_id,
    ).first()
    if config is None:
        raise ValidationError('Configuração de integração não encontrada nesta Prefeitura.')
    _require(actor, config.provedor, 'integration.manage')
    key = (idempotency_key or '').strip()
    if not key or len(key) > 128:
        raise ValidationError('Informe uma chave de idempotência de 1 a 128 caracteres.')
    digest = _digest(request_body)
    existing = m.TentativaIntegracaoMunicipal.objects.filter(
        organization=organization, chave_idempotencia=key,
    ).first()
    if existing:
        if existing.digest_requisicao != digest or existing.configuracao_id != config.pk:
            raise ValidationError('A chave de idempotência já foi usada com outra requisição.')
        return existing

    attempt = m.TentativaIntegracaoMunicipal(
        organization=organization, configuracao=config,
        chave_idempotencia=key, digest_requisicao=digest,
        status=m.TentativaIntegracaoMunicipal.Status.BLOQUEADA,
        numero_tentativa=1, solicitada_por=actor, solicitada_em=timezone.now(),
        codigo_erro='ADAPTADOR_PENDENTE',
        mensagem_erro='Nenhuma transmissão foi realizada; adaptador oficial pendente.',
    )
    attempt._service_write = True
    attempt.save()
    _write_event(actor, organization, config, 'TRANSMISSAO_BLOQUEADA_SEM_ADAPTADOR', after={
        'tentativa': str(attempt.public_id), 'status': attempt.status,
        'digest_requisicao': digest, 'codigo_erro': attempt.codigo_erro,
        'numero_tentativa': attempt.numero_tentativa,
    })
    return attempt


def configurations_for(actor):
    """Return only tenant configurations within entitled modules and scope."""
    organization = current_organization()
    if organization is None:
        raise PermissionDenied('Selecione uma Prefeitura antes de acessar integrações.')
    visible = []
    for provider, module in INTEGRATION_MODULES.items():
        if public_module_available(organization, module) and has_municipal_permission(
            actor, 'integration.view', module=module,
        ):
            visible.append(provider)
    return m.ConfiguracaoIntegracaoMunicipal.objects.filter(
        organization=organization, provedor__in=visible,
    ).order_by('provedor', 'nome')
