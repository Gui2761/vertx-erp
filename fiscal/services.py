import hashlib
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from gestao.permissions import require
from gestao.services import audit, write
from operacao.models import Configuracao, DocumentoFiscal, Documento
from .providers import resolve
from .providers.base import FiscalResult

def payload(document):
    org, customer = document.organization, document.cliente
    products = []
    if document.venda_id:
        products = [{'sku': row.peca.sku, 'descricao': row.peca.descricao, 'ncm': row.peca.ncm, 'cfop': row.peca.cfop, 'cst_csosn': row.peca.cst_csosn, 'quantidade': str(row.quantidade), 'valor_unitario': str(row.valor_unitario), 'desconto': str(row.desconto)} for row in document.venda.itens.select_related('peca')]
    return {'tipo': document.tipo, 'ambiente': document.ambiente, 'emitente': {'cnpj': org.cnpj, 'razao_social': org.razao_social}, 'destinatario': {'documento': customer.cpf_cnpj, 'nome': customer.nome_razao_social, 'inscricao_estadual': customer.inscricao_estadual, 'inscricao_municipal': customer.inscricao_municipal}, 'serie': document.serie, 'municipio': document.municipio, 'codigo_servico': document.codigo_servico, 'descricao': document.descricao, 'valor': str(document.valor), 'impostos': document.impostos, 'retencoes': document.retencoes, 'produtos': products}

@transaction.atomic
def executar(user, pk, action, reason=''):
    require(user, 'financeiro_escrever')
    doc = DocumentoFiscal.objects.select_for_update().get(pk=pk)
    config = Configuracao.objects.first()
    if not config or config.ambiente_fiscal != doc.ambiente:
        raise ValidationError('Configure o ambiente fiscal da organização e do documento antes de usar o provedor.')
    provider = resolve(config.provedor_fiscal, doc.organization, doc.ambiente)
    old = {'status': doc.status, 'numero': doc.numero, 'protocolo': doc.protocolo}
    if action == 'emitir':
        if doc.status != 'RASCUNHO':
            raise ValidationError('Use consulta para um documento já enviado.')
        if not doc.organization.cnpj or doc.tipo == 'NFSE' and not (doc.municipio and doc.codigo_servico) or doc.tipo != 'NFSE' and not doc.venda_id:
            raise ValidationError('Cadastro fiscal incompleto: emitente, município/serviço ou venda com produtos.')
        result = provider.emitir(payload(doc), f'{doc.organization.public_id}:{doc.pk}:{doc.ambiente}')
    elif action == 'consultar' and doc.protocolo:
        result = provider.consultar(doc.protocolo)
    elif action == 'cancelar' and doc.status == 'AUTORIZADA' and reason.strip():
        result = provider.cancelar(doc.protocolo, reason.strip())
    else:
        raise ValidationError('Operação fiscal inválida para o estado atual.')
    if not isinstance(result, FiscalResult) or result.status not in ['ENVIADA', 'AUTORIZADA', 'REJEITADA', 'CANCELADA'] or result.status == 'AUTORIZADA' and not (result.numero and result.protocolo):
        raise ValidationError('Resposta fiscal inválida; nenhum estado foi alterado.')
    doc.status, doc.numero, doc.protocolo = result.status, result.numero, result.protocolo
    write(doc)
    for extension, data in [('xml', result.xml), ('pdf', result.pdf)]:
        if data:
            if len(data) > 25 * 1024 * 1024 or extension == 'pdf' and not data.startswith(b'%PDF-'):
                raise ValidationError('Arquivo fiscal inválido ou acima de 25 MB.')
            if extension == 'xml':
                from xml.etree.ElementTree import fromstring, ParseError
                try:
                    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                        raise ValueError()
                    fromstring(data)
                except (ValueError, ParseError):
                    raise ValidationError('XML fiscal inválido.')
            Documento.objects.create(titulo=f'{doc.get_tipo_display()} {doc.numero}', tipo='FISCAL_' + extension.upper(), arquivo=ContentFile(data, name=f'nota.{extension}'), cliente=doc.cliente, fiscal=doc, sha256=hashlib.sha256(data).hexdigest(), enviado_por=user, disponivel_portal=True)
    audit(user, 'FISCAL_' + doc.status, doc, {'anterior': old, 'posterior': {'status': doc.status, 'numero': doc.numero, 'protocolo': doc.protocolo}})
    return doc
