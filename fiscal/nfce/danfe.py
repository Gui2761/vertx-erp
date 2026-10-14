"""Local NFC-e DANFE preparation; not certified against current SE/manual yet."""
import hashlib
from io import BytesIO
from xml.sax.saxutils import escape
import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from platform_core.modules import require_capability
from gestao.services import write
from operacao import models as m
from . import services as s,xml


def render(snapshot,*,numero,chave,protocolo,emissao):
    if snapshot.get('ambiente')!='HOMOLOGACAO' or not protocolo:
        raise ValidationError('DANFE exige homologação e protocolo de autorização confirmado.')
    url=xml.qr_online(chave,snapshot['qr_url']);data=BytesIO()
    normal=ParagraphStyle('NFCe',fontName='Helvetica',fontSize=7,leading=10,spaceAfter=3)
    center=ParagraphStyle('NFCeCenter',parent=normal,alignment=TA_CENTER)
    strong=ParagraphStyle('NFCeWarning',parent=center,fontName='Helvetica-Bold',fontSize=9,leading=12,spaceAfter=5)
    def p(text,style=normal):return Paragraph(escape(str(text)),style)
    issuer=snapshot['emitente'];address=issuer['endereco']
    story=[p('VERTYX',strong),p('AMBIENTE DE HOMOLOGACAO',strong),p('SEM VALOR FISCAL',strong),p(issuer['razao_social'],center),p('CNPJ '+issuer['cnpj']+' | IE '+issuer['ie'],center),p(address['logradouro']+', '+address['numero']+' - '+address['bairro'],center),p(issuer['municipio_nome']+'/'+issuer['uf']+' | CEP '+address['cep'],center),Spacer(1,3*mm),p('DANFE NFC-e - Documento Auxiliar da Nota Fiscal de Consumidor Eletronica',center),p('Não permite aproveitamento de crédito de ICMS',center)]
    rows=[[p('Código / descrição'),p('Qtd / un'),p('Unit.'),p('Total')]]
    for row in snapshot['itens']:
        rows.append([p(row['sku']+' / '+row['descricao']),p(row['quantidade']+' '+row['unidade']),p(xml.money(xml.decimal(row['valor_unitario']))),p(xml.money(xml.decimal(row['liquido'])))])
    table=Table(rows,colWidths=[32*mm,13*mm,12*mm,15*mm],repeatRows=1,hAlign='CENTER')
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.3,colors.grey),('LEFTPADDING',(0,0),(-1,-1),1),('RIGHTPADDING',(0,0),(-1,-1),1)]));story.extend([table,Spacer(1,3*mm),p('Itens: '+str(len(rows)-1)),p('TOTAL R$ '+snapshot['total'],strong)])
    names={'01':'Dinheiro','03':'Cartão de crédito','04':'Cartão de débito','17':'PIX dinâmico','20':'PIX estático'}
    for payment in snapshot['pagamentos']:story.append(p(names[payment['codigo']]+' recebido R$ '+payment['recebido']+' / aplicado R$ '+payment['valor']))
    change=sum(xml.decimal(row['troco']) for row in snapshot['pagamentos']);story.append(p('Troco R$ '+xml.money(change)))
    story.extend([Spacer(1,3*mm),p('NFC-e '+str(numero)+' | Série '+snapshot['serie']+' | Emissão '+emissao,center),p('Protocolo de autorização: '+protocolo,center),p('Chave de acesso',center),p(' '.join(chave[i:i+4] for i in range(0,44,4)),center)])
    image=BytesIO();qrcode.make(url).save(image,format='PNG');image.seek(0);story.append(Image(image,width=35*mm,height=35*mm,hAlign='CENTER'))
    story.extend([p('Consulta pela chave: '+snapshot['consulta_url'],center),p('Consumidor '+('identificado' if snapshot.get('destinatario') else 'não identificado'),center),p('PREVIA LOCAL - HOMOLOGACAO SEM VALOR FISCAL',strong),p('Leiaute e URLs oficiais de Sergipe aguardam homologação externa.',center)])
    SimpleDocTemplate(data,pagesize=(80*mm,297*mm),leftMargin=4*mm,rightMargin=4*mm,topMargin=5*mm,bottomMargin=5*mm).build(story)
    return data.getvalue()


@transaction.atomic
def gerar(user,doc_id):
    require_capability(user,'fiscal_consultar');s.local()
    doc=m.DocumentoFiscal.objects.select_for_update().get(pk=doc_id,tipo='NFCE',ambiente='HOMOLOGACAO')
    if doc.status!='AUTORIZADA':raise ValidationError('DANFE não é autorização; exige documento autorizado.')
    req=doc.solicitacoes_fiscais.get(operacao='EMITIR',estado='CONCLUIDA')
    if not req.artefatos_nfce.filter(tipo='PROCESSADO').exists():raise ValidationError('XML com protocolo não foi armazenado.')
    existing=req.artefatos_nfce.filter(tipo='DANFE').first()
    if existing:return existing.arquivo
    content=render(doc.snapshot_fiscal,numero=doc.numero,chave=doc.chave,protocolo=doc.protocolo,emissao=doc.snapshot_fiscal['emissao'])
    file=m.Documento.objects.create(fiscal=doc,tipo='FISCAL_PDF',titulo='DANFE NFC-e HOMOLOGACAO SEM VALOR FISCAL',arquivo=ContentFile(content,name='danfe-nfce-hom.pdf'),sha256=hashlib.sha256(content).hexdigest(),enviado_por=user,disponivel_portal=False)
    write(m.ArtefatoNFCe(solicitacao=req,arquivo=file,tipo='DANFE',protocolo=doc.protocolo));s.evento(user,doc,'DANFE_LOCAL',req=req)
    return file
