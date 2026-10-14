"""SE/SVRS homologation-only SOAP contract. No HTTP client or credential loader."""
from dataclasses import dataclass
import re
from lxml import etree
from django.core.exceptions import ValidationError
from .schema import parse, NFE

BASE='https://nfce-homologacao.svrs.rs.gov.br/ws/'
SERVICOS={
    'AUTORIZAR':(BASE+'NfeAutorizacao/NFeAutorizacao4.asmx','NFeAutorizacao4','nfeAutorizacaoLote'),
    'CONSULTAR':(BASE+'NfeConsulta/NfeConsulta4.asmx','NFeConsulta4','nfeConsultaNF'),
    'RECIBO':(BASE+'NfeRetAutorizacao/NFeRetAutorizacao4.asmx','NFeRetAutorizacao4','nfeRetAutorizacaoLote'),
    'CANCELAR':(BASE+'recepcaoevento/recepcaoevento4.asmx','NFeRecepcaoEvento4','nfeRecepcaoEvento'),
    'INUTILIZAR':(BASE+'nfeinutilizacao/nfeinutilizacao4.asmx','NFeInutilizacao4','nfeInutilizacaoNF'),
    'STATUS':(BASE+'NfeStatusServico/NfeStatusServico4.asmx','NFeStatusServico4','nfeStatusServicoNF'),
}


def envelope(operation,payload):
    if operation not in SERVICOS:raise ValidationError('Operação SOAP não suportada.')
    _,service,method=SERVICOS[operation]
    soap='http://www.w3.org/2003/05/soap-envelope';ws='http://www.portalfiscal.inf.br/nfe/wsdl/'+service
    root=etree.Element('{'+soap+'}Envelope',nsmap={'soap':soap});body=etree.SubElement(root,'{'+soap+'}Body')
    data=etree.SubElement(body,'{'+ws+'}nfeDadosMsg',nsmap={None:ws});data.append(parse(payload))
    return etree.tostring(root,encoding='utf-8',xml_declaration=True),ws+'/'+method


@dataclass(frozen=True)
class Retorno:
    status: str
    codigo: str
    protocolo: str=''
    recibo: str=''
    # xMotivo remains exclusively in the protected original response XML.


def retorno(xml,key,operation='EMITIR',digest=None):
    root=parse(xml);ns={'n':NFE}
    responses=[x for x in root.iter() if x.tag in ['{'+NFE+'}retEnviNFe','{'+NFE+'}retConsSitNFe','{'+NFE+'}retConsReciNFe','{'+NFE+'}retEnvEvento']]
    if len(responses)!=1:raise ValidationError('Retorno oficial ausente/ambíguo.')
    response=responses[0]
    if operation!='CANCELAR' and response.findtext('n:tpAmb',namespaces=ns)!='2':raise ValidationError('Retorno de produção/ambiente ausente bloqueado.')
    if operation!='CANCELAR' and response.findtext('n:cUF',namespaces=ns)!='28':raise ValidationError('UF do retorno incompatível/ausente.')
    if operation=='CANCELAR':
        if response.tag=='{'+NFE+'}retConsSitNFe':
            if response.findtext('n:tpAmb',namespaces=ns)!='2' or response.findtext('n:cUF',namespaces=ns)!='28' or response.findtext('n:chNFe',namespaces=ns)!=key:
                raise ValidationError('Consulta de cancelamento fora do contexto.')
            nodes=response.findall('n:procEventoNFe/n:retEvento/n:infEvento',ns)
            nodes=[n for n in nodes if n.findtext('n:tpEvento',namespaces=ns)=='110111']
            if not nodes:return Retorno('RESULTADO_DESCONHECIDO',response.findtext('n:cStat',namespaces=ns) or '')
        else:
            nodes=response.findall('n:retEvento/n:infEvento',ns)
        if len(nodes)!=1:raise ValidationError('Retorno do evento ambíguo.')
        info=nodes[0]
        if any(info.findtext('n:'+field,namespaces=ns)!=value for field,value in [('tpAmb','2'),('chNFe',key),('tpEvento','110111'),('nSeqEvento','1')]):raise ValidationError('Evento não corresponde ao cancelamento.')
        code=info.findtext('n:cStat',namespaces=ns);protocol=info.findtext('n:nProt',namespaces=ns) or ''
        if code in ('135','155'):
            if not re.fullmatch(r'\d{15}|\d{17}',protocol) or not info.findtext('n:dhRegEvento',namespaces=ns):raise ValidationError('Cancelamento sem protocolo/data.')
            return Retorno('CANCELADA',code,protocol)
        if not code or not re.fullmatch(r'\d{3,4}',code):raise ValidationError('cStat do evento ausente/inválido.')
        if code in ('136','573','108','109','656'):return Retorno('RESULTADO_DESCONHECIDO',code)
        return Retorno('REJEITADA',code)
    nodes=response.findall('n:protNFe/n:infProt',ns)
    if len(nodes)>1:raise ValidationError('Protocolo ambíguo.')
    if nodes:
        info=nodes[0]
        if info.findtext('n:tpAmb',namespaces=ns)!='2' or info.findtext('n:chNFe',namespaces=ns)!=key:raise ValidationError('Protocolo de outro documento/ambiente.')
        code=info.findtext('n:cStat',namespaces=ns);protocol=info.findtext('n:nProt',namespaces=ns) or ''
        if not code or not re.fullmatch(r'\d{3,4}',code):raise ValidationError('cStat do protocolo ausente/inválido.')
        if code in ('100','150'):
            if not re.fullmatch(r'\d{15}|\d{17}',protocol) or not info.findtext('n:dhRecbto',namespaces=ns) or digest and info.findtext('n:digVal',namespaces=ns)!=digest:raise ValidationError('Autorização sem protocolo/data/digest correspondente.')
            return Retorno('AUTORIZADA',code,protocol)
        if code in ('204','539'):return Retorno('RESULTADO_DESCONHECIDO',code)
        return Retorno('REJEITADA',code or '')
    code=response.findtext('n:cStat',namespaces=ns)
    if not code or not re.fullmatch(r'\d{3,4}',code):raise ValidationError('cStat ausente/inválido.')
    responsekey=response.findtext('n:chNFe',namespaces=ns)
    if responsekey and responsekey!=key:raise ValidationError('Consulta de outra chave.')
    if code in ('100','150','101','151'):raise ValidationError('Status conclusivo sem protocolo correspondente; reconciliar.')
    if code in ('103','105','106','108','109','204','217','539','656'):
        return Retorno('RESULTADO_DESCONHECIDO',code,recibo=response.findtext('n:infRec/n:nRec',namespaces=ns) or '')
    return Retorno('REJEITADA',code)
