from django.urls import path
from . import views

app_name = 'platform_core'
urlpatterns = [path('', views.home, name='home'), path('organizacao/', views.select_organization, name='select_organization')]
