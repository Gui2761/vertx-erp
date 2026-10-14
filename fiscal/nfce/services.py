"""NFC-e local homologation orchestration using the existing fiscal/sale models."""
import hashlib
import json
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction,connection
from django.utils import timezone
from lxml import etree
from platform_core.context import current_organization
from platform_core.models import ConfiguracaoEmpresa
from platform_core.modules import require_capability
from gestao.services import audit,write
from operacao import models as m
from fiscal.motors.nfce_homologacao import MotorNFCeHomologacao
from . import xml,transport
from .schema import parse,NFE


@transaction.atomic
def registrar_proposta_documental(user, proposta):
    """Audited local registration. No profile, numbering, vault or issuance."""
    from copy import deepcopy
    from platform_core.models import Organization, FilialEmpresa
    from operacao.fiscal_models import proposta_documental_publica
    require_capability(user, 'fiscal_configurar')
    local()
    proposta_documental_publica(proposta)
    if not proposta:
        raise ValidationError('Informe uma proposta documental pública.')
    proposta = deepcopy(proposta)
    org = Organization.objects.select_for_update().get(pk=current_organization().pk)
    data = proposta['dados']
    if org.cnpj and org.cnpj != data['cnpj']:
        raise ValidationError('CNPJ documental diverge da organização selecionada; nenhuma alteração realizada.')
    existing = m.ConfiguracaoFiscal.objects.filter(proposta_documental__dados__cnpj=data['cnpj']).first()
    if existing:
        for field in ('ie', 'im'):
            previous = existing.proposta_documental['cadastro_anterior'].get(field, '')
            divergence = {'campo': field, 'anterior': previous, 'proposta': data[field]}
            if previous and previous != data[field] and divergence not in proposta['divergencias']:
                proposta['divergencias'].append(divergence)
        before = deepcopy(existing.proposta_documental)
        before['cadastro_anterior'] = proposta['cadastro_anterior']
        if before != proposta:
            raise ValidationError('Proposta já registrada com outros dados; exige revisão explícita e nova versão.')
        return existing
    company = ConfiguracaoEmpresa.objects.select_for_update().first()
    old = {'razao_social': org.razao_social, 'nome_fantasia': org.nome_fantasia,
           'cnpj': org.cnpj, 'ie': company.inscricao_estadual if company else '',
           'im': company.inscricao_municipal if company else ''}
    proposta['cadastro_anterior'] = old
    for field, previous in [('ie', old['ie']), ('im', old['im'])]:
        if previous and previous != data[field] and not any(
            d == {'campo': field, 'anterior': previous, 'proposta': data[field]}
            for d in proposta['divergencias']
        ):
            proposta['divergencias'].append({'campo': field, 'anterior': previous, 'proposta': data[field]})
    org.cnpj = data['cnpj']
    org.razao_social = data['razao_social']
    org.nome_fantasia = data['nome_fantasia']
    org.save()
    audit(user, 'FISCAL_CADASTRO_DOCUMENTAL', org, {'anterior': old,
        'posterior': {k: data[k] for k in ('cnpj', 'razao_social', 'nome_fantasia')},
        'estado': 'PROPOSTA_DOCUMENTAL_LOCAL'})
    if company is None:
        company = ConfiguracaoEmpresa()
    # Existing conflicting registration and definitive tax data are preserved.
    if not company.inscricao_estadual:
        company.inscricao_estadual = data['ie']
    if not company.inscricao_municipal:
        company.inscricao_municipal = data['im']
    company.save()
    audit(user, 'FISCAL_INSCRICOES_DOCUMENTAIS', company, {'anterior': {'ie': old['ie'], 'im': old['im']},
        'posterior': {'ie': company.inscricao_estadual, 'im': company.inscricao_municipal}})
    if FilialEmpresa.objects.filter(codigo='FISCAL-DOC-HOM').exists():
        raise ValidationError('Código provisório já existe sem esta proposta; exige revisão explícita.')
    branch = FilialEmpresa.objects.create(codigo='FISCAL-DOC-HOM',
        nome=data['nome_fantasia'] + ' · proposta documental', cnpj=data['cnpj'],
        inscricao_estadual=data['ie'], inscricao_municipal=data['im'], ativo=False,
        endereco='PROPOSTA DOCUMENTAL — '+data['logradouro']+', '+data['numero']+', '+data['complemento']+', '+data['bairro']+', '+data['municipio']+'/'+data['uf']+', CEP '+data['cep'])
    audit(user, 'FISCAL_ESTABELECIMENTO_PROVISORIO', branch, {'ativo': False, 'homologado': False})
    config = m.ConfiguracaoFiscal.objects.create(estabelecimento=branch, tipo='NFCE',
        ambiente='HOMOLOGACAO', motor='NFCE_SVRS_HOM', habilitada=False, proposta_documental=proposta)
    audit(user, 'FISCAL_PROPOSTA_DOCUMENTAL', config, proposta)
    return config


