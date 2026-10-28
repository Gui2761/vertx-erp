from django.urls import path
from contas.views import LoginView
from . import views

app_name='commercial'
urlpatterns=[
    path('',views.home,name='home'),
    path('planos/',views.pricing,name='pricing'),
    path('cadastro/',views.signup,name='signup'),
    path('cadastro/confirmacao/',views.signup_confirmation,name='signup_confirmation'),
    path('cadastro/primeiro-acesso/',views.signup_first_access,name='signup_first_access'),
    path('demonstracao/',views.demo,name='demo'),
    path('contato/',views.demo,name='contact'),
    path('solicitacao-recebida/',views.thanks,name='thanks'),
    path('suporte/',views.information,{'kind':'support'},name='support'),
    path('termos/',views.information,{'kind':'terms'},name='terms'),
    path('privacidade/',views.information,{'kind':'privacy'},name='privacy'),
    path('login/',LoginView.as_view(),name='login'),
    path('robots.txt',views.robots,name='robots'),
]
