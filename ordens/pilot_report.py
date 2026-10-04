"""Padrão 2: somente snapshot técnico, sem consultar a medição contratual."""
import base64
import hashlib
import io
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Foto
from .storage import private_storage
from .services import digest
from .templatetags.ordens_format import data_os


def render(assinatura):
    assinatura.validate_tenant()
    d=assinatura.conferencia.dados; issuer=d['organization']
    if issuer['id']!=str(assinatura.ordem.organization.public_id) or digest(d)!=assinatura.conferencia.digest:
        raise ValidationError('Snapshot ou emissor inconsistente.')
    raw=base64.b64decode(assinatura.imagem)
    if hashlib.sha256(raw).hexdigest()!=assinatura.imagem_sha256:
        raise ValidationError('Assinatura não corresponde ao hash.')
    output=io.BytesIO(); styles=getSampleStyleSheet()
    styles.add(ParagraphStyle('OSBody',fontSize=9,leading=12,spaceAfter=4,wordWrap='CJK'))
    styles.add(ParagraphStyle('OSCaption',fontSize=7.5,leading=10,spaceAfter=3,textColor=colors.HexColor('#526779'),wordWrap='CJK'))
    styles.add(ParagraphStyle('OSBrand',fontSize=20,leading=24,textColor=colors.HexColor('#143e59'),spaceAfter=6))
    story=[]
    def p(value,style='OSBody'):
        return Paragraph(escape(str(value or '-')).replace('\n','<br/>'),styles[style])
    def section(title): story.append(p(title,'Heading2'))
    def fields(rows):
        table=Table([[p(label),p(value)] for label,value in rows],colWidths=[38*mm,134*mm],hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#edf4f8')),('LINEBELOW',(0,0),(-1,-1),.25,colors.HexColor('#d6e0e7')),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        story.extend([table,Spacer(1,3*mm)])
    if issuer.get('logo_key'):
        try:
            with private_storage.open(issuer['logo_key'],'rb') as f: logo=Image(io.BytesIO(f.read()))
            logo._restrictSize(50*mm,18*mm); story.append(logo)
        except (OSError,FileNotFoundError): pass
    story.extend([p(issuer['nome'],'OSBrand'),p(issuer.get('razao_social'),'OSCaption'),p(' · '.join(filter(None,[issuer.get('cnpj'),issuer.get('telefone'),issuer.get('email')])),'OSCaption'),p(issuer.get('details'),'OSCaption'),p('VERTYX | ASSISTÊNCIA TÉCNICA | COMPROVANTE DE ATENDIMENTO','OSCaption'),p(f"{d['numero']} · Versão {assinatura.ciclo} · {d.get('status','Finalizada')}",'Heading1')])
    section('Cliente e local de atendimento')
    fields([('Cliente / CPF-CNPJ',f"{d['cliente']} / {d['documento']}"),('Contrato',d.get('contrato')),('Unidade / setor',f"{d['unidade']} / {d.get('setor','')}"),('Endereço do atendimento',d['local']),('Endereço do cliente',d['cliente_endereco']),('Responsável',d.get('responsavel')),('Contato',f"{d['cliente_telefone']} / {d['cliente_email']}")])
    section('Atendimento técnico')
    fields([('Tipo / status',f"{d['tipo']} / {d.get('status','Finalizada')}"),('Técnico / registro',f"{d['tecnico']} / {d['registro_profissional'] or 'Não cadastrado'}"),('Abertura',data_os(d['abertura'])),('Início da OS',data_os(d['inicio'])),('Término técnico',data_os(d['conclusao'])),('Duração técnica da OS',d.get('duracao_tecnica'))])
    section('Equipamento')
    fields([('Equipamento',d['equipamento']),('Fabricante / modelo',f"{d['fabricante']} / {d['modelo']}"),('Série / patrimônio',f"{d['serie']} / {d['patrimonio']}"),('Setor',d.get('setor'))])
    section('Relatório técnico')
    for label,key in [('Problema / solicitação','defeito'),('Diagnóstico','diagnostico'),('Serviço executado','servico_executado'),('Causa provável','causa_provavel'),('Solução aplicada','solucao'),('Condição final do equipamento','condicao_final'),('Recomendações','recomendacoes'),('Pendências','pendencias')]:
        story.extend([p(label,'Heading3'),p(d.get(key) or 'Não informado')])
    if d.get('checklist'):
        section('Checklist, testes e medições')
        for item in d['checklist']:
            answer=item.get('resposta')
            if isinstance(answer,bool): answer=('Conforme' if answer else 'Não conforme') if item.get('tipo')=='CONFORMIDADE' else ('Sim' if answer else 'Não')
            if item.get('tipo')=='FOTO' and answer: answer=f'Foto #{answer}'
            story.append(p(f"{item['item']} · {'Concluído' if item.get('concluido') else 'Pendente'} · {answer if answer is not None else '-'} {item.get('unidade','')} · {item.get('observacao','')}"))
    section('Materiais utilizados')
    story.extend([p(d.get('pecas') or 'Sem peças informadas'),p(d.get('materiais'))])
    for item in d.get('pecas_estoque',[]):
        for lot in item.get('lotes',[]): story.append(p(f"{item['sku']} | {item['tipo']} | Lote {lot['numero']} | Quantidade {lot['quantidade']}",'OSCaption'))
    if d.get('observacoes'): section('Observações'); story.append(p(d['observacoes']))
    section('Fotografias do atendimento')
    for item in sorted(d['fotos'],key=lambda f:({'Antes':0,'Durante':1,'Depois':2}.get(f.get('categoria'),3),f['id'])):
        photo=Foto.objects.get(pk=item['id'],ordem=assinatura.ordem)
        with photo.arquivo.open('rb') as f: image_bytes=f.read()
        if hashlib.sha256(image_bytes).hexdigest()!=item['sha256']: raise ValidationError('Foto não corresponde ao snapshot.')
        image=Image(io.BytesIO(image_bytes)); image._restrictSize(148*mm,65*mm)
        story.append(KeepTogether([p(item.get('categoria','Sem classificação').upper(),'Heading3'),image,p(f"{item.get('descricao') or 'Foto do atendimento'} | {data_os(item['data'])}",'OSCaption'),Spacer(1,3*mm)]))
    if not d['fotos']: story.append(p('Sem fotografias anexadas.'))
    signature=Image(io.BytesIO(raw)); signature._restrictSize(78*mm,28*mm)
    left=[p('Responsável do cliente','Heading3'),p(f'{assinatura.nome} · {assinatura.cargo}'),signature]
    right=[p('Responsável técnico','Heading3'),p(f"{d['tecnico']} · {d['registro_profissional'] or 'Sem registro informado'}")]
    if assinatura.imagem_tecnico:
        tech_raw=base64.b64decode(assinatura.imagem_tecnico)
        if hashlib.sha256(tech_raw).hexdigest()!=assinatura.imagem_tecnico_sha256: raise ValidationError('Assinatura técnica alterada.')
        tech_image=Image(io.BytesIO(tech_raw)); tech_image._restrictSize(78*mm,28*mm)
        right.extend([tech_image,p(f'Confirmação gráfica registrada por {assinatura.usuario}','OSCaption')])
    else: right.append(p(f'Registro autenticado por {assinatura.usuario}; assinatura gráfica técnica não coletada.','OSCaption'))
    signatures=Table([[left,right]],colWidths=[86*mm,86*mm]); signatures.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    # Nota e hashes pertencem ao bloco de assinaturas: não ficam órfãos.
    story.append(KeepTogether([p('Assinaturas e integridade','Heading2'),signatures,p(f"Assinado em {timezone.localtime(assinatura.assinado_em).strftime('%d/%m/%Y %H:%M:%S %z')}",'OSCaption'),p('Assinatura eletrônica de recebimento coletada na interface do atendimento.','OSCaption'),p('Versão conferida SHA-256: '+assinatura.conferencia.digest,'OSCaption'),p('Assinatura do cliente SHA-256: '+assinatura.imagem_sha256,'OSCaption'),p('Assinatura técnica SHA-256: '+assinatura.imagem_tecnico_sha256,'OSCaption') if assinatura.imagem_tecnico else Spacer(1,1)]))
    def footer(canvas,doc):
        canvas.setFont('Helvetica',8); canvas.setFillColor(colors.HexColor('#526779'))
        canvas.drawString(19*mm,11*mm,f"{issuer['nome'][:48]} | {d['numero']} | v{assinatura.ciclo} | Padrão 2")
        canvas.drawRightString(191*mm,11*mm,f'Página {doc.page}')
    SimpleDocTemplate(output,pagesize=A4,leftMargin=19*mm,rightMargin=19*mm,topMargin=16*mm,bottomMargin=20*mm,title=f"{d['numero']} - {issuer['nome']}",author=issuer['nome'],invariant=1).build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
