from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. Custom User Model
# This replaces the default Django User but keeps all login functionality.
# Make sure to add 'AUTH_USER_MODEL = "user.User"' in your settings.py!
class User(AbstractUser):
    chess_username = models.CharField(max_length=100, unique=True, blank=True, null=True)
    
    def __str__(self):
        return self.username

# 2. Game Model
class Game(models.Model):
    # Link to our Custom User
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="games")
    chess_username_at_time = models.CharField(max_length=100)
    game_id = models.CharField(max_length=255, unique=True)
    accuracy = models.FloatField(blank=True, null=True)
    date_played = models.DateTimeField(blank=True, null=True)
    white_player = models.CharField(max_length=100)
    black_player = models.CharField(max_length=100)
    result = models.CharField(max_length=10) 
    time_control = models.CharField(max_length=50)
    opening = models.CharField(max_length=255, blank=True, null=True)
    pgn = models.TextField(blank=True, null=True)
    is_analyzed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date_played'] 

    def __str__(self):
        return f"{self.white_player} vs {self.black_player} ({self.date_played.date()})"