def local():
    # This phase cannot operate against an ordinary/production database, even
    # if somebody toggles a feature flag. Only the dedicated synthetic lab.
    db=connection.settings_dict
    if not getattr(settings,'FISCAL_NFCE_LOCAL_ENABLED',False) or db.get('HOST')!='127.0.0.1' or not db['NAME'].startswith('test_') or getattr(settings,'UPLOAD_STORAGE','local')!='local' or getattr(settings,'PRIVATE_STORAGE',None):
        raise ValidationError('NFC-e desta fase exige banco sintético e armazenamento privado local; produção bloqueada.')


def evento(user,doc,name,old='',req=None):
    write(m.EventoFiscal(documento=doc,solicitacao=req,usuario=user,evento=name,anterior=old,posterior=doc.status))
    audit(user,'FISCAL_NFCE_HOM_'+name,doc,{'ambiente':'HOMOLOGACAO','estado':doc.status})


@transaction.atomic
def cadastrar_local(user,model,**values):
    require_capability(user,'fiscal_gerenciar_credenciais' if model in (m.CredencialFiscal,m.VinculoCredencialFiscal) else 'fiscal_configurar');local()
    if {'organization','organization_id'} & values.keys():raise ValidationError('Tenant é determinado exclusivamente pelo backend.')
    allowed={m.ConfiguracaoFiscal,m.ConfiguracaoNFCe,m.TributacaoProdutoNFCe,m.PagamentoFiscalNFCe,m.PerfilFiscalEstabelecimento,m.CredencialFiscal,m.VinculoCredencialFiscal,m.SerieFiscal,m.RegraTributariaFiscal}
    if model not in allowed:raise ValidationError('Modelo não permitido no laboratório NFC-e.')
    if model is m.ConfiguracaoFiscal:
        values.update(tipo='NFCE',ambiente='HOMOLOGACAO',motor='NFCE_SVRS_HOM')
        branch = values.get('estabelecimento')
        if branch and values.get('habilitada') and m.ConfiguracaoFiscal.objects.filter(estabelecimento=branch).exclude(proposta_documental={}, preparacao_fiscal={}).exists():
            raise ValidationError('Estabelecimento documental em preparação; emissão permanece bloqueada.')
    if model is m.SerieFiscal:
        if not values.get('proximo_numero'):raise ValidationError('Informe explicitamente o próximo número homologado.')
        values.update(tipo='NFCE',ambiente='HOMOLOGACAO')
    if model is m.CredencialFiscal:values.update(ambiente='HOMOLOGACAO',mecanismo='REFERENCIA')
    if model in (m.ConfiguracaoNFCe,m.TributacaoProdutoNFCe,m.PagamentoFiscalNFCe,m.RegraTributariaFiscal,m.VinculoCredencialFiscal):
        config=values.get('configuracao')
        if isinstance(config,m.ConfiguracaoNFCe):config=config.configuracao
        if config is None or (config.tipo,config.ambiente,config.motor)!=('NFCE','HOMOLOGACAO','NFCE_SVRS_HOM'):raise ValidationError('Cadastro só pode vincular configuração NFC-e homologação desta organização.')
    row=model(**values);row.save();audit(user,'FISCAL_NFCE_HOM_CADASTRO',row,{'modelo':model.__name__,'id':row.pk})
    return row


