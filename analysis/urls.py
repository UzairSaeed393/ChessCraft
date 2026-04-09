from django.urls import path
from . import views

urlpatterns = [
    path('', views.analysis_dashboard, name='analysis_dashboard'),
    path('api/analyze/', views.analyze_single_position, name='analyze_single_position'),
    path('api/review/', views.run_full_game_review, name='run_full_game_review'),
]