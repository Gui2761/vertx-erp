"""Relatório sempre baseado na versão imutável que foi conferida e assinada."""
import base64
import io
import hashlib
from xml.sax.saxutils import escape
from django.core.exceptions import ValidationError
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from .models import Foto
from .templatetags.ordens_format import data_os
from .storage import private_storage


def gerar_pdf_legado(assinatura):
    assinatura.validate_tenant()
    from .services import digest
    dados = assinatura.conferencia.dados
    issuer = dados.get('organization') or assinatura.conferencia.issuer
    if not issuer or issuer.get('id') != str(assinatura.ordem.organization.public_id):
        raise ValidationError('Emissor do documento incompatível com a organização da OS.')
    marca = issuer['nome']
    if digest(dados) != assinatura.conferencia.digest or hashlib.sha256(base64.b64decode(assinatura.imagem)).hexdigest() != assinatura.imagem_sha256:
        raise ValidationError('Falha de integridade na versão assinada. Verifique o armazenamento.')
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('Marca', fontSize=23, leading=28, textColor=colors.HexColor('#143e59')))
    styles.add(ParagraphStyle('TextoOS', fontSize=10, leading=15, spaceAfter=7, wordWrap='CJK'))
    styles.add(ParagraphStyle('LegendaOS', fontSize=8, leading=11, textColor=colors.HexColor('#526779')))
    story = []

    def paragraph(value, style='TextoOS'):
        return Paragraph(escape(str(value or '-')).replace('\n', '<br/>'), styles[style])

    def campo(label, value):
        story.append(Paragraph(f'<b>{escape(label)}</b><br/>{escape(str(value or "-")).replace(chr(10), "<br/>")}', styles['TextoOS']))

    if issuer.get('logo_key'):
        try:
            with private_storage.open(issuer['logo_key'], 'rb') as stream:
                img = Image(io.BytesIO(stream.read()))
            img._restrictSize(55 * mm, 22 * mm)
            story.append(img)
        except (FileNotFoundError, OSError):
            pass  # Identificação textual sempre permanece disponível.
    story.append(paragraph(marca, 'Marca'))
    if issuer.get('cnpj'):
        story.append(paragraph(issuer['cnpj'], 'LegendaOS'))
    if issuer.get('details'):
        story.append(paragraph(issuer['details'], 'LegendaOS'))
    story.append(paragraph('ASSISTÊNCIA TÉCNICA • COMPROVANTE DE ATENDIMENTO', 'LegendaOS'))
    story.append(Spacer(1, 5 * mm))
    story.append(paragraph(f'{dados["numero"]} | Versão {assinatura.ciclo}', 'Heading1'))
    rows = [[paragraph('Cliente'), paragraph(dados['cliente'])], [paragraph('CPF/CNPJ'), paragraph(dados['documento'])], [paragraph('Endereço'), paragraph(dados['cliente_endereco'])], [paragraph('Contato'), paragraph(' | '.join(v for v in [dados['cliente_telefone'], dados['cliente_email']] if v))], [paragraph('Unidade / local'), paragraph(f'{dados["unidade"]}\n{dados["local"]}')], [paragraph('Equipamento'), paragraph(f'{dados["equipamento"]} - {dados["fabricante"]} {dados["modelo"]}')], [paragraph('Patrimônio / série'), paragraph(f'{dados["patrimonio"] or "-"} / {dados["serie"] or "-"}')], [paragraph('Técnico / registro'), paragraph(f'{dados["tecnico"]} / {dados["registro_profissional"] or "-"}')]]
    table = Table(rows, colWidths=[40 * mm, 132 * mm], hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#edf4f8')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#d6e0e7')), ('LEFTPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 6)]))
    story.extend([table, Spacer(1, 5 * mm)])
    for label, key in [('Tipo de atendimento', 'tipo'), ('Abertura', 'abertura'), ('Início do atendimento', 'inicio'), ('Conclusão do serviço (conferência)', 'conclusao'), ('Defeito / reclamação', 'defeito'), ('Diagnóstico', 'diagnostico'), ('Serviço executado', 'servico_executado'), ('Peças utilizadas', 'pecas'), ('Observações', 'observacoes')]:
        campo(label, data_os(dados[key]) if key in ['abertura', 'inicio', 'conclusao'] else dados[key])
    for label, key in [('Contrato', 'contrato'), ('Prioridade', 'prioridade'), ('Horas trabalhadas', 'horas'), ('Deslocamento (km)', 'deslocamento_km')]:
        if key in dados:
            campo(label, dados[key])
    for label, key in [('Causa provável', 'causa_provavel'), ('Solução aplicada', 'solucao'), ('Recomendações', 'recomendacoes'), ('Materiais utilizados', 'materiais')]:
        if dados.get(key):
            campo(label, dados[key])
    if dados.get('auxiliares'):
        campo('Equipe auxiliar', ', '.join(dados['auxiliares']))
    if dados.get('checklist'):
        answers = []
        for item in dados['checklist']:
            answer = item.get('resposta')
            if item.get('tipo') in ['BOOLEANO', 'CONFORMIDADE'] and type(answer) is bool:
                answer = ('Conforme' if answer else 'Não conforme') if item['tipo'] == 'CONFORMIDADE' else ('Sim' if answer else 'Não')
            if item.get('tipo') == 'FOTO' and answer:
                answer = f'Foto #{answer}'
            response = f' · {answer} {item.get("unidade", "")}'.rstrip() if answer is not None and answer != '' else ''
            answers.append(('Concluído: ' if item.get('concluido') else 'Pendente: ') + item['item'] + response + (' · ' + item.get('observacao', '') if item.get('observacao') else ''))
        campo('Checklist / medições', '\n'.join(answers))
    for label, key in [('Localização inicial', 'localizacao_inicio'), ('Localização final', 'localizacao_final')]:
        geo = dados[key]
        block = [Paragraph(f'<b>{escape(label)}</b><br/>{escape(geo["resultado"])} | {escape(str(data_os(geo["data"])))}<br/>Latitude: {escape(geo["latitude"] or "-")}; longitude: {escape(geo["longitude"] or "-")}; precisão: {escape(geo["precisao"] or "-")} m<br/>Registrado por: {escape(geo["usuario"] or "-")}', styles['TextoOS'])]
        if geo['mapa']:
            block.append(Paragraph(f'<link href="{escape(geo["mapa"], {chr(34): "&quot;"})}">Ver localização no mapa</link>', styles['TextoOS']))
        story.append(KeepTogether(block))
    story.append(paragraph('Fotografias do atendimento', 'Heading2'))
    for item in dados['fotos']:
        foto = Foto.objects.get(pk=item['id'], ordem=assinatura.ordem)
        with foto.arquivo.open('rb') as stream:
            raw = stream.read()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValidationError('Uma fotografia não corresponde à versão assinada.')
        image = Image(io.BytesIO(raw))
        image._restrictSize(150 * mm, 80 * mm)
        story.append(KeepTogether([image, paragraph(f'{item.get("categoria", "")} {item["descricao"] or "Foto do atendimento"} | {data_os(item["data"])} | {item["usuario"]}', 'LegendaOS'), Spacer(1, 4 * mm)]))
    if not dados['fotos']:
        story.append(paragraph('Sem fotografias anexadas.'))
    signature = Image(io.BytesIO(base64.b64decode(assinatura.imagem)))
    signature._restrictSize(95 * mm, 38 * mm)
    story.append(KeepTogether([paragraph('Responsável pelo recebimento', 'Heading2'), paragraph(f'{assinatura.nome} | {assinatura.cargo}'), signature, paragraph(f'Assinado em {timezone.localtime(assinatura.assinado_em).strftime("%d/%m/%Y %H:%M:%S %z")}', 'LegendaOS')]))
    story.append(Spacer(1, 4 * mm))
    campo('Integridade da versão conferida (SHA-256)', assinatura.conferencia.digest)
    campo('Integridade da assinatura (SHA-256)', assinatura.imagem_sha256)
    story.append(paragraph('Assinatura eletrônica de recebimento coletada na interface do atendimento.', 'LegendaOS'))

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor('#d6e0e7'))
        canvas.line(19 * mm, 16 * mm, 191 * mm, 16 * mm)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#526779'))
        canvas.drawString(19 * mm, 11 * mm, f'{marca[:55]} | {dados["numero"]} | Versão {assinatura.ciclo}')
        canvas.drawRightString(191 * mm, 11 * mm, f'Página {doc.page}')

    SimpleDocTemplate(output, pagesize=A4, rightMargin=19 * mm, leftMargin=19 * mm, topMargin=18 * mm, bottomMargin=23 * mm, title=f'{dados["numero"]} - {marca}', author=marca).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def gerar_pdf(assinatura):
    """Primeira emissão privada; futuras leituras usam exatamente o arquivo emitido."""
    from django.db import transaction
    from django.core.files.base import ContentFile
    from .models import Assinatura, DocumentoOSAssinado
    from .services import digest
    import uuid
    assinatura.validate_tenant()
    if digest(assinatura.conferencia.dados) != assinatura.conferencia.digest:
        raise ValidationError('Snapshot assinado alterado.')
    if hashlib.sha256(base64.b64decode(assinatura.imagem)).hexdigest()!=assinatura.imagem_sha256:
        raise ValidationError('Assinatura alterada.')
    if assinatura.imagem_tecnico and hashlib.sha256(base64.b64decode(assinatura.imagem_tecnico)).hexdigest()!=assinatura.imagem_tecnico_sha256:
        raise ValidationError('Assinatura técnica alterada.')
    with transaction.atomic():
        Assinatura.objects.select_for_update().get(pk=assinatura.pk)
        existing=DocumentoOSAssinado.objects.filter(assinatura=assinatura).first()
        if existing:
            with existing.arquivo.open('rb') as f: content=f.read()
            if hashlib.sha256(content).hexdigest()!=existing.sha256:
                raise ValidationError('PDF emitido não corresponde ao hash.')
            return content
        if assinatura.conferencia.dados.get('pdf_modelo', 1) == 2:
            from .pilot_report import render
            content=render(assinatura)
        else:
            content=gerar_pdf_legado(assinatura)
        key=private_storage.save(f'organizations/{assinatura.ordem.organization.public_id}/assistencia/ordens/{assinatura.ordem.codigo}/pdf/{assinatura.ciclo}-{uuid.uuid4().hex}.pdf',ContentFile(content))
        try:
            doc=DocumentoOSAssinado(ordem=assinatura.ordem,assinatura=assinatura,arquivo=key,sha256=hashlib.sha256(content).hexdigest())
            doc.full_clean(); doc.save()
        except Exception:
            private_storage.delete(key)  # Apenas o novo arquivo cuja criação falhou.
            raise
        return content
