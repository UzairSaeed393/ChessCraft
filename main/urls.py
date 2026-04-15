from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),   
    path('about/', views.about, name='about'),  
    path('contact/', views.contact, name='contact'),   
    path('api/play-vs-ai/', views.play_vs_ai, name='play_vs_ai'),
    path('api/client-error/', views.client_error_report, name='client_error_report'),
]
