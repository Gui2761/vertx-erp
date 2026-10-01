"""Verifica arquivos efetivamente baixados pelo navegador no ensaio local."""
import json
from pathlib import Path
from pypdf import PdfReader
from openpyxl import load_workbook
root=Path(__file__).resolve().parents[1]
out=root/'tmp/validation'
pdf=PdfReader(out/'stock-weekly-report.pdf')
text='\n'.join(page.extract_text() for page in pdf.pages)
headers=['Produto','Código/SKU','Categoria','Estoque físico','Reservado','Disponível','Mínimo','Ideal/máximo','Consumo médio/dia','Quantidade vencendo','Em compra','Sugerido','Último fornecedor','Último custo','Valor estimado']
assert all(header in text for header in headers)
assert 'Luva com validade' in text
workbook=load_workbook(out/'stock-weekly-report.xlsx',read_only=True,data_only=False)
sheet=workbook.active
rows=list(sheet.values)
assert list(rows[0])==headers
assert any('Luva com validade' in str(row[0]) for row in rows[1:])
assert all(cell.data_type!='f' for row in sheet for cell in row)
assert all(sheet.cell(row=row,column=column).data_type=='n' for row in range(2,sheet.max_row+1) for column in [4,5,6,7,8,9,10,11,12,14,15])
result={'pdf_pages':len(pdf.pages),'pdf_15_fields':'PASS','xlsx_15_columns':'PASS','xlsx_rows':len(rows)-1,'xlsx_numeric_columns':'PASS','xlsx_untrusted_formulas_absent':'PASS'}
(out/'stock-artifacts.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
