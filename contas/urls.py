from django.urls import path

from . import views

app_name = "contas"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("usuarios/", views.UsuarioListView.as_view(), name="usuario_list"),
    path("usuarios/novo/", views.UsuarioCreateView.as_view(), name="usuario_create"),
    path("usuarios/<int:pk>/editar/", views.UsuarioUpdateView.as_view(), name="usuario_update"),
    path("tecnicos/", views.TecnicoListView.as_view(), name="tecnico_list"),
    path("tecnicos/novo/", views.TecnicoCreateView.as_view(), name="tecnico_create"),
    path("tecnicos/<int:pk>/editar/", views.TecnicoUpdateView.as_view(), name="tecnico_update"),
]
