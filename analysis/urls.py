from django.urls import path
from . import views

urlpatterns = [
    path('', views.analysis_home, name='analysis_home'),
    path('game/<int:game_id>/', views.analysis_dashboard, name='analysis_dashboard'),
    path('api/analyze/', views.analyze_single_position, name='analyze_single_position'),
    path('api/review/start/', views.run_full_game_review, name='run_full_game_review'),
    path('api/review/latest/<int:game_id>/', views.latest_saved_review, name='latest_saved_review'),
    path('api/variation/', views.analyze_variation, name='analyze_variation'),
]