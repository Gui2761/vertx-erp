from django.urls import path
from . import views
from . import company

app_name = 'platform_core'
urlpatterns = [path('', views.home, name='home'), path('organizacao/', views.select_organization, name='select_organization')]
urlpatterns += [path('empresa/',company.configuration,name='empresa'),path('empresa/modulos/',company.configuration,{'kind':'modulos'},name='modulos'),path('empresa/permissoes/',company.configuration,{'kind':'permissao'},name='permissoes'),path('empresa/filiais/nova/',company.configuration,{'kind':'filial'},name='filial_nova'),path('empresa/filiais/<uuid:public_id>/',company.configuration,{'kind':'filial'},name='filial_editar')]
