from django.urls import path
from . import views
from . import company
from . import saas_views

app_name = 'platform_core'
urlpatterns = [path('', views.home, name='home'), path('organizacao/', views.select_organization, name='select_organization')]
urlpatterns += [path('empresa/',company.configuration,name='empresa'),path('empresa/modulos/',company.configuration,{'kind':'modulos'},name='modulos'),path('empresa/permissoes/',company.configuration,{'kind':'permissao'},name='permissoes'),path('empresa/filiais/nova/',company.configuration,{'kind':'filial'},name='filial_nova'),path('empresa/filiais/<uuid:public_id>/',company.configuration,{'kind':'filial'},name='filial_editar')]
urlpatterns += [
    path('saas/manifest.webmanifest', saas_views.manifest, name='saas_manifest'),
    path('saas/sw.js', saas_views.service_worker, name='saas_sw'),
    path('saas/', saas_views.inicio, name='saas_home'),
    path('saas/clientes/', saas_views.clientes, name='saas_clients'),
    path('saas/clientes/novo/', saas_views.novo_cliente, name='saas_new_client'),
    path('saas/clientes/novo/plano/', saas_views.novo_cliente, {'step': 2}, name='saas_new_client_step2'),
    path('saas/clientes/<uuid:public_id>/', saas_views.cliente_detalhe, name='saas_client_detail'),
    path('saas/clientes/<uuid:public_id>/editar/', saas_views.editar_cliente, name='saas_client_edit'),
    path('saas/clientes/<uuid:public_id>/plano/', saas_views.alterar_plano_cliente, name='saas_client_change_plan'),
    path('saas/clientes/<uuid:public_id>/status/<str:action>/', saas_views.status_cliente, name='saas_client_status'),
    path('saas/clientes/<uuid:public_id>/compartilhar-acesso/', saas_views.compartilhar_acesso, name='saas_share_access'),
    path('saas/clientes/<uuid:public_id>/reemitir-acesso/', saas_views.reemitir_acesso, name='saas_reissue_access'),
    path('saas/planos/', saas_views.planos, name='saas_plans'),
    path('saas/planos/novo/', saas_views.plano_form, name='saas_plan_create'),
    path('saas/planos/<int:pk>/editar/', saas_views.plano_form, name='saas_plan_edit'),
    path('primeiro-acesso/<str:token>/', saas_views.primeiro_acesso, name='saas_first_access'),
]