def validar_config(config,serie,cred,regra):
    local()
    if config.proposta_documental or config.preparacao_fiscal:
        raise ValidationError('EMISSÃO BLOQUEADA — preparação documental não autoriza emissão nesta etapa.')
    for obj in [config,serie,cred,regra]:obj.full_clean()
    if not config.habilitada or (config.tipo,config.ambiente,config.motor)!=('NFCE','HOMOLOGACAO','NFCE_SVRS_HOM') or not config.estabelecimento.ativo:
        raise ValidationError('Configuração não habilitada para NFC-e/Sergipe/homologação.')
    if (serie.estabelecimento_id,serie.tipo,serie.ambiente)!=(config.estabelecimento_id,'NFCE','HOMOLOGACAO'):
        raise ValidationError('Série de outro estabelecimento/ambiente.')
    if not serie.serie.isdigit() or not 0<=int(serie.serie)<=889 or not 1<=serie.proximo_numero<=999999999:
        raise ValidationError('Informe série e numeração homologadas; não são geradas por cadastro automático.')
    if not cred.ativa or cred.mecanismo!='REFERENCIA' or cred.ambiente!='HOMOLOGACAO' or cred.expira_em and cred.expira_em<=timezone.now() or not m.VinculoCredencialFiscal.objects.filter(configuracao=config,credencial=cred).exists():
        raise ValidationError('Referência de cofre ausente/inválida ou de outra configuração.')
    today=timezone.localdate()
    if regra.configuracao_id!=config.pk or regra.inicio>today or regra.fim and regra.fim<today:
        raise ValidationError('Regra tributária fora da configuração/vigência.')
    try:profile=config.estabelecimento.perfil_fiscal;cfg=config.nfce
    except (m.PerfilFiscalEstabelecimento.DoesNotExist,m.ConfiguracaoNFCe.DoesNotExist):
        raise ValidationError('Faltam perfil fiscal ou parâmetros NFC-e do estabelecimento.')
    company=ConfiguracaoEmpresa.objects.first();branch=config.estabelecimento
    missing=[]
    for name,value in [('CNPJ da organização',current_organization().cnpj),('CNPJ do estabelecimento',branch.cnpj),('razão social',current_organization().razao_social),('IE do estabelecimento',branch.inscricao_estadual),('CRT',company.crt if company else ''),('regime tributário',company.regime_tributario if company else ''),('atividade',profile.atividade),('município',cfg.municipio_nome)]:
        if not value:missing.append(name)
    for name in ['logradouro','numero','bairro','cep']:
        if not profile.endereco_estruturado.get(name):missing.append('endereço/'+name)
    if missing:raise ValidationError('Dados do emitente ausentes: '+', '.join(missing))
    if branch.cnpj[:8]!=current_organization().cnpj[:8]:
        raise ValidationError('CNPJ do estabelecimento não pertence à identidade jurídica desta organização.')
    # Duplicate branches for a legal issuer must not split the numbering ledger.
    if m.SerieFiscal.objects.filter(tipo='NFCE',ambiente='HOMOLOGACAO',serie=serie.serie,estabelecimento__cnpj=branch.cnpj).exclude(estabelecimento=branch).exists():
        raise ValidationError('Mesmo emitente/série cadastrado em outro estabelecimento; numeração deve ser única.')
    if profile.uf!='SE' or not profile.municipio_ibge.startswith('28') or company.crt not in ('1','2','3','4'):
        raise ValidationError('UF/município/CRT incompatíveis com NFC-e de Sergipe.')
    if not cfg.urls_confirmadas or not cfg.qr_url or not cfg.consulta_url or not cfg.fonte_urls or cfg.qr_versao!='3':
        raise ValidationError('URLs oficiais de QR/consulta SE e aplicabilidade QR v3 não confirmadas.')
    if not cfg.schema_aplicabilidade_confirmada or not cfg.schema_release:
        raise ValidationError('Release XSD oficial vigente/aplicável não confirmado.')
    return profile,cfg,company


