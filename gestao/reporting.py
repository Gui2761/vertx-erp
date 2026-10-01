import csv
import io
from decimal import Decimal
from html import escape
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from django.utils import timezone
from ordens.models import OrdemServico
from ordens.services import visiveis
from equipamentos.models import Equipamento
from . import models as m
from .permissions import allowed

REPORTS = {
    'os_periodo': ('Ordens de Serviço por período', 'operacional'),
    'os_status': ('OS por status', 'operacional'),
    'os_tecnico': ('OS por técnico', 'operacional'),
    'os_cliente': ('OS por cliente', 'operacional'),
    'equipamentos_cliente': ('Equipamentos por cliente', 'operacional'),
    'equipamentos_situacao': ('Equipamentos por situação', 'operacional'),
    'equipamentos_restricao': ('Equipamentos com restrição de uso', 'operacional'),
    'equipamentos_inoperantes': ('Equipamentos inoperantes', 'operacional'),
    'preventivas_realizadas': ('Preventivas realizadas', 'operacional'),
    'preventivas_pendentes': ('Preventivas pendentes', 'operacional'),
    'preventivas_proximas': ('Preventivas próximas do vencimento', 'operacional'),
    'pecas_utilizadas': ('Peças utilizadas', 'estoque'),
    'movimentacao_estoque': ('Movimentação de estoque', 'estoque'),
    'estoque_minimo': ('Estoque abaixo do mínimo', 'estoque'),
    'contratos_ativos': ('Contratos ativos', 'contratos'),
    'contratos_proximos': ('Contratos próximos do vencimento', 'contratos'),
    'receitas': ('Faturamento / receitas por período', 'financeiro'),
    'despesas': ('Despesas por período', 'financeiro'),
}
from operacao.reporting import REPORTS as ADDITIONAL_REPORTS
REPORTS.update(ADDITIONAL_REPORTS)


def report_allowed(user, key):
    capability = REPORTS[key][1]
    if capability == 'operacional':
        return allowed(user, 'planejamento')
    if capability == 'estoque':
        return allowed(user, 'estoque') and (key == 'pecas_utilizadas' or allowed(user, 'estoque_escrever'))
    return allowed(user, capability)


def situation(qs, status):
    if not status:
        return qs
    today = timezone.localdate()
    if qs.model is m.Lancamento:
        if status in ['PENDENTE', 'VENCIDO']:
            qs = qs.filter(status__in=['PENDENTE', 'VENCIDO'])
            return qs.filter(vencimento__lt=today) if status == 'VENCIDO' else qs.filter(vencimento__gte=today)
    if qs.model is m.Orcamento and status == 'VENCIDO':
        return qs.filter(Q(status='VENCIDO') | Q(status__in=['RASCUNHO', 'ENVIADO'], validade__lt=today))
    if qs.model is m.Orcamento and status in ['RASCUNHO', 'ENVIADO']:
        return qs.filter(status=status, validade__gte=today)
    if qs.model is m.Contrato and status in ['ATIVO', 'PROXIMO', 'VENCIDO']:
        qs = qs.exclude(status__in=['SUSPENSO', 'ENCERRADO'])
        if status == 'VENCIDO':
            return qs.filter(data_final__lt=today)
        if status == 'PROXIMO':
            return qs.filter(data_final__gte=today, data_final__lte=today + timezone.timedelta(days=30))
        return qs.filter(data_final__gt=today + timezone.timedelta(days=30))
    return qs.filter(status=status)


def filter_query(qs, data, mapping, date_field=None):
    for name, path in mapping.items():
        if data.get(name):
            selected = data[name]
            qs = qs.filter(**{path: selected.pk if path in ['pk', 'id'] and hasattr(selected, 'pk') else selected})
    if date_field:
        if data.get('inicio'):
            qs = qs.filter(**{date_field + '__gte': data['inicio']})
        if data.get('fim'):
            qs = qs.filter(**{date_field + '__lte': data['fim']})
    return qs


