"""XMLDSig assembly in the backend; RSA operation stays in the secure vault.

The callback receives canonical SignedInfo, reference and tenant context, never
returns a key. The same builder signs a single NFC-e or cancellation event.
"""
import base64
import hashlib
from lxml import etree
from django.core.exceptions import ValidationError
from .schema import parse, NFE
from .signature import DS, C14N


def assinar_xml(unsigned, identity, assinar_canonicalizado):
    root=parse(unsigned)
    if root.findall('.//{'+DS+'}Signature'):
        raise ValidationError('XML já assinado; não será assinado novamente.')
    nodes=root.findall('{'+NFE+'}infNFe') if root.tag=='{'+NFE+'}NFe' else root.findall('{'+NFE+'}evento/{'+NFE+'}infEvento') if root.tag=='{'+NFE+'}envEvento' else []
    if len(nodes)!=1 or not nodes[0].get('Id') or len(root.xpath('//*[@Id=$id]',id=nodes[0].get('Id')))!=1:
        raise ValidationError('XML/referência de assinatura ausente ou ambígua.')
    info=nodes[0];ds='{'+DS+'}'
    issuer=info.findtext('{'+NFE+'}emit/{'+NFE+'}CNPJ') if root.tag=='{'+NFE+'}NFe' else info.findtext('{'+NFE+'}CNPJ')
    environment=info.findtext('{'+NFE+'}ide/{'+NFE+'}tpAmb') if root.tag=='{'+NFE+'}NFe' else info.findtext('{'+NFE+'}tpAmb')
    if issuer!=identity.cnpj or environment!='2' or identity.ambiente!='HOMOLOGACAO':
        raise ValidationError('XML de outro emitente/ambiente; assinatura bloqueada.')
    sig=etree.SubElement(info.getparent(),ds+'Signature',nsmap={None:DS})
    si=etree.SubElement(sig,ds+'SignedInfo')
    etree.SubElement(si,ds+'CanonicalizationMethod',Algorithm=C14N)
    etree.SubElement(si,ds+'SignatureMethod',Algorithm=DS+'rsa-sha1')
    ref=etree.SubElement(si,ds+'Reference',URI='#'+info.get('Id'))
    transforms=etree.SubElement(ref,ds+'Transforms')
    for algorithm in (DS+'enveloped-signature',C14N):etree.SubElement(transforms,ds+'Transform',Algorithm=algorithm)
    etree.SubElement(ref,ds+'DigestMethod',Algorithm=DS+'sha1')
    etree.SubElement(ref,ds+'DigestValue').text=base64.b64encode(hashlib.sha1(etree.tostring(info,method='c14n')).digest()).decode()
    # Provider must perform RSA-SHA1 with the protected key and return signature
    # bytes only. No PEM/PFX, secret or certificate password enters this module.
    value=assinar_canonicalizado(etree.tostring(si,method='c14n'))
    if not isinstance(value,bytes) or not 256<=len(value)<=1024 or not identity.certificado_der:
        raise ValidationError('Resposta de assinatura inválida; chave nunca é aceita.')
    etree.SubElement(sig,ds+'SignatureValue').text=base64.b64encode(value).decode()
    etree.SubElement(etree.SubElement(etree.SubElement(sig,ds+'KeyInfo'),ds+'X509Data'),ds+'X509Certificate').text=base64.b64encode(identity.certificado_der).decode()
    return etree.tostring(root,encoding='utf-8',xml_declaration=True)