@transaction.atomic
def preparar(user,venda_id,config_id,serie_id,credencial_id,regra_id):
    require_capability(user,'fiscal_emitir');local()
    sale=m.Venda.objects.select_for_update().get(pk=venda_id)
    config=m.ConfiguracaoFiscal.objects.get(pk=config_id);serie=m.SerieFiscal.objects.get(pk=serie_id)
    cred=m.CredencialFiscal.objects.get(pk=credencial_id);regra=m.RegraTributariaFiscal.objects.get(pk=regra_id)
    if sale.status!='FINALIZADA' or not sale.snapshot:raise ValidationError('NFC-e exige venda já finalizada.')
    profile,cfg,company=validar_config(config,serie,cred,regra)
    existing=m.DocumentoFiscal.objects.filter(venda=sale,tipo='NFCE',ambiente='HOMOLOGACAO',configuracao_fiscal__isnull=False).first()
    if existing:
        if (existing.configuracao_fiscal_id,existing.serie_fiscal_id,existing.credencial_fiscal_id,existing.regra_fiscal_id)!=(config.pk,serie.pk,cred.pk,regra.pk):raise ValidationError('Venda já possui operação fiscal em outra configuração.')
        return existing
    rows=[]
    for original in sale.snapshot['itens']:
        item=m.ItemVenda.objects.select_related('peca').get(pk=original['item'],venda=sale);part=item.peca
        tax=m.TributacaoProdutoNFCe.objects.filter(configuracao=cfg,peca=part,regra=regra).first()
        if not tax:raise ValidationError('Produto '+part.sku+': falta regra tributária NFC-e versionada.')
        # Commercial snapshot is in base units; use the product base unit, never
        # relabel the base quantity as a box/unit from an unrelated purchase.
        code=part.csosn or part.cst or part.cst_csosn
        row={'sku':original['sku'],'descricao':original['descricao'],'quantidade':original['quantidade'],'valor_unitario':original['valor_unitario'],'liquido':original['valor_liquido'],
             'ncm':part.ncm,'cfop':part.cfop,'cest':part.cest,'origem':part.origem_fiscal,'unidade':part.unidade_medida,'gtin':part.gtin,'tributacao':tax.parametros,'regra_produto':tax.pk}
        xml.produto_validar(row,company.crt,timezone.localdate())
        if not code or code!=tax.parametros.get('icms_codigo'):raise ValidationError('Produto '+part.sku+': CST/CSOSN cadastrado difere da regra explícita.')
        rows.append(row)
    payments=[]
    for payment in sale.pagamentos_pdv.select_related('forma').order_by('pk'):
        mapping=m.PagamentoFiscalNFCe.objects.filter(configuracao=cfg,forma=payment.forma).first()
        if not mapping:raise ValidationError('Pagamento '+payment.forma.nome+': falta código/integração fiscal explícitos.')
        compatible={'DINHEIRO':('01',),'PIX':('17','20'),'CREDITO':('03',),'DEBITO':('04',)}
        if mapping.codigo not in compatible.get(payment.forma.tipo_pdv,()):raise ValidationError('Código fiscal não coincide com o meio de pagamento da venda.')
        payments.append({'codigo':mapping.codigo,'valor':str(payment.valor),'recebido':str(payment.recebido),'troco':str(payment.troco),'integracao':mapping.integracao,'cnpj_instituicao':mapping.cnpj_instituicao,'bandeira':mapping.bandeira})
    customer=None
    if sale.cliente_id:
        number=''.join(c for c in sale.cliente.cpf_cnpj if c.isdigit())
        if len(number) not in (11,14):raise ValidationError('Cliente selecionado sem CPF/CNPJ fiscal válido; não será omitido silenciosamente.')
        customer={'documento':number}
    issued=timezone.localtime().replace(microsecond=0)
    snapshot={'sem_valor_fiscal':True,'ambiente':'HOMOLOGACAO','serie':serie.serie,'emissao':issued.isoformat(),'cnf':f'{secrets.randbelow(100000000):08}',
        'emitente':{'cnpj':config.estabelecimento.cnpj,'razao_social':current_organization().razao_social,'ie':config.estabelecimento.inscricao_estadual,'crt':company.crt,'uf':profile.uf,'municipio_ibge':profile.municipio_ibge,'municipio_nome':cfg.municipio_nome,'endereco':profile.endereco_estruturado},
        'itens':rows,'pagamentos':payments,'total':str(sale.total),'destinatario':customer,'natureza':cfg.natureza_operacao,'qr_url':cfg.qr_url,'consulta_url':cfg.consulta_url,
        'configuracao_versao':config.versao,'regra_versao':regra.versao}
    # Validate structure and money BEFORE reserving a number. The temporary nNF
    # is the explicitly configured next number, not a new/improvised series.
    xml.gerar(snapshot,serie.proximo_numero,issued,snapshot['cnf'])
    doc=write(m.DocumentoFiscal(estabelecimento=config.estabelecimento,configuracao_fiscal=config,serie_fiscal=serie,credencial_fiscal=cred,regra_fiscal=regra,
        tipo='NFCE',modelo='65',ambiente='HOMOLOGACAO',status='PENDENTE',serie=serie.serie,venda=sale,cliente=sale.cliente,valor=sale.total,
        descricao='NFC-e de homologação — sem valor fiscal',snapshot_fiscal=snapshot,criado_por=user))
    write(m.DetalhesNFCe(documento=doc,pagamentos_snapshot=payments));evento(user,doc,'PREPARADO')
    return doc


