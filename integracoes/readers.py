"""Bounded XLSX/CSV ingestion. Does not execute formulas or open linked files."""
import csv
import io
import re
import zipfile
from datetime import date,datetime
from pathlib import PurePath
from django.core.exceptions import ValidationError
from openpyxl import load_workbook
from .catalog import normalize

MAX_BYTES=5*1024*1024
MAX_ROWS=5000
MAX_COLS=40
MAX_CELL=1000

def scalar(value):
    if isinstance(value,(date,datetime)):return value.date().isoformat() if isinstance(value,datetime) else value.isoformat()
    if value is None:return ''
    text=str(value).strip()
    if len(text)>MAX_CELL:raise ValidationError('Há uma célula muito longa. Use até 1.000 caracteres por campo.')
    return text

def read(name,data):
    suffix=PurePath(name).suffix.lower()
    if suffix not in {'.xlsx','.csv'}:raise ValidationError('Escolha um arquivo Excel (.xlsx) ou CSV (.csv).')
    if not data or len(data)>MAX_BYTES:raise ValidationError('O arquivo deve ter conteúdo e no máximo 5 MB.')
    if suffix=='.xlsx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos=z.infolist()
                if len(infos)>200 or sum(x.file_size for x in infos)>20*1024*1024:raise ValidationError('O Excel é grande demais depois de aberto. Divida o arquivo.')
                for info in infos:
                    lower=info.filename.lower()
                    if any(x in lower for x in ('vbaproject','externallinks/','embeddings/')):raise ValidationError('Remova macros, objetos e vínculos externos do Excel.')
                    if lower.endswith('.xml'):
                        xml=z.read(info).lower()
                        if b'<!doctype' in xml or b'<!entity' in xml:raise ValidationError('O arquivo contém uma estrutura não permitida.')
            wb=load_workbook(io.BytesIO(data),read_only=True,data_only=False,keep_links=False)
            try:
                ws=wb['Dados'] if 'Dados' in wb.sheetnames else wb.worksheets[0]
                if (ws.max_row or 0)>MAX_ROWS+1 or (ws.max_column or 0)>MAX_COLS:raise ValidationError('Use até 5.000 registros e 40 colunas por arquivo.')
                values=[]
                for row in ws.iter_rows():
                    if len(values)>MAX_ROWS or len(row)>MAX_COLS:raise ValidationError('Use até 5.000 registros e 40 colunas por arquivo.')
                    if any(cell.data_type=='f' for cell in row):raise ValidationError('Há fórmulas no arquivo. Copie e cole somente os valores antes de enviar.')
                    values.append([scalar(cell.value) for cell in row])
            finally:wb.close()
        except ValidationError:raise
        except Exception:raise ValidationError('Não foi possível abrir esse Excel. Salve novamente como .xlsx.') from None
    else:
        text=None
        for encoding in ('utf-8-sig','cp1252'):
            try:text=data.decode(encoding);break
            except UnicodeError:continue
        if text is None or '\x00' in text:raise ValidationError('Não foi possível ler esse CSV. Use UTF-8 ou Windows-1252.')
        try:
            delimiter=csv.Sniffer().sniff(text[:8192],delimiters=';,\t').delimiter
        except csv.Error:delimiter=';'
        try:
            values=[]
            for row in csv.reader(io.StringIO(text),delimiter=delimiter,strict=True):
                if len(values)>MAX_ROWS or len(row)>MAX_COLS:raise ValidationError('Use até 5.000 registros e 40 colunas por arquivo.')
                values.append([scalar(v) for v in row])
        except csv.Error:raise ValidationError('Revise as aspas e os separadores do CSV.') from None
    if not values:raise ValidationError('O arquivo está vazio.')
    # Empty formatted Excel cells are not data columns; never truncate populated cells.
    width=max((i+1 for row in values for i,v in enumerate(row) if v),default=0)
    if not width:raise ValidationError('O arquivo está vazio.')
    headers=(values[0]+['']*width)[:width]
    if any(not normalize(h) for h in headers) or len({normalize(h) for h in headers})!=width:raise ValidationError('Preencha o nome de cada coluna, sem repetir cabeçalhos.')
    rows=[]
    for number,row in enumerate(values[1:],2):
        if len(row)>width and any(row[width:]):raise ValidationError(f'Linha {number}: há valores sem nome de coluna.')
        row=(row+['']*width)[:width]
        if any(row):rows.append((number,row))
    if not rows:raise ValidationError('Inclua ao menos um registro abaixo dos nomes das colunas.')
    if len(rows)>MAX_ROWS:raise ValidationError('Use até 5.000 registros por arquivo.')
    return headers,rows
