from django.urls import path

from . import views

app_name = "clientes"

urlpatterns = [
    path("", views.ClienteListView.as_view(), name="cliente_list"),
    path("novo/", views.ClienteCreateView.as_view(), name="cliente_create"),
    path("<int:pk>/", views.ClienteDetailView.as_view(), name="cliente_detail"),
    path("<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="cliente_update"),
    path("unidades/nova/", views.UnidadeCreateView.as_view(), name="unidade_create"),
    path("unidades/<int:pk>/editar/", views.UnidadeUpdateView.as_view(), name="unidade_update"),
]