@transaction.atomic
def solicitar(user,doc_id,request_id,operacao='EMITIR',motivo=''):
    require_capability(user,'fiscal_cancelar' if operacao=='CANCELAR' else 'fiscal_emitir');local()
    if operacao not in ('EMITIR','CANCELAR'):raise ValidationError('Operação NFC-e não permitida.')
    doc=m.DocumentoFiscal.objects.select_for_update().get(pk=doc_id)
    validar_config(doc.configuracao_fiscal,doc.serie_fiscal,doc.credencial_fiscal,doc.regra_fiscal)
    if doc.ambiente!='HOMOLOGACAO' or doc.modelo!='65':raise ValidationError('Documento não pertence a este motor.')
    rid=uuid.UUID(str(request_id));digest=hashlib.sha256(json.dumps({'doc':doc.pk,'snapshot':doc.snapshot_fiscal,'operacao':operacao,'motivo':motivo.strip()},sort_keys=True).encode()).hexdigest()
    for existing in [m.SolicitacaoFiscal.objects.filter(request_id=rid).first(),m.SolicitacaoFiscal.objects.filter(documento=doc,operacao=operacao).first()]:
        if existing:
            if existing.payload_hash!=digest:raise ValidationError('Operação fiscal já existe com outros dados; correção explícita pendente.')
            return existing
    if operacao=='EMITIR':
        if doc.status!='PENDENTE':raise ValidationError('Estado não permite emissão; não é permitido reemitir automaticamente.')
        serie=m.SerieFiscal.objects.select_for_update().get(pk=doc.serie_fiscal_id)
        number=serie.proximo_numero
        if number>999999999:raise ValidationError('Numeração esgotada.')
        serie.proximo_numero+=1;write(serie);write(m.ReservaNumeracaoFiscal(serie=serie,documento=doc,numero=number))
        issued=timezone.datetime.fromisoformat(doc.snapshot_fiscal['emissao'])
        _,key=xml.gerar(doc.snapshot_fiscal,number,issued,doc.snapshot_fiscal['cnf']);doc.numero=str(number);doc.chave=key;write(doc)
    elif doc.status!='AUTORIZADA' or not 15<=len(motivo.strip())<=255:
        raise ValidationError('Cancelamento exige autorização anterior e justificativa de 15–255 caracteres.')
    req=write(m.SolicitacaoFiscal(documento=doc,request_id=rid,operacao=operacao,solicitante=user,payload_hash=digest,motivo=motivo.strip()))
    evento(user,doc,'SOLICITADO',req=req);return req


