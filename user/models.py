from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. Custom User Model
# This replaces the default Django User but keeps all login functionality.
# Make sure to add 'AUTH_USER_MODEL = "user.User"' in your settings.py!
class User(AbstractUser):
    chess_username = models.CharField(max_length=100, blank=True, null=True)
    
    def __str__(self):
        return self.username

# 2. Game Model
class Game(models.Model):
    # Link to our Custom User
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="games")
    chess_username_at_time = models.CharField(max_length=100)
    game_id = models.CharField(max_length=255)
    accuracy = models.FloatField(blank=True, null=True)
    date_played = models.DateTimeField(blank=True, null=True)
    white_player = models.CharField(max_length=100)
    black_player = models.CharField(max_length=100)
    result = models.CharField(max_length=10) 
    time_control = models.CharField(max_length=50)
    opening = models.CharField(max_length=255, blank=True, null=True)
    pgn = models.TextField(blank=True, null=True)
    is_analyzed = models.BooleanField(default=False)
    white_rating = models.IntegerField(blank=True, null=True)
    black_rating = models.IntegerField(blank=True, null=True)
    

    class Meta:
        ordering = ['-date_played'] 

        constraints = [
            models.UniqueConstraint(fields=['user', 'game_id'], name='unique_user_game_id'),
        ]

    def __str__(self):
        date_part = self.date_played.date() if self.date_played else 'Unknown date'
        return f"{self.white_player} vs {self.black_player} ({date_part})"