def legacy_preventivas(data):
    qs = filter_query(Equipamento.objects.select_related('cliente', 'unidade'), data, {'cliente': 'cliente', 'unidade': 'unidade', 'equipamento': 'pk'})
    rows = []
    for equipment in qs:
        due = equipment.proxima_preventiva
        if due and (not data.get('inicio') or due >= data['inicio']) and (not data.get('fim') or due <= data['fim']):
            rows.append((equipment, due))
    return rows


def report_data(user, key, data):
    if key in ADDITIONAL_REPORTS:
        from operacao.reporting import report_data as expanded
        return expanded(user, key, data)
    today = timezone.localdate()
    if key.startswith('os_') or key == 'preventivas_realizadas':
        qs = visiveis(user)
        date = 'abertura__date'
        if key == 'preventivas_realizadas':
            qs = qs.filter(tipo_atendimento='PREVENTIVA', status__in=['FINALIZADA','APROVADA','FATURADA'])
            date = 'conclusao__date'
        qs = filter_query(qs, data, {'cliente': 'cliente', 'unidade': 'unidade', 'tecnico': 'tecnico', 'equipamento': 'equipamento', 'status': 'status'}, date)
        order = {'os_status': 'status', 'os_tecnico': 'tecnico__nome', 'os_cliente': 'cliente__nome_razao_social'}.get(key, '-abertura')
        return ['OS', 'Cliente', 'Unidade', 'Equipamento', 'Técnico', 'Status', 'Abertura', 'Conclusão'], [[x.numero, str(x.cliente), str(x.unidade or ''), x.equipamento.nome, x.tecnico.nome if x.tecnico_id else 'Não atribuído', x.get_status_display(), timezone.localtime(x.abertura).strftime('%d/%m/%Y'), timezone.localtime(x.conclusao).strftime('%d/%m/%Y') if x.conclusao else ''] for x in qs.order_by(order, 'pk')]
    if key.startswith('equipamentos_'):
        qs = filter_query(Equipamento.objects.select_related('cliente', 'unidade'), data, {'cliente': 'cliente', 'unidade': 'unidade', 'equipamento': 'pk', 'status': 'situacao_operacional'}, 'criado_em__date')
        fixed = {'equipamentos_restricao': 'RESTRICAO', 'equipamentos_inoperantes': 'INOPERANTE'}.get(key)
        if fixed:
            qs = qs.filter(situacao_operacional=fixed)
        return ['Equipamento', 'Patrimônio', 'Cliente', 'Unidade', 'Situação', 'Próxima preventiva'], [[x.nome, x.codigo_interno, str(x.cliente), str(x.unidade or ''), x.get_situacao_operacional_display(), x.proxima_preventiva or ''] for x in qs.order_by('cliente__nome_razao_social', 'nome')]
    if key in ['preventivas_pendentes', 'preventivas_proximas']:
        qs = m.AgendaPreventiva.objects.select_related('contrato__cliente', 'equipamento__unidade', 'tecnico', 'ordem').filter(cancelada=False).exclude(contrato__status__in=['SUSPENSO', 'ENCERRADO']).exclude(ordem__status__in=['FINALIZADA','APROVADA','FATURADA','CANCELADA'])
        qs = filter_query(qs, data, {'cliente': 'contrato__cliente', 'unidade': 'equipamento__unidade', 'tecnico': 'tecnico', 'equipamento': 'equipamento'}, 'data_prevista')
        if not allowed(user, 'contratos'):
            qs = qs.filter(Q(tecnico__usuario=user) | Q(ordem__tecnico__usuario=user))
        rows = [[x.equipamento.nome, str(x.contrato.cliente), x.data_prevista, x.situacao, x.contrato.numero, x.tecnico.nome if x.tecnico else 'Não atribuído'] for x in qs if (not data.get('status') or x.situacao == data['status']) and (key != 'preventivas_proximas' or today <= x.data_prevista <= today + timezone.timedelta(days=30))]
        if not data.get('tecnico'):
            for equipment, due in legacy_preventivas(data):
                state = 'ATRASADA' if due < today else 'PENDENTE'
                if (not data.get('status') or state == data['status']) and (key != 'preventivas_proximas' or today <= due <= today + timezone.timedelta(days=30)):
                    rows.append([equipment.nome, str(equipment.cliente), due, state, 'Cadastro de equipamento', 'Não atribuído'])
        return ['Equipamento', 'Cliente', 'Prevista para', 'Situação', 'Origem', 'Técnico'], sorted(rows, key=lambda row: row[2])
    if key in ['pecas_utilizadas', 'movimentacao_estoque']:
        qs = m.Movimentacao.objects.select_related('peca', 'ordem__cliente', 'usuario')
        if key == 'pecas_utilizadas':
            qs = qs.filter(tipo__in=['OS', 'DEVOLUCAO'], ordem__isnull=False)
        if not allowed(user, 'estoque_escrever'):
            qs = qs.filter(ordem__tecnico__usuario=user)
        qs = filter_query(qs, data, {'cliente': 'ordem__cliente', 'unidade': 'ordem__unidade', 'tecnico': 'ordem__tecnico', 'equipamento': 'ordem__equipamento', 'status': 'tipo'}, 'criado_em__date')
        return ['Data', 'SKU', 'Peça', 'Tipo', 'Quantidade', 'Variação', 'Saldo após', 'OS', 'Responsável'], [[timezone.localtime(x.criado_em).strftime('%d/%m/%Y %H:%M'), x.peca.sku, x.peca.descricao, x.get_tipo_display(), x.quantidade, x.variacao, x.saldo_apos, x.ordem.numero if x.ordem else '', str(x.usuario)] for x in qs]
    if key == 'estoque_minimo':
        qs = m.Peca.objects.filter(ativo=True, quantidade_atual__lte=F('estoque_minimo'))
        return ['SKU', 'Peça', 'Saldo', 'Mínimo', 'Unidade', 'Localização'], [[x.sku, x.descricao, x.quantidade_atual, x.estoque_minimo, x.unidade_medida, x.localizacao] for x in qs]
    if key.startswith('contratos_'):
        qs = filter_query(m.Contrato.objects.select_related('cliente'), data, {'cliente': 'cliente', 'unidade': 'unidades', 'equipamento': 'equipamentos'}, 'data_final').distinct()
        qs = situation(qs, 'PROXIMO') if key == 'contratos_proximos' else qs.exclude(status__in=['SUSPENSO', 'ENCERRADO']).filter(data_final__gte=today, data_inicial__lte=today)
        if data.get('status'):
            qs = situation(qs, data['status'])
        return ['Contrato', 'Cliente', 'Início', 'Fim', 'Situação', 'Valor por cobrança', 'Periodicidade'], [[x.numero, str(x.cliente), x.data_inicial, x.data_final, x.situacao, x.valor, x.get_periodicidade_cobranca_display()] for x in qs]
    qs = m.Lancamento.objects.select_related('cliente', 'categoria').filter(tipo='RECEBER' if key == 'receitas' else 'PAGAR').exclude(status='CANCELADO')
    qs = filter_query(qs, data, {'cliente': 'cliente'}, 'data_emissao')
    for name in ['unidade', 'tecnico', 'equipamento']:
        if data.get(name):
            match = Q(**{'ordem__' + name: data[name]}) | Q(**{'orcamento__ordem_convertida__' + name: data[name]}) | Q(**{'orcamento__ordem__' + name: data[name]})
            if name != 'tecnico':
                match |= Q(**{'orcamento__' + name: data[name]})
                match |= Q(**{'contrato__equipamentos__' + ('unidade' if name == 'unidade' else 'pk'): data[name].pk})
                if name == 'unidade':
                    match |= Q(contrato__unidades=data[name])
            else:
                match |= Q(contrato__agenda__tecnico=data[name])
            qs = qs.filter(match).distinct()
    qs = situation(qs, data.get('status'))
    return ['Lançamento', 'Cliente', 'Categoria', 'Emissão', 'Vencimento', 'Valor', 'Situação', 'Liquidação'], [[x.descricao, str(x.cliente or ''), str(x.categoria or ''), x.data_emissao, x.vencimento, x.valor, x.situacao, x.data_liquidacao or ''] for x in qs]


