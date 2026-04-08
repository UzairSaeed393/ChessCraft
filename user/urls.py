from django.urls import path
from . import views

urlpatterns = [
    path('game/', views.game_view, name="game"),
    path('profile/', views.profile_view, name="profile"),
    path('delete-account/', views.delete_account_view, name='delete_account'),
   
]
