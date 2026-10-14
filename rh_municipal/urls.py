from django.urls import path
from . import views

app_name = 'rh_municipal'
urlpatterns = [
    path('', views.home, name='home'),
    path('servidores/', views.servidores, name='servidores'),
    path('servidores/<uuid:public_id>/', views.servidor, name='servidor'),
    path('estrutura/', views.estrutura, name='estrutura'),
    path('estrutura/novo/<str:kind>/', views.estrutura_novo, name='estrutura_nova'),
    path('jornadas/nova/', views.jornada_nova, name='jornada_nova'),
    path('acessos/', views.acessos, name='acessos'),
    path('solicitacoes/', views.solicitacoes, name='solicitacoes'),
    path('portal/', views.portal, name='portal'),
]