def csv_bytes(headers, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(headers)
    for row in rows:
        cells = []
        for cell in row:
            value = str(cell)
            if not isinstance(cell, (int, Decimal)) and value.startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                value = "'" + value
            cells.append(value)
        writer.writerow(cells)
    return ('\ufeff' + stream.getvalue()).encode('utf-8')

def xlsx_bytes(headers, rows, numeric_columns=()):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    if len(rows) > 10000:
        raise ValidationError('Excel limitado a 10.000 linhas; reduza os filtros.')
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'VERTYX'
    sheet.append(headers)
    for row in rows:
        sheet.append([cell if index in numeric_columns and isinstance(cell,(int,float,Decimal)) else str(cell) if cell is not None else '' for index,cell in enumerate(row)])
        for index,cell in enumerate(sheet[sheet.max_row]):
            # Strings fornecidas pelo usuário nunca são fórmulas Excel.
            if index not in numeric_columns or not isinstance(cell.value,(int,float,Decimal)):
                cell.data_type = 's'
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='006F74')
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for index in range(1,len(headers)+1):
        sheet.column_dimensions[get_column_letter(index)].width = 24
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def pdf_bytes(title, organization, headers, rows, details=(), max_rows=1000):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
    if len(rows) > max_rows:
        raise ValidationError(f'PDF limitado a {max_rows} linhas. Reduza o período/filtros ou exporte Excel/CSV.')
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    styles['BodyText'].fontSize = 8
    styles['BodyText'].leading = 10
    def text(value):
        return Paragraph(escape(str(value)).replace('\n', '<br/>'), styles['BodyText'])
    table = LongTable([[text(x) for x in headers]] + [[text(cell) for cell in row] for row in rows], repeatRows=1, colWidths=[(landscape(A4)[0] - 60) / len(headers)] * len(headers))
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e5edf4')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#d2dbe4')), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30, title=title)
    def footer(canvas, document):
        canvas.setFont('Helvetica', 8)
        canvas.drawString(30, 15, f'Página {document.page}')
    story = [Paragraph(escape(organization.display_name), styles['Title']), Paragraph(escape(title), styles['Heading2'])]
    story.extend(text(f'{name}: {value}') for name, value in details)
    story.extend([Spacer(1, 10), table])
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def financial_dashboard(inicio, fim):
    from operacao.reporting import financial_dashboard as expanded
    return expanded(inicio, fim)

