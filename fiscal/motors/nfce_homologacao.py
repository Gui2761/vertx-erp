"""Distinct NFC-e homologation motor. Default dependencies prohibit transmission."""
from django.conf import settings
from django.core.exceptions import ValidationError
from lxml import etree
from fiscal.nfce.contracts import CofreIndisponivel, DependenciaFiscal
from fiscal.nfce.vault import AdaptadorCofre
from fiscal.nfce.schema import SchemaOficial,NFE,parse
from fiscal.nfce import signature,xml


class MotorNFCeHomologacao:
    tipo='NFCE';modelo='65';ambiente='HOMOLOGACAO'
    def __init__(self,cofre=None,schema=None,verificador=None,transporte=None,regra_cancelamento=None):
        self.cofre=cofre or AdaptadorCofre();self.schema=schema
        self.verificador=verificador or signature.verificar
        from fiscal.nfce.svrs import TransporteSVRSHomologacao
        self.transporte=transporte or (TransporteSVRSHomologacao() if isinstance(self.cofre,AdaptadorCofre) else None)
        self.regra_cancelamento=regra_cancelamento
    def validar(self,documento):
        # Cached instances are not authority: revalidate every tenant FK before
        # consulting a vault. SaaS staff/superuser status never selects an issuer.
        documento.full_clean()
        config=documento.configuracao_fiscal
        cred=documento.credencial_fiscal
        serie=documento.serie_fiscal
        if not config or not cred or not serie:
            raise ValidationError('Contexto fiscal completo obrigatório antes de acessar o cofre.')
        for row in (config,cred,serie):row.full_clean()
        if not config.habilitada or not documento.estabelecimento.ativo or (serie.estabelecimento_id,serie.tipo,serie.ambiente)!=(documento.estabelecimento_id,documento.tipo,documento.ambiente):
            raise ValidationError('Estabelecimento/configuração/série incompatíveis ou desabilitados.')
        from operacao.models import VinculoCredencialFiscal
        from django.utils import timezone
        if not VinculoCredencialFiscal.objects.filter(configuracao=config,credencial=cred).exists() or cred.expira_em and cred.expira_em<=timezone.now():
            raise ValidationError('Credencial não vinculada ao estabelecimento/configuração ou expirada.')
        if documento.tipo!=self.tipo or documento.modelo!=self.modelo or documento.ambiente!=self.ambiente or documento.configuracao_fiscal.motor!='NFCE_SVRS_HOM' or documento.detalhesnfce.modo_emissao!='NORMAL':
            raise ValidationError('Motor NFC-e homologação incompatível; produção/contingência bloqueadas.')
        if not cred or cred.mecanismo!='REFERENCIA' or cred.ambiente!='HOMOLOGACAO' or not cred.ativa:
            raise ValidationError('Referência A1 de homologação obrigatória.')
        context=self.contexto(documento)
        if documento.snapshot_fiscal['emitente']['cnpj']!=context['emitente_cnpj']:
            raise ValidationError('Emitente do snapshot diverge do estabelecimento fiscal.')
        identity=self.cofre.identidade(cred.referencia,**context)
        if (identity.organization_id,identity.estabelecimento_id,identity.ambiente,identity.cnpj)!=(documento.organization_id,documento.estabelecimento_id,'HOMOLOGACAO',context['emitente_cnpj']) or not identity.vigente or not identity.icp_brasil:
            raise ValidationError('Certificado pertence a outro tenant/estabelecimento/emitente/ambiente ou não é ICP-Brasil vigente.')
        return identity
    @staticmethod
    def contexto(doc):
        return {'organization_id':doc.organization_id,'estabelecimento_id':doc.estabelecimento_id,'ambiente':doc.ambiente,'emitente_cnpj':doc.estabelecimento.cnpj}
    @staticmethod
    def validar_xml(doc,payload,operation):
        root=parse(payload);ns={'n':NFE}
        if operation=='CONSULTAR':
            if root.tag!='{'+NFE+'}consSitNFe' or root.findtext('n:chNFe',namespaces=ns)!=doc.chave or root.findtext('n:tpAmb',namespaces=ns)!='2':
                raise ValidationError('Consulta XML fora do contexto do documento.')
            return
        if operation=='RECIBO':
            if root.tag!='{'+NFE+'}consReciNFe' or root.findtext('n:tpAmb',namespaces=ns)!='2' or not root.findtext('n:nRec',namespaces=ns):
                raise ValidationError('Consulta de recibo inválida.')
            return
        path='n:NFe/n:infNFe' if operation=='AUTORIZAR' else 'n:infNFe' if operation=='EMITIR' else 'n:evento/n:infEvento'
        expected='enviNFe' if operation=='AUTORIZAR' else 'NFe' if operation=='EMITIR' else 'envEvento'
        rows=root.findall(path,ns)
        if root.tag!='{'+NFE+'}'+expected or len(rows)!=1:
            raise ValidationError('XML fiscal ausente/ambíguo ou de outro motor.')
        row=rows[0]
        if operation in ('EMITIR','AUTORIZAR'):
            match=(row.get('Id')=='NFe'+doc.chave and row.findtext('n:ide/n:tpAmb',namespaces=ns)=='2' and row.findtext('n:emit/n:CNPJ',namespaces=ns)==doc.estabelecimento.cnpj)
        else:
            match=(row.findtext('n:chNFe',namespaces=ns)==doc.chave and row.findtext('n:tpAmb',namespaces=ns)=='2' and row.findtext('n:CNPJ',namespaces=ns)==doc.estabelecimento.cnpj)
        if not match:
            raise ValidationError('XML pertence a outro emitente/ambiente/documento.')
    def preparar_assinado(self,doc,unsigned,operation):
        if operation=='CANCELAR' and isinstance(self.cofre,AdaptadorCofre):
            if self.regra_cancelamento is None:raise DependenciaFiscal('Regras/prazo de cancelamento não provisionados.')
            self.regra_cancelamento.validar(doc)
        identity=self.validar(doc)
        self.validar_xml(doc,unsigned,operation)
        cfg=doc.configuracao_fiscal.nfce
        if self.schema is None:
            from fiscal.nfce.schema_flow import SchemaFluxo
            self.schema=SchemaFluxo()
        schema=self.schema
        # Official field types before signing, unmodified complete XSD after it.
        # Legacy orchestration doubles have no official unsigned validation.
        if callable(getattr(schema,'validar_sem_assinatura',None)):
            schema.validar_sem_assinatura(unsigned,'nfe_v4.00.xsd' if operation=='EMITIR' else 'envEventoCancNFe_v1.00.xsd')
        signed=self.cofre.assinar(doc.credencial_fiscal.referencia,unsigned,**self.contexto(doc))
        if isinstance(self.cofre, AdaptadorCofre):
            self.verificador(unsigned,signed,identity,cadeia=identity.cadeia_der,ancoras_sha256=self.cofre.ancoras_icp_brasil)
        else:
            self.verificador(unsigned,signed,identity)
        schema.validar(signed,'nfe_v4.00.xsd' if operation=='EMITIR' else 'envEventoCancNFe_v1.00.xsd')
        return signed
    def enviar(self,doc,payload,operation):
        self.validar(doc)
        self.validar_xml(doc,payload,operation)
        if not getattr(settings,'FISCAL_NFCE_SEFAZ_APPROVED',False):
            raise DependenciaFiscal('Acesso à SEFAZ não aprovado; nenhum webservice será chamado.')
        if self.transporte is None:
            raise DependenciaFiscal('Transporte HTTPS/mTLS segregado não provisionado; nenhum envio realizado.')
        # The signing identity is never an implicit transport identity. A
        # separately provisioned transport reference is required even when
        # both services happen to be backed by the same secure-vault provider.
        transport_reference=getattr(self.transporte,'referencia_transporte',None)
        if transport_reference and transport_reference==doc.credencial_fiscal.referencia:
            raise DependenciaFiscal('Referência mTLS deve ser distinta da referência de assinatura; nenhum envio realizado.')
        if self.schema is None:
            from fiscal.nfce.schema_flow import SchemaFluxo
            self.schema=SchemaFluxo()
        self.schema.validar(payload,{'AUTORIZAR':'enviNFe_v4.00.xsd','CONSULTAR':'consSitNFe_v4.00.xsd','RECIBO':'consReciNFe_v4.00.xsd','CANCELAR':'envEventoCancNFe_v1.00.xsd'}[operation])
        return self.transporte.enviar(operation,payload,**self.contexto(doc))
    def emitir(self,doc,signed):
        root=etree.Element('{'+NFE+'}enviNFe',versao='4.00',nsmap={None:NFE})
        xml.tag(root,'idLote',doc.pk);xml.tag(root,'indSinc','1');root.append(parse(signed))
        return self.enviar(doc,etree.tostring(root), 'AUTORIZAR')
    def consultar(self,doc):
        root=etree.Element('{'+NFE+'}consSitNFe',versao='4.00',nsmap={None:NFE})
        xml.tag(root,'tpAmb','2');xml.tag(root,'xServ','CONSULTAR');xml.tag(root,'chNFe',doc.chave)
        return self.enviar(doc,etree.tostring(root),'CONSULTAR')
    def consultar_recibo(self,doc,recibo):
        import re
        if not re.fullmatch(r'\d{15}',recibo):raise ValidationError('Recibo fiscal inválido.')
        root=etree.Element('{'+NFE+'}consReciNFe',versao='4.00',nsmap={None:NFE})
        xml.tag(root,'tpAmb','2');xml.tag(root,'nRec',recibo)
        return self.enviar(doc,etree.tostring(root),'RECIBO')
    def cancelar(self,doc,signed):
        return self.enviar(doc,signed,'CANCELAR')
