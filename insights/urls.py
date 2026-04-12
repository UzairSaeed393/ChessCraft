from django.urls import path
from . import views

urlpatterns = [
    path('', views.insights_home, name='insights_home'),
    path('api/summary/', views.api_summary, name='insights_api_summary'),
    path('api/trend/', views.api_trend, name='insights_api_trend'),
    path('api/move-breakdown/', views.api_move_breakdown, name='insights_api_move_breakdown'),
    path('api/openings/', views.api_openings, name='insights_api_openings'),
    path('api/phases/', views.api_phases, name='insights_api_phases'),
]