def arquivar(user,req,content,kind,result=None):
    file=m.Documento.objects.create(fiscal=req.documento,tipo='FISCAL_XML',titulo='NFC-e HOM '+kind,
        arquivo=ContentFile(content,name='nfce-hom.xml'),sha256=hashlib.sha256(content).hexdigest(),enviado_por=user,disponivel_portal=False)
    return write(m.ArtefatoNFCe(solicitacao=req,arquivo=file,tipo=kind,codigo=result.codigo if result else '',protocolo=result.protocolo if result else '',recibo=result.recibo if result else ''))


def resumo_retorno(user,req_id):
    """Private fiscal access; escaped display text, never logged provider text."""
    import re
    require_capability(user,'fiscal_consultar');local()
    req=m.SolicitacaoFiscal.objects.get(pk=req_id)
    artifact=req.artefatos_nfce.filter(tipo='RESPOSTA').exclude(codigo='').order_by('-pk').first()
    if not artifact:return None
    message='Consulte o retorno privado e revise os dados com o responsável fiscal.'
    try:
        with artifact.arquivo.arquivo.open('rb') as stream:root=parse(stream.read())
        values=root.findall('.//{'+NFE+'}xMotivo')
        if values:
            value=' '.join((values[-1].text or '').split())[:250]
            if value and not re.search(r'PRIVATE KEY|CERTIFICATE|senha|password|token|secret|cofre://|csc',value,re.I):message=value
    except (ValidationError,OSError):pass
    return {'codigo':artifact.codigo,'mensagem':message,'timestamp':artifact.criado_em}


