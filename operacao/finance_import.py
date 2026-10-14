"""Importadores mínimos e sem persistência do arquivo bruto para extratos OFX/CSV."""
import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation


def _date(value):
    value = str(value).strip()
    if re.fullmatch(r'\d{8}', value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    for pattern in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            from datetime import datetime
            return datetime.strptime(value[:10], pattern).date()
        except ValueError:
            pass
    raise ValueError('data inválida')


def _amount(value):
    raw = str(value).strip().replace('R$', '').replace(' ', '')
    if ',' in raw and '.' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif ',' in raw:
        raw = raw.replace(',', '.')
    try:
        amount = Decimal(raw).quantize(Decimal('.01'))
    except (InvalidOperation, ValueError):
        raise ValueError('valor inválido') from None
    if not amount:
        raise ValueError('valor não pode ser zero')
    return amount


def parse_csv(content):
    text = content.decode('utf-8-sig')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=';,\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError('CSV sem cabeçalho.')
    aliases = {
        'id': {'id', 'identificador', 'fitid', 'referencia', 'referência'},
        'data': {'data', 'date', 'dtposted'},
        'valor': {'valor', 'value', 'amount', 'trnamt'},
        'descricao': {'descricao', 'descrição', 'description', 'memo', 'nome'},
    }
    mapping = {}
    for required, choices in aliases.items():
        mapping[required] = next((header for header in reader.fieldnames if header.strip().lower() in choices), None)
        if not mapping[required]:
            raise ValueError(f'CSV precisa conter uma coluna para {required}.')
    rows = []
    for line, row in enumerate(reader, start=2):
        try:
            ident = str(row[mapping['id']] or '').strip()[:150]
            description = str(row[mapping['descricao']] or '').strip()[:255]
            if not ident or not description:
                raise ValueError('identificador e descrição são obrigatórios')
            rows.append({'identificador': ident, 'data': _date(row[mapping['data']]), 'valor': _amount(row[mapping['valor']]), 'descricao': description})
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f'Linha {line}: {exc}') from None
    return rows


def parse_ofx(content):
    text = content.decode('utf-8-sig', errors='strict')
    if '<OFX' not in text.upper():
        raise ValueError('Arquivo OFX inválido.')
    rows = []
    for line, block in enumerate(re.findall(r'<STMTTRN>(.*?)</STMTTRN>', text, re.I | re.S), start=1):
        def tag(name):
            found = re.search(rf'<{name}>([^<\r\n]+)', block, re.I)
            return found.group(1).strip() if found else ''
        ident, posted = tag('FITID'), tag('DTPOSTED')
        description = tag('NAME') or tag('MEMO')
        try:
            if not ident or not description:
                raise ValueError('FITID e descrição são obrigatórios')
            rows.append({'identificador': ident[:150], 'data': _date(posted), 'valor': _amount(tag('TRNAMT')), 'descricao': description[:255]})
        except ValueError as exc:
            raise ValueError(f'Transação OFX {line}: {exc}') from None
    if not rows:
        raise ValueError('Nenhuma transação encontrada no OFX.')
    return rows


def parse_statement(upload):
    content = upload.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise ValueError('O arquivo excede 10 MB.')
    return parse_ofx(content) if upload.name.lower().endswith('.ofx') else parse_csv(content)
