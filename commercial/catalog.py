"""Public capabilities describe implemented modules, never tenant entitlements."""
FEATURES = {
    'erp': ('ERP completo', 'Uma visão integrada do seu negócio.', 'grid'),
    'assistencia': ('Assistência técnica', 'Da triagem à entrega, com histórico do atendimento.', 'tool'),
    'os': ('Ordens de Serviço', 'Diagnósticos, fotos, peças, assinaturas e documentos.', 'document'),
    'chamados': ('Chamados', 'Organize solicitações e acompanhe sua evolução.', 'chat'),
    'preventivas': ('Preventivas', 'Planeje os próximos cuidados com cada equipamento.', 'calendar'),
    'equipamentos': ('Equipamentos', 'Cadastros e histórico técnico no mesmo lugar.', 'equipment'),
    'estoque': ('Estoque', 'Peças, lotes, validades e movimentações rastreáveis.', 'box'),
    'compras': ('Compras', 'Solicitação, cotação, pedido e recebimento.', 'cart'),
    'vendas': ('Vendas', 'Produtos e atendimento comercial conectados.', 'trend'),
    'pdv': ('PDV', 'Uma operação de venda feita para o balcão.', 'terminal'),
    'financeiro': ('Financeiro', 'Contas, recebimentos e fluxo de caixa para a gestão.', 'wallet'),
    'contratos': ('Contratos', 'Acompanhe serviços e compromissos contratados.', 'contract'),
    'relatorios': ('Relatórios', 'Transforme os registros da operação em decisões.', 'chart'),
    'portal': ('Portal do cliente', 'Consultas e documentos com acesso autorizado.', 'users'),
    'pwa': ('PWA do técnico', 'Atendimentos, câmera e assinatura na experiência móvel.', 'phone'),
}
# Explicitly internal: fiscal placeholders are not marketed as issuance.
FUTURE_FEATURES = {'fiscal', 'gateway', 'assinatura_automatica', 'provisionamento_automatico'}
RESOURCE_STATES = {'INCLUIDO', 'CONSULTA', 'FUTURO'}
DEFAULT_RESOURCES = {key: 'CONSULTA' for key in FEATURES} | {key: 'FUTURO' for key in FUTURE_FEATURES}
DEFAULT_PLANS = [
    {'slug':'basico','nome':'Básico','preco':'149.00','descricao':'Para organizar o dia a dia e dar o próximo passo.','ordem':10},
    {'slug':'profissional','nome':'Profissional','preco':'249.00','descricao':'Para conectar a equipe e acompanhar toda a operação.','destaque':True,'ordem':20},
    {'slug':'empresarial','nome':'Empresarial','preco':'399.00','descricao':'Para empresas com uma operação mais ampla.','ordem':30},
    {'slug':'personalizado','nome':'Personalizado','preco':None,'descricao':'Uma proposta alinhada às necessidades da sua empresa.','ordem':40},
]


def money(value):
    text = f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return text[:-3] if text.endswith(',00') else text
