"""Server-side final checklist. No browser field or feature flag proves readiness."""
from django.conf import settings
from django.core.exceptions import ValidationError
from platform_core.context import current_organization
from platform_core.modules import require_capability
from operacao import models as m
from fiscal.motors.nfce_homologacao import MotorNFCeHomologacao
from . import services,xml
from .vault import AdaptadorCofre
from datetime import datetime


def verificar(user,documento_id,motor=None,*,credenciamento_confirmado=None):
    require_capability(user,'fiscal_emitir');services.local()
    doc=m.DocumentoFiscal.objects.get(pk=documento_id)
    doc.full_clean();motor=motor or MotorNFCeHomologacao()
    rows=[]
    def add(name,valid):rows.append({'item':name,'valido':valid is True})
    add('Tenant correto',doc.organization_id==current_organization().pk)
    add('Estabelecimento e CNPJ emitente',bool(doc.estabelecimento_id and doc.snapshot_fiscal.get('emitente',{}).get('cnpj')==doc.estabelecimento.cnpj))
    add('Ambiente HOMOLOGAÇÃO',doc.ambiente=='HOMOLOGACAO' and doc.tipo=='NFCE' and doc.modelo=='65')
    add('Venda FINALIZADA',bool(doc.venda_id and doc.venda.status=='FINALIZADA'))
    configured=False
    try:
        services.validar_config(doc.configuracao_fiscal,doc.serie_fiscal,doc.credencial_fiscal,doc.regra_fiscal)
        configured=True
    except (ValidationError,AttributeError,m.ConfiguracaoNFCe.DoesNotExist):pass
    for name in ('CRT / cadastro','Produto e tributação','QR v3 e consulta oficialmente confirmados'):
        add(name,configured)
    # Supplied exclusively by provisioned backend evidence, not a browser field
    # or a guessed tax code. The local documental draft remains insufficient.
    accreditation=credenciamento_confirmado or {}
    add('Credenciamento explicitamente confirmado',accreditation=={
        'organization_id':doc.organization_id,'estabelecimento_id':doc.estabelecimento_id,
        'cnpj':doc.estabelecimento.cnpj,'ambiente':'HOMOLOGACAO','confirmado':True})
    reservation=m.ReservaNumeracaoFiscal.objects.filter(documento=doc,serie_id=doc.serie_fiscal_id,numero=int(doc.numero) if doc.numero.isdigit() else 0).exists()
    add('Série e número reservados',bool(reservation and doc.chave))
    signed=False
    if configured and reservation:
        try:
            unsigned,key=xml.gerar(doc.snapshot_fiscal,int(doc.numero),datetime.fromisoformat(doc.snapshot_fiscal['emissao']),doc.snapshot_fiscal['cnf'])
            if key!=doc.chave:raise ValidationError('Chave divergente.')
            motor.preparar_assinado(doc,unsigned,'EMITIR');signed=True
        except ValidationError:pass
    add('Certificado e assinatura XMLDSig validados',signed)
    add('XSD antes/depois e aplicabilidade confirmada',signed)
    add('Endpoint oficial SVRS HOMOLOGAÇÃO',True)
    wsdl=False;mtls=False
    if motor.transporte is not None:
        try:
            motor.transporte.contrato('AUTORIZAR');wsdl=True
            cofre=motor.transporte.cofre_transporte
            if not isinstance(cofre,AdaptadorCofre):raise ValidationError('Cofre seguro obrigatório.')
            cofre.identidade(motor.transporte.referencia_transporte,**motor.contexto(doc));mtls=True
        except (ValidationError,AttributeError):pass
    add('WSDL oficial pinado',wsdl)
    add('Identidade mTLS separadamente provisionada',mtls)
    add('Autorização explícita de transmissão',getattr(settings,'FISCAL_NFCE_SEFAZ_APPROVED',False) is True and bool(motor.transporte and motor.transporte.habilitado))
    ready=all(row['valido'] for row in rows)
    return {'estado':'PRONTO PARA TRANSMISSÃO' if ready else 'EMISSÃO BLOQUEADA',
            'checklist':rows,'pendencias':[r['item'] for r in rows if not r['valido']],
            'transmissao_executada':False,'producao_habilitada':False}