def processar(user,req_id,motor=None):
    local();motor=motor or MotorNFCeHomologacao()
    with transaction.atomic():
        req=m.SolicitacaoFiscal.objects.select_for_update().get(pk=req_id)
        require_capability(user,'fiscal_cancelar' if req.operacao=='CANCELAR' else 'fiscal_emitir')
        doc=req.documento;validar_config(doc.configuracao_fiscal,doc.serie_fiscal,doc.credencial_fiscal,doc.regra_fiscal)
        if req.estado=='CONCLUIDA' or req.lease_ate and req.lease_ate>timezone.now():return req
        token=uuid.uuid4();req.lease_token=token;req.lease_ate=timezone.now()+timedelta(minutes=5);req.estado='ENVIANDO';write(req)
        old=doc.status
        if req.operacao=='EMITIR':doc.status='ENVIANDO';write(doc)
        write(m.TentativaFiscal(solicitacao=req,resultado='INICIADA'));evento(user,doc,'ENVIANDO',old,req)
    sent=req.artefatos_nfce.filter(tipo='ENVIADO').first()
    try:
        motor.validar(doc)
        if sent:
            receipt=req.artefatos_nfce.exclude(recibo='').order_by('-pk').first()
            # Uncertain cancellation is also queried by key: never resend it.
            response=motor.consultar_recibo(doc,receipt.recibo) if req.operacao=='EMITIR' and receipt else motor.consultar(doc)
        else:
            if req.operacao=='EMITIR':
                unsigned,key=xml.gerar(doc.snapshot_fiscal,int(doc.numero),timezone.datetime.fromisoformat(doc.snapshot_fiscal['emissao']),doc.snapshot_fiscal['cnf'])
                if key!=doc.chave:raise ValidationError('Chave diverge da reserva.')
            else:
                unsigned=xml.cancelamento(doc.chave,doc.snapshot_fiscal['emitente']['cnpj'],doc.protocolo,req.motivo,timezone.localtime().replace(microsecond=0),req.pk)
            signed=motor.preparar_assinado(doc,unsigned,req.operacao)
            # Durable marker BEFORE transport. A crash after this point can
            # only consult, never transmit a second authorization blindly.
            with transaction.atomic():
                locked=m.SolicitacaoFiscal.objects.select_for_update().get(pk=req.pk)
                if locked.lease_token!=token:return locked
                arquivar(user,locked,unsigned,'PREPARADO');sent=arquivar(user,locked,signed,'ENVIADO')
            response=motor.emitir(doc,signed) if req.operacao=='EMITIR' else motor.cancelar(doc,signed)
        # Validation of signed XML and response XSD are dependency gates in the
        # default adapter; local tests inject a clearly synthetic transport.
        schema=motor.schema
        if schema is None:
            from .schema import SchemaOficial
            schema=SchemaOficial(getattr(settings,'FISCAL_NFCE_SCHEMA_DIR',None),doc.configuracao_fiscal.nfce.schema_release)
        response_root=parse(response)
        fiscal_nodes=[n for n in response_root.iter() if n.tag in ['{'+NFE+'}retEnviNFe','{'+NFE+'}retConsSitNFe','{'+NFE+'}retEnvEvento','{'+NFE+'}retConsReciNFe']]
        if len(fiscal_nodes)!=1:raise ValidationError('Retorno fiscal ausente/ambíguo.')
        response=etree.tostring(fiscal_nodes[0])
        with transaction.atomic():
            current=m.SolicitacaoFiscal.objects.select_for_update().get(pk=req.pk)
            if current.lease_token!=token:return current
            # Preserve the original return before schema/protocol validation;
            # it cannot authorize anything until both gates succeed.
            arquivar(user,current,response,'RESPOSTA')
        root_name=etree.QName(fiscal_nodes[0]).localname
        schema.validar(response,{'retEnviNFe':'retEnviNFe_v4.00.xsd','retConsSitNFe':'retConsSitNFe_v4.00.xsd','retConsReciNFe':'retConsReciNFe_v4.00.xsd','retEnvEvento':'retEnvEventoCancNFe_v1.00.xsd'}[root_name])
        signed_original=sent.arquivo.arquivo
        with signed_original.open('rb') as f:signed_data=f.read()
        signed_root=parse(signed_data);digest=signed_root.findtext('.//{http://www.w3.org/2000/09/xmldsig#}DigestValue')
        result=transport.retorno(response,doc.chave,req.operacao,digest)
    except Exception as failure:
        # A sent artifact means the outcome is unknown even for parse/storage
        # errors. Never record a rejection based on an exception, never log it.
        with transaction.atomic():
            current=m.SolicitacaoFiscal.objects.select_for_update().get(pk=req.pk)
            if current.lease_token==token:
                current.estado='RESULTADO_DESCONHECIDO' if sent else 'BLOQUEADA';current.lease_ate=None;write(current)
                if not sent and req.operacao=='EMITIR':
                    doc=m.DocumentoFiscal.objects.select_for_update().get(pk=doc.pk)
                    doc.status='PENDENTE';write(doc)
                write(m.TentativaFiscal(solicitacao=current,resultado='TIMEOUT' if isinstance(failure,TimeoutError) and sent else current.estado));evento(user,doc,current.estado,req=current)
            return current
    with transaction.atomic():
        current=m.SolicitacaoFiscal.objects.select_for_update().get(pk=req.pk)
        if current.lease_token!=token:return current
        require_capability(user,'fiscal_cancelar' if current.operacao=='CANCELAR' else 'fiscal_emitir')
        validar_config(doc.configuracao_fiscal,doc.serie_fiscal,doc.credencial_fiscal,doc.regra_fiscal)
        doc=m.DocumentoFiscal.objects.select_for_update().get(pk=doc.pk);old=doc.status
        arquivar(user,current,response,'RESPOSTA',result)
        if result.status=='RESULTADO_DESCONHECIDO':
            current.estado=result.status
        else:
            if current.operacao=='EMITIR':
                doc.status=result.status
                if result.status=='AUTORIZADA':
                    doc.protocolo=result.protocolo;doc.autorizado_em=timezone.now()
                    processed=etree.Element('{'+NFE+'}nfeProc',versao='4.00',nsmap={None:NFE});processed.append(parse(signed_data))
                    protocol=parse(response).find('{'+NFE+'}protNFe')
                    processed.append(protocol);arquivar(user,current,etree.tostring(processed),'PROCESSADO',result)
            elif result.status=='CANCELADA':
                doc.status='CANCELADA' # Keep original authorization key/protocol/XML.
            write(doc);current.estado='CONCLUIDA'
        current.lease_ate=None;write(current)
        write(m.TentativaFiscal(solicitacao=current,resultado=result.status));evento(user,doc,result.status,old,current)
        return current
