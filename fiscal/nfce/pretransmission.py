"""Local pre-transmission proof; no network, authorization or commercial writes."""
import hashlib
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from platform_core.modules import require_capability
from operacao import models as m
from gestao.services import audit
from . import services, signature
from .schema import SchemaOficial

SCHEMA_DIRECTORY = Path(__file__).parent / 'schemas' / 'PL_010f_v1.04'
SCHEMA_RELEASE = 'PL_010f_v1.04'


def validar_ensaio(user, documento_id, unsigned, signed, identity, *, cadeia, ancoras_sha256):
    require_capability(user, 'fiscal_emitir')
    services.local()
    if getattr(settings, 'FISCAL_NFCE_SEFAZ_APPROVED', False):
        raise ValidationError('Ensaio exige transmissão desabilitada.')
    doc = m.DocumentoFiscal.objects.get(pk=documento_id)
    doc.full_clean()
    services.validar_config(doc.configuracao_fiscal, doc.serie_fiscal, doc.credencial_fiscal, doc.regra_fiscal)
    if doc.status != 'PENDENTE' or not doc.numero or not doc.chave or not doc.venda_id or doc.venda.status != 'FINALIZADA':
        raise ValidationError('Ensaio requer documento pendente numerado de venda confirmada.')
    if not m.ReservaNumeracaoFiscal.objects.filter(documento=doc, serie=doc.serie_fiscal, numero=int(doc.numero)).exists():
        raise ValidationError('Reserva de numeração incompatível.')
    expected = (doc.organization_id, doc.estabelecimento_id, 'HOMOLOGACAO', doc.estabelecimento.cnpj)
    actual = (identity.organization_id, identity.estabelecimento_id, identity.ambiente, identity.cnpj)
    if actual != expected or identity.icp_brasil or not cadeia or not ancoras_sha256:
        raise ValidationError('Ensaio aceita apenas identidade sintética, cadeia explícita e contexto exato.')
    from fiscal.motors.nfce_homologacao import MotorNFCeHomologacao
    MotorNFCeHomologacao.validar_xml(doc, unsigned, 'EMITIR')
    proof = signature.verificar(unsigned, signed, identity, cadeia=cadeia,
                               ancoras_sha256=ancoras_sha256, ensaio_sintetico=True)
    xsd = SchemaOficial(SCHEMA_DIRECTORY, SCHEMA_RELEASE).validar(signed, ensaio_local=True)
    result = {'estado': 'PRONTO PARA TRANSMISSÃO', 'conclusao': 'PRONTO PARA HOMOLOGAÇÃO OFICIAL',
              'escopo': 'ENSAIO LOCAL SINTÉTICO — não habilita a TECNOLMED',
              'documento_id': doc.pk, 'assinatura': proof, 'xsd': xsd,
              'xml_sha256': hashlib.sha256(signed).hexdigest(), 'transmissao': False,
              'autorizado_sefaz': False, 'certificado_real': False, 'status_fiscal': doc.status}
    # Only public evidence. Never return/store certificate bytes, passwords or keys.
    audit(user, 'FISCAL_PRETRANSMISSAO_ENSAIO', doc, result)
    return result