def legacy_financial_dashboard(inicio, fim):
    qs = m.Lancamento.objects.exclude(status='CANCELADO')
    pending = qs.filter(status__in=['PENDENTE', 'VENCIDO'])
    settled = qs.filter(status='LIQUIDADO', data_liquidacao__gte=inicio, data_liquidacao__lte=fim)
    def total(query):
        return query.aggregate(total=Sum('valor'))['total'] or m.ZERO
    result = {'a_receber': total(pending.filter(tipo='RECEBER')), 'a_pagar': total(pending.filter(tipo='PAGAR')), 'recebido': total(settled.filter(tipo='RECEBER')), 'pago': total(settled.filter(tipo='PAGAR')), 'vencido_receber': total(pending.filter(tipo='RECEBER', vencimento__lt=timezone.localdate())), 'vencido_pagar': total(pending.filter(tipo='PAGAR', vencimento__lt=timezone.localdate()))}
    result['resultado'] = result['recebido'] - result['pago']
    months = {}
    for entry in qs.filter(Q(vencimento__gte=inicio, vencimento__lte=fim) | Q(data_liquidacao__gte=inicio, data_liquidacao__lte=fim)):
        for date, prefix in [(entry.vencimento, 'previsto'), (entry.data_liquidacao if entry.status == 'LIQUIDADO' else None, 'realizado')]:
            if date and inicio <= date <= fim:
                key = date.strftime('%Y-%m')
                row = months.setdefault(key, {'mes': key, 'previsto_RECEBER': m.ZERO, 'previsto_PAGAR': m.ZERO, 'realizado_RECEBER': m.ZERO, 'realizado_PAGAR': m.ZERO})
                row[prefix + '_' + entry.tipo] += entry.valor
    result['fluxo'] = [months[key] for key in sorted(months)]
    return result
