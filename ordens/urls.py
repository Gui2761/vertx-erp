from django.urls import path
from . import views

app_name = 'ordens'
urlpatterns = [
    path('', views.lista, name='lista'),
    path('nova/', views.criar, name='criar'),
    path('<int:pk>/', views.detalhe, name='detalhe'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/iniciar/', views.iniciar, name='iniciar'),
    path('<int:pk>/fotos/adicionar/', views.foto_adicionar, name='foto_adicionar'),
    path('<int:pk>/fotos/<int:foto_id>/', views.foto, name='foto'),
    path('<int:pk>/preparar/', views.preparar, name='preparar'),
    path('<int:pk>/conferencia/<str:token>/', views.conferencia, name='conferencia'),
    path('<int:pk>/finalizar/', views.finalizar, name='finalizar'),
    path('<int:pk>/reabrir/', views.reabrir, name='reabrir'),
    path('<int:pk>/assinaturas/<int:assinatura_id>/imagem/', views.assinatura_imagem, name='assinatura_imagem'),
    path('<int:pk>/assinaturas/<int:assinatura_id>/pdf/', views.pdf, name='pdf'),
]
