"""Backend-only A1 contract. No implementation loading PFX/password from disk/DB."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from django.core.exceptions import ValidationError


class DependenciaFiscal(ValidationError):
    pass


@dataclass(frozen=True)
class IdentidadeCertificado:
    organization_id: int
    ambiente: str
    cnpj: str
    vigente: bool
    icp_brasil: bool
    estabelecimento_id: int
    sha256_certificado: str = ''
    titular: str = ''
    valido_desde: datetime | None = None
    valido_ate: datetime | None = None
    cadeia_validada: bool = False
    revogacao_verificada: bool = False
    certificado_der: bytes = field(default=b'', repr=False)
    cadeia_der: tuple[bytes, ...] = field(default=(), repr=False)


class CofreFiscal(Protocol):
    def identidade(self, referencia: str, *, organization_id: int, estabelecimento_id: int, ambiente: str, emitente_cnpj: str) -> IdentidadeCertificado: ...
    def assinar(self, referencia: str, xml: bytes, *, organization_id: int, estabelecimento_id: int, ambiente: str, emitente_cnpj: str) -> bytes: ...
    # mTLS is delegated to an authorized backend service; private key never returned.
    def transmitir(self, referencia: str, endpoint: str, metodo: str, envelope: bytes, *, organization_id: int, estabelecimento_id: int, ambiente: str, emitente_cnpj: str) -> bytes: ...


class ProvedorAssinaturaSegura(Protocol):
    """Backend/cofre SDK contract; implementation chosen when provisioned."""
    def identidade(self, referencia: str, *, organization_id: int, estabelecimento_id: int, ambiente: str, emitente_cnpj: str) -> IdentidadeCertificado: ...
    def assinar_canonicalizado(self, referencia: str, signed_info: bytes, *, algoritmo: str, organization_id: int, estabelecimento_id: int, ambiente: str, emitente_cnpj: str) -> bytes: ...


class ProvedorMTLSSeguro(Protocol):
    # Receives RequisicaoSOAP; returns RespostaHTTPS, without exposing a key.
    def executar_mtls(self, referencia: str, requisicao, *, organization_id: int, estabelecimento_id: int, ambiente: str, emitente_cnpj: str): ...


class CofreIndisponivel:
    estado = 'COFRE NÃO PROVISIONADO'
    def identidade(self, referencia, **kwargs):
        raise DependenciaFiscal('COFRE NÃO PROVISIONADO; nenhum certificado foi solicitado ou carregado.')
    def assinar(self, *args, **kwargs):
        raise DependenciaFiscal('Assinatura A1 indisponível; transmissão bloqueada.')
    def transmitir(self, *args, **kwargs):
        raise DependenciaFiscal('Transporte mTLS não autorizado/integrado.')
