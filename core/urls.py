from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("assistencia/", views.PainelView.as_view(), name="painel"),
]
