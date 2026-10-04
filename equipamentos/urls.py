from django.urls import path

from . import views

app_name = "equipamentos"

urlpatterns = [
    path('<int:pk>/etiqueta/', views.etiqueta, name='etiqueta'),
    path('categorias/nova/', views.CategoriaCreateView.as_view(), name='categoria_create'),
    path('categorias/<int:pk>/editar/', views.CategoriaUpdateView.as_view(), name='categoria_update'),
    path("", views.EquipamentoListView.as_view(), name="equipamento_list"),
    path("novo/", views.EquipamentoCreateView.as_view(), name="equipamento_create"),
    path("<int:pk>/", views.EquipamentoDetailView.as_view(), name="equipamento_detail"),
    path("<int:pk>/editar/", views.EquipamentoUpdateView.as_view(), name="equipamento_update"),
    path(
        "qr/<uuid:codigo_publico>/",
        views.EquipamentoQrRedirectView.as_view(),
        name="equipamento_qr",
    ),
    path("ajax/unidades/", views.unidades_por_cliente, name="unidades_por_cliente"),
]
