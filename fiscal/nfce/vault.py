"""Provider boundary only. No secret loader, fallback vault or transport client.

Provisioning/ACLs, ICP-Brasil anchors and revocation checking are obligations
of a future backend provider. A database reference never proves provisioning.
"""
import re
import hashlib
from datetime import datetime, timezone
from uuid import UUID
from cryptography import x509
from django.core.exceptions import ValidationError
from platform_core.context import current_organization
from operacao import models as m
from .contracts import CofreIndisponivel, DependenciaFiscal
from .certificates import cnpj_certificado, verificar_cadeia


class AdaptadorCofre:
    def __init__(self, provider=None, *, ancoras_icp_brasil=()):
        self.provider = provider
        # Pins must come from trusted backend provisioning, never the provider
        # response, browser, database form or certificate filename.
        self.ancoras_icp_brasil = tuple(ancoras_icp_brasil)
        self.estado = 'COFRE NÃO PROVISIONADO' if provider is None else 'PROVISIONAMENTO A VALIDAR'

    def _context(self, reference, context):
        try:
            if set(context) != {'organization_id', 'estabelecimento_id', 'ambiente', 'emitente_cnpj'}:
                raise ValueError()
            org = current_organization()
            if not org or context['organization_id'] != org.pk or context['ambiente'] != 'HOMOLOGACAO':
                raise ValueError()
            if not re.fullmatch(r'\d{14}', context['emitente_cnpj']) or not reference.startswith('cofre://'):
                raise ValueError()
            if str(UUID(reference[8:])) != reference[8:]:
                raise ValueError()
            link = m.VinculoCredencialFiscal.objects.filter(
                credencial__referencia=reference, credencial__organization_id=org.pk,
                credencial__ambiente='HOMOLOGACAO', credencial__ativa=True,
                credencial__mecanismo='REFERENCIA', configuracao__organization_id=org.pk,
                configuracao__estabelecimento_id=context['estabelecimento_id'],
                configuracao__estabelecimento__cnpj=context['emitente_cnpj'],
                configuracao__estabelecimento__ativo=True, configuracao__ambiente='HOMOLOGACAO',
                configuracao__tipo='NFCE').select_related('credencial').first()
            if not link or link.credencial.expira_em and link.credencial.expira_em <= datetime.now(timezone.utc):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValidationError('Referência/contexto do cofre incompatível; acesso bloqueado.') from None
        return context

    def identidade(self, reference, **context):
        self._context(reference, context)
        if self.provider is None:
            return CofreIndisponivel().identidade(reference, **context)
        try:
            identity = self.provider.identidade(reference, **context)
            expected = (context['organization_id'], context['estabelecimento_id'], context['ambiente'], context['emitente_cnpj'])
            actual = (identity.organization_id, identity.estabelecimento_id, identity.ambiente, identity.cnpj)
            now = datetime.now(timezone.utc)
            if actual != expected or any(value is not True for value in (identity.vigente, identity.icp_brasil, identity.cadeia_validada, identity.revogacao_verificada)):
                raise ValueError()
            if not identity.titular or not re.fullmatch('[0-9a-f]{64}', identity.sha256_certificado):
                raise ValueError()
            if not identity.valido_desde <= now <= identity.valido_ate:
                raise ValueError()
            cert = x509.load_der_x509_certificate(identity.certificado_der)
            if (hashlib.sha256(identity.certificado_der).hexdigest() != identity.sha256_certificado
                or cnpj_certificado(cert) != context['emitente_cnpj']
                or identity.valido_desde != cert.not_valid_before_utc
                or identity.valido_ate != cert.not_valid_after_utc
                or identity.titular != cert.subject.rfc4514_string()):
                raise ValueError()
            verificar_cadeia(identity.certificado_der, identity.cadeia_der, self.ancoras_icp_brasil)
            return identity
        except Exception:
            raise DependenciaFiscal('Identidade/validade/cadeia não atestadas pelo cofre; bloqueado.') from None

    def assinar(self, reference, xml, **context):
        identity=self.identidade(reference, **context)
        try:
            from .signing import assinar_xml
            from .signature import verificar
            signed=assinar_xml(xml,identity,lambda canonical:self.provider.assinar_canonicalizado(
                reference,canonical,algoritmo='RSA-SHA1',**context))
            verificar(xml,signed,identity,cadeia=identity.cadeia_der,ancoras_sha256=self.ancoras_icp_brasil)
            return signed
        except Exception:
            raise DependenciaFiscal('Assinatura no cofre indisponível; conteúdo do provedor não exposto.') from None

    def transmitir(self, *args, **kwargs):
        # This stage deliberately does not implement an external transport.
        raise DependenciaFiscal('Transmissão não implementada/autorizada neste adaptador.')
