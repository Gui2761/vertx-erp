"""Public, nontechnical column catalog. No tenant IDs or access fields accepted."""
import re
import unicodedata

def normalize(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower())

def field(key,label,required=False,aliases=(),kind='text',help=''):
    return dict(key=key,label=label,required=required,aliases=list(aliases),kind=kind,help=help)

CATALOG = {
 'produtos':dict(title='Produtos',icon='box-seam',description='Cadastros, preços e códigos. O saldo é importado separadamente em Estoque.',fields=[
  field('sku','Código',True,('sku','cod_prod','codigo interno','codigo','cod','cod_item','part_number','part number','referencia','item','codigo peca','cod peca')),
  field('descricao','Nome do produto',True,('descricao','produto','nome','descricao da peca','nome do produto','peca','material','item descricao')),
  field('gtin','EAN / GTIN',aliases=('ean','codigo ean','gtin','cod_barras','codigo barras','codigo de barras')),
  field('codigo_externo','Código externo',aliases=('codigo alternativo','cod_ext','codigo externo','cod fabricante','ref fabricante','codigo fornecedor')),
  field('unidade_medida','Unidade',aliases=('unidade de medida','un','unidade','unid','medida','um')),
  field('preco_venda','Preço de venda',kind='money',aliases=('preco','valor venda','preco venda','preco unitario','valor','venda','vl venda')),
  field('custo_aquisicao','Custo de aquisição',kind='money',aliases=('custo','preco custo','custo unitario','valor custo','custo medio','vl custo')),
  field('estoque_minimo','Estoque mínimo',kind='quantity',aliases=('estoque minimo','est minimo','est_min','minimo','ponto pedido','qtd minima')),
  field('estoque_maximo','Estoque ideal',kind='quantity',aliases=('estoque maximo','estoque ideal','est maximo','est_max','maximo','qtd maxima')),
  field('fabricante','Fabricante',aliases=('fabricante','fabr','marca fabricante')),
  field('marca','Marca',aliases=('marca','marca modelo')),
  field('ncm','NCM',aliases=('ncm','codigo ncm','classificacao fiscal'),help='Opcional no cadastro. Ausência não libera emissão fiscal.'),
  field('controla_validade','Controla validade',kind='bool',aliases=('controla validade','controla_validade','tem validade')),
  field('exige_lote','Exige lote',kind='bool',aliases=('exige lote','exige_lote','tem lote')),
  field('fracionavel','Fracionável',kind='bool',aliases=('fracionavel','fracionado'))]),
 'clientes':dict(title='Clientes',icon='people',description='Nome, documento e contatos dos seus clientes.',fields=[
  field('nome_razao_social','Nome / Razão social',True,('nome','razao social','razao_social','cliente','nome cliente','nome razao social','razao social / nome')),
  field('cpf_cnpj','CPF / CNPJ',True,('cpf','cnpj','documento','cpf_cnpj','cpf / cnpj','cnpj / cpf','doc','doc identificacao')),
  field('nome_fantasia','Nome fantasia',aliases=('nome fantasia','fantasia','nome_fantasia')),
  field('email','E-mail',aliases=('email','e-mail','contato email')),
  field('telefone','Telefone',aliases=('telefone','fone','tel','telefone fixo','comercial')),
  field('whatsapp','WhatsApp',aliases=('whatsapp','zap','celular','whats','cel')),
  field('endereco','Endereço',aliases=('endereco','logradouro','rua','avenida','end')),
  field('numero','Número',aliases=('numero','num','n')),
  field('complemento','Complemento',aliases=('complemento','comp','compl')),
  field('bairro','Bairro',aliases=('bairro','distrito')),
  field('cidade','Cidade',aliases=('cidade','municipio')),
  field('uf','UF',aliases=('uf','estado','sigla uf')),
  field('cep','CEP',aliases=('cep','codigo postal')),
  field('observacoes','Observações',aliases=('observacoes','obs','observacao','notas'))]),
 'fornecedores':dict(title='Fornecedores',icon='truck',description='Cadastros e contatos. Compras e contas existentes permanecem preservadas.',fields=[
  field('nome','Nome / Razão social',True,('nome fornecedor','razao social','fornecedor','razao_social')),
  field('documento','CPF / CNPJ',aliases=('cpf','cnpj','documento','cpf_cnpj','doc')),
  field('nome_fantasia','Nome fantasia',aliases=('nome fantasia','fantasia')),
  field('email','E-mail',aliases=('email','e-mail')),
  field('telefone','Telefone',aliases=('telefone','fone','tel')),
  field('contato','Contato',aliases=('contato','pessoa contato')),
  field('endereco','Endereço',aliases=('endereco','logradouro')),
  field('observacoes','Observações',aliases=('observacoes','obs'))]),
 'estoque':dict(title='Estoque',icon='boxes',description='Entradas adicionais auditadas. Nunca substitui o saldo atual. Cadastre antes produtos, depósitos e fornecedores.',fields=[
  field('identificador','Identificador da entrada',True,('id entrada','codigo externo','id_entrada','id','identificador','lancamento','num entrada'),help='Código único desta entrada no sistema de origem. Impede repetir a mesma entrada em outros arquivos.'),
  field('sku','Código do produto',True,('sku','codigo','cod_prod','cod_item','part_number','item','codigo produto','codigo peca')),
  field('deposito','Depósito',True,('local','armazem','deposito','almoxarifado','deposito destino')),
  field('quantidade','Quantidade de entrada',True,('quantidade','saldo','qtd','qtde','quantidade entrada','saldo inicial'),kind='quantity'),
  field('custo_unitario','Custo unitário',True,('custo','custo unitario','valor unitario','preco custo','vl unitario'),kind='money'),
  field('lote','Lote',True,('numero lote','lote','num lote','lote fabrica')),
  field('validade','Validade',kind='date',aliases=('validade','data validade','vencimento','data vencimento','dt validade')),
  field('fabricacao','Fabricação',kind='date',aliases=('fabricacao','data fabricacao','dt fabricacao')),
  field('fornecedor','CPF / CNPJ do fornecedor',aliases=('documento fornecedor','fornecedor','cnpj fornecedor')),
  field('localizacao','Localização',aliases=('localizacao','prateleira','posicao','box','gaveta')),
  field('documento_entrada','Documento de entrada',aliases=('documento de entrada','nota fiscal','nf','doc entrada','numero nf'))]),
 'equipamentos':dict(title='Equipamentos',icon='heart-pulse',description='Importe depois de Clientes. A categoria deve existir nesta organização.',fields=[
  field('codigo_interno','Código / Patrimônio',True,('codigo','patrimonio','codigo externo','patrimonio hospitalar','tag')),
  field('nome','Nome do equipamento',True,('descricao','nome','equipamento','aparelho')),
  field('cliente','CPF / CNPJ do cliente',True,('cliente documento','documento cliente','cnpj cliente')),
  field('categoria','Categoria',True,aliases=('categoria','tipo equipamento')),
  field('numero_serie','Número de série',aliases=('serie','numero serie','num serie','sn')),
  field('fabricante','Fabricante',aliases=('fabricante','marca')),
  field('marca','Marca',aliases=('marca',)),
  field('modelo','Modelo',aliases=('modelo',)),
  field('localizacao','Localização',aliases=('localizacao','setor','sala','leito')),
  field('observacoes','Observações',aliases=('observacoes','obs'))]),
 'funcionarios':dict(title='Funcionários',icon='person-badge',description='Fichas ligadas a contas já existentes. Não cria contas, perfis, jornadas ou permissões.',fields=[
  field('usuario','Usuário já cadastrado',True,('usuario','login')),
  field('matricula','Matrícula',True,('codigo','codigo externo','matricula')),
  field('nome','Nome',True,('nome funcionario','colaborador')),
  field('telefone','Telefone',aliases=('telefone','celular')),
  field('email','E-mail',aliases=('email','e-mail')),
  field('cargo','Cargo',aliases=('cargo','funcao')),
  field('vinculo','Vínculo',aliases=('vinculo','contrato'))]),
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
