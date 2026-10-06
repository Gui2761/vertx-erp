from django.urls import path
from . import views
from . import planning, portal, pwa, configuration
from . import stock_views
from . import operational_panel
from . import pdv
from . import workforce_views
from . import overtime_views
from . import inventory_views
from . import executive
from . import mobile
from . import contract_workday_views
app_name = 'operacao'
urlpatterns = [
    path('contratos/jornadas/', contract_workday_views.measurement, name='contract_measurement'),
    path('contratos/<int:pk>/jornada/', contract_workday_views.configuration, name='contract_configuration'),
    path('tecnico/atividade/<int:order_id>/', contract_workday_views.activity, name='contract_activity'),
    path('tecnico/qr/',mobile.qr_reader,name='mobile_qr'),
    path('gestao/executiva/',executive.dashboard,name='executive'),
    path('inventarios/',inventory_views.inventories,name='inventory_list'),
    path('inventarios/<uuid:public_id>/',inventory_views.inventories,name='inventory_detail'),
    path('transferencias/',inventory_views.transfers,name='transfer_list'),
    path('ponto/',workforce_views.home,name='ponto_home'),
    path('ponto/horas-extras/',overtime_views.own,name='ponto_overtime'),
    path('rh/horas-extras/',overtime_views.management,name='rh_overtime'),
    path('ponto/espelho/<uuid:public_id>/',workforce_views.mirror,name='ponto_mirror'),
    path('ponto/ajustes/',workforce_views.adjustments,name='ponto_adjustments'),
    path('rh/<str:resource>/',workforce_views.management,name='rh_list'),
    path('rh/<str:resource>/novo/',workforce_views.management,{'new':True},name='rh_new'),
    path('rh/<str:resource>/<int:pk>/',workforce_views.management,name='rh_edit'),
    path('pdv/',pdv.home,name='pdv_home'),
    path('pdv/configuracao/',pdv.config,name='pdv_config'),
    path('pdv/caixas/<uuid:public_id>/',pdv.cash,name='pdv_cash'),
    path('pdv/vendas/<uuid:public_id>/',pdv.sale,name='pdv_sale'),
    path('pdv/vendas/<uuid:public_id>/produtos/',pdv.products,name='pdv_products'),
    path('pdv/vendas/<uuid:public_id>/comprovante/',pdv.sale,{'receipt':True},name='pdv_receipt'),
    path('pesquisa/', views.pesquisa, name='pesquisa'),
    path('estoque/necessidades/', views.necessidades, name='necessidades'),
    path('estoque/necessidades/<int:pk>/comprar/', views.necessidade_compra, name='necessidade_compra'),
    path('estoque/necessidades/<int:pk>/resolver/', views.necessidade_resolver, name='necessidade_resolver'),
    path('ordens/<int:pk>/necessidade/', views.os_necessidade, name='os_necessidade'),
    path('estoque/lotes/',stock_views.lots,name='stock_lots'),
    path('estoque/lotes/entrada/',stock_views.lot_entry,name='stock_entry'),
    path('estoque/reservas/',stock_views.reservations,name='stock_reservations'),
    path('estoque/reservas/<int:pk>/liberar/',stock_views.release,name='stock_release'),
    path('estoque/ocorrencias/',stock_views.occurrences,name='stock_occurrences'),
    path('estoque/relatorios/',stock_views.reports,name='stock_reports'),
    path('estoque/relatorios/<int:pk>/',stock_views.report,name='stock_report'),
    path('configuracoes/estoque-compras/',stock_views.config,name='stock_config'),
    path('compras/<int:pk>/itens/<int:item_id>/lote/',stock_views.receipt,name='stock_receipt'),
    path('compras/<int:pk>/receber/', views.compra_receber, name='compra_receber'),
    path('planejamento/', planning.calendario, name='calendario'),
    path('planejamento/nova-os/', planning.quick, name='planning_quick'),
    path('planejamento/ordens/<int:pk>/', planning.detail, name='planning_detail'),
    path('planejamento/ordens/<int:pk>/agendar/', planning.schedule, name='planning_schedule'),
    path('painel-operacional/', operational_panel.panel, name='operational_panel'),
    path('painel-operacional/dados/', operational_panel.data, name='panel_data'),
    path('configuracoes/painel-operacional/', operational_panel.config, name='panel_config'),
    path('tecnico/', planning.tecnico, name='tecnico'),
    path('manifest.webmanifest', pwa.manifest, name='manifest'),
    path('sw.js', pwa.worker, name='worker'),
    path('configuracoes/', configuration.configuracao, name='configuracao'),
    path('notificacoes/', configuration.notificacoes, name='notificacoes'),
    path('notificacoes/<int:pk>/lida/', configuration.notificacao_lida, name='notificacao_lida'),
    path('portal/', portal.home, name='portal'),
    path('portal/chamados/novo/', portal.chamado, name='portal_chamado'),
    path('portal/chamados/<int:pk>/', portal.chamado_detalhe, name='portal_chamado_detalhe'),
    path('portal/equipamentos/<uuid:codigo_publico>/', portal.equipamento, name='portal_equipamento'),
    path('portal/ordens/<int:pk>/', portal.ordem, name='portal_os'),
    path('portal/ordens/<int:pk>/pdf/<int:item_id>/', portal.arquivo_os, {'kind': 'pdf'}, name='portal_os_pdf'),
    path('portal/ordens/<int:pk>/foto/<int:item_id>/', portal.arquivo_os, {'kind': 'foto'}, name='portal_os_foto'),
    path('portal/orcamentos/<int:pk>/pdf/', portal.orcamento_pdf, name='portal_orcamento_pdf'),
    path('portal/orcamentos/<int:pk>/<str:action>/', portal.aprovar, name='portal_aprovar'),
    path('portal/documentos/<int:pk>/arquivo/', portal.documento_arquivo, name='portal_documento'),
    path('portal/relatorio/', portal.relatorio, name='portal_relatorio'),
    path('compras/sugestoes/', views.sugestoes, name='sugestoes'),
    path('documentos/<int:pk>/arquivo/', views.documento_arquivo, name='documento_arquivo'),
    path('preventivas/ocorrencias/<int:pk>/gerar-os/', views.preventiva_gerar, name='preventiva_gerar'),
    path('ordens/<int:pk>/operacao/<str:action>/', views.os_acao, name='os_acao'),
    path('bancos/caixa/', views.financeiro_acao, {'action': 'caixa'}, name='caixa'),
    path('bancos/transferir/', views.financeiro_acao, {'action': 'transferir'}, name='transferir'),
    path('financeiro/<int:pk>/pagar/', views.financeiro_acao, {'action': 'pagar'}, name='pagar'),
    path('financeiro/<int:pk>/parcelar/', views.financeiro_acao, {'action': 'parcelar'}, name='parcelar'),
    path('bancos/extrato/<int:pk>/conciliar/', views.financeiro_acao, {'action': 'conciliar'}, name='conciliar'),
]
for resource, prefix in {'conhecimento': 'conhecimento', 'deposito': 'depositos', 'categoria': 'categorias-pecas', 'chamado': 'chamados', 'checklist': 'checklists', 'plano': 'preventivas', 'compra': 'compras', 'venda': 'vendas', 'banco': 'bancos', 'extrato': 'bancos/extrato', 'fiscal': 'fiscal', 'documento': 'documentos', 'portal_acesso': 'portal-acessos'}.items():
    urlpatterns += [
        path(prefix + '/', views.lista, {'resource': resource}, name=resource + '_lista'),
        path(prefix + '/novo/', views.editar, {'resource': resource}, name=resource + '_novo'),
        path(prefix + '/<int:pk>/', views.detalhe, {'resource': resource}, name=resource + '_detalhe'),
        path(prefix + '/<int:pk>/editar/', views.editar, {'resource': resource}, name=resource + '_editar'),
        path(prefix + '/<int:pk>/acao/<str:action>/', views.acao, {'resource': resource}, name=resource + '_acao'),
    ]
for resource in ['compra', 'venda']:
    prefix = 'compras' if resource == 'compra' else 'vendas'
    urlpatterns += [
        path(prefix + '/<int:pk>/itens/novo/', views.item, {'resource': resource}, name=resource + '_item_novo'),
        path(prefix + '/<int:pk>/itens/<int:item_id>/', views.item, {'resource': resource}, name=resource + '_item_editar'),
        path(prefix + '/<int:pk>/itens/<int:item_id>/remover/', views.item_remover, {'resource': resource}, name=resource + '_item_remover'),
    ]
urlpatterns += [
    path('compras/<int:pk>/cotacoes/novo/', views.item, {'resource': 'compra', 'kind': 'cotacao'}, name='cotacao_novo'),
    path('compras/<int:pk>/cotacoes/<int:item_id>/', views.item, {'resource': 'compra', 'kind': 'cotacao'}, name='cotacao_editar'),
    path('compras/<int:pk>/cotacoes/<int:item_id>/remover/', views.item_remover, {'resource': 'compra', 'kind': 'cotacao'}, name='cotacao_remover'),
]
