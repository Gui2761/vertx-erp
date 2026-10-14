"""Public, nontechnical column catalog. No tenant IDs or access fields accepted."""
import re
import unicodedata

def normalize(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower())

def field(key,label,required=False,aliases=(),kind='text',help=''):
    return dict(key=key,label=label,required=required,aliases=list(aliases),kind=kind,help=help)

CATALOG = {
 'produtos':dict(title='Produtos',icon='box-seam',description='Cadastros, preços e códigos. O saldo é importado separadamente em Estoque.',fields=[
  field('sku','Código',True,('sku','cod_prod','codigo interno')),field('descricao','Nome do produto',True,('descricao','produto','nome')),
  field('gtin','EAN / GTIN',aliases=('ean','codigo ean')),field('codigo_externo','Código externo',aliases=('codigo alternativo',)),
  field('unidade_medida','Unidade',aliases=('unidade de medida',)),field('preco_venda','Preço de venda',kind='money',aliases=('preco','valor venda')),
  field('custo_aquisicao','Custo de aquisição',kind='money',aliases=('custo','preco custo')),
  field('estoque_minimo','Estoque mínimo',kind='quantity'),field('estoque_maximo','Estoque ideal',kind='quantity',aliases=('estoque maximo',)),
  field('fabricante','Fabricante'),field('marca','Marca'),field('ncm','NCM',help='Opcional no cadastro. Ausência não libera emissão fiscal.'),
  field('controla_validade','Controla validade',kind='bool'),field('exige_lote','Exige lote',kind='bool'),field('fracionavel','Fracionável',kind='bool')]),
 'clientes':dict(title='Clientes',icon='people',description='Nome, documento e contatos dos seus clientes.',fields=[
  field('nome_razao_social','Nome / Razão social',True,('nome','razao social','cliente')),field('cpf_cnpj','CPF / CNPJ',True,('cpf','cnpj','documento')),
  field('nome_fantasia','Nome fantasia'),field('email','E-mail',aliases=('email',)),field('telefone','Telefone'),field('whatsapp','WhatsApp'),
  field('endereco','Endereço'),field('numero','Número'),field('bairro','Bairro'),field('cidade','Cidade'),field('uf','UF'),field('cep','CEP'),field('observacoes','Observações')]),
 'fornecedores':dict(title='Fornecedores',icon='truck',description='Cadastros e contatos. Compras e contas existentes permanecem preservadas.',fields=[
  field('nome','Nome / Razão social',True,('nome fornecedor','razao social','fornecedor')),field('documento','CPF / CNPJ',aliases=('cpf','cnpj','documento')),
  field('nome_fantasia','Nome fantasia'),field('email','E-mail',aliases=('email',)),field('telefone','Telefone'),field('contato','Contato'),field('endereco','Endereço'),field('observacoes','Observações')]),
 'estoque':dict(title='Estoque',icon='boxes',description='Entradas adicionais auditadas. Nunca substitui o saldo atual. Cadastre antes produtos, depósitos e fornecedores.',fields=[
  field('identificador','Identificador da entrada',True,('id entrada','codigo externo','id_entrada'),help='Código único desta entrada no sistema de origem. Impede repetir a mesma entrada em outros arquivos.'),
  field('sku','Código do produto',True,('sku','codigo','cod_prod')),field('deposito','Depósito',True,('local','armazem')),
  field('quantidade','Quantidade de entrada',True,('quantidade','saldo'),kind='quantity'),field('custo_unitario','Custo unitário',True,('custo',),kind='money'),
  field('lote','Lote',True,('numero lote',)),field('validade','Validade',kind='date'),field('fabricacao','Fabricação',kind='date'),
  field('fornecedor','CPF / CNPJ do fornecedor',aliases=('documento fornecedor',)),field('localizacao','Localização'),field('documento_entrada','Documento de entrada')]),
 'equipamentos':dict(title='Equipamentos',icon='heart-pulse',description='Importe depois de Clientes. A categoria deve existir nesta organização.',fields=[
  field('codigo_interno','Código / Patrimônio',True,('codigo','patrimonio','codigo externo')),field('nome','Nome do equipamento',True,('descricao','nome','equipamento')),
  field('cliente','CPF / CNPJ do cliente',True,('cliente documento',)),field('categoria','Categoria',True),
  field('numero_serie','Número de série',aliases=('serie',)),field('fabricante','Fabricante'),field('marca','Marca'),field('modelo','Modelo'),field('localizacao','Localização'),field('observacoes','Observações')]),
 'funcionarios':dict(title='Funcionários',icon='person-badge',description='Fichas ligadas a contas já existentes. Não cria contas, perfis, jornadas ou permissões.',fields=[
  field('usuario','Usuário já cadastrado',True,('usuario','login')),field('matricula','Matrícula',True,('codigo','codigo externo')),field('nome','Nome',True,('nome funcionario',)),
  field('telefone','Telefone'),field('email','E-mail',aliases=('email',)),field('cargo','Cargo'),field('vinculo','Vínculo')]),
}
PLANNED=[dict(title='Contratos',description='Próxima etapa: vínculos com clientes, unidades, equipamentos e cobrança.'),dict(title='Financeiro',description='Próxima etapa: origens, saldos, parcelas e conciliação sem duplicar pagamentos.')]

def suggest(kind,headers):
    result={};used=set()
    for index,header in enumerate(headers):
        key=next((f['key'] for f in CATALOG[kind]['fields'] if normalize(header) in {normalize(f['label']),normalize(f['key']),*(normalize(a) for a in f['aliases'])}), '')
        if key in used:key=''
        if key:used.add(key)
        result[str(index)]=key
    return result
