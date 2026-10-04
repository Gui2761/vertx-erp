from django.urls import path
from . import views
from . import product_views

app_name = 'gestao'
urlpatterns = [
    path('estoque/<int:pk>/comercial/',product_views.relationships,name='produto_vinculos'),
    path('estoque/movimentar/', views.movimentar, name='movimentar'),
    path('orcamentos/<int:pk>/itens/novo/', views.item, name='item_novo'),
    path('orcamentos/<int:pk>/itens/<int:item_id>/editar/', views.item, name='item_editar'),
    path('orcamentos/<int:pk>/itens/<int:item_id>/remover/', views.item_remover, name='item_remover'),
    path('orcamentos/<int:pk>/status/<str:action>/', views.orcamento_status, name='orcamento_status'),
    path('orcamentos/<int:pk>/converter/', views.converter, name='converter'),
    path('orcamentos/<int:pk>/pdf/', views.orcamento_pdf, name='orcamento_pdf'),
    path('contratos/<int:pk>/gerar/<str:action>/', views.contrato_gerar, name='contrato_gerar'),
    path('contratos/planejamento/', views.planejamento, name='planejamento'),
    path('contratos/planejamento/<int:pk>/gerar-os/', views.agenda_os, name='agenda_os'),
    path('financeiro/', views.financeiro, name='financeiro'),
    path('financeiro/lancamentos/<int:pk>/operacao/<str:action>/', views.financeiro_operacao, name='financeiro_operacao'),
    path('relatorios/', views.relatorios, name='relatorios'),
    path('relatorios/<slug:key>/', views.relatorio, name='relatorio'),
]
prefixes = {'peca': 'estoque/', 'fornecedor': 'estoque/fornecedores/', 'orcamento': 'orcamentos/', 'contrato': 'contratos/', 'lancamento': 'financeiro/lancamentos/', 'categoria_financeira': 'financeiro/categorias/', 'centro_custo': 'financeiro/centros-custo/', 'forma_pagamento': 'financeiro/formas-pagamento/'}
for resource, prefix in prefixes.items():
    urlpatterns += [
        path(prefix, views.lista, {'resource': resource}, name=resource + '_lista'),
        path(prefix + 'novo/', views.editar, {'resource': resource}, name=resource + '_novo'),
        path(prefix + '<int:pk>/', views.detalhe, {'resource': resource}, name=resource + '_detalhe'),
        path(prefix + '<int:pk>/editar/', views.editar, {'resource': resource}, name=resource + '_editar'),
    ]
