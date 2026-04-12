from django.conf import settings  # Change this line
from django.db import models

class SavedAnalysis(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    game_date = models.DateTimeField(auto_now_add=True)
    pgn_data = models.TextField()  # The full move history
    
    # Overall Stats
    white_accuracy = models.FloatField(default=0.0)
    black_accuracy = models.FloatField(default=0.0)
    white_rating_est = models.IntegerField(default=0)
    black_rating_est = models.IntegerField(default=0)
    
    # Move Count Breakdown
    brilliant_count = models.IntegerField(default=0)
    great_count = models.IntegerField(default=0)
    best_count = models.IntegerField(default=0)
    excelllent_count = models.IntegerField(default=0)
    good_count = models.IntegerField(default=0)
    book_count = models.IntegerField(default=0)
    inaccuracy_count = models.IntegerField(default=0)
    miss_count = models.IntegerField(default=0)
    mistake_count = models.IntegerField(default=0)
    blunder_count = models.IntegerField(default=0)

    def __str__(self):
        return f"Analysis for {self.user.username} - {self.game_date.date()}"

class MoveAnalysis(models.Model):
    analysis = models.ForeignKey(SavedAnalysis, related_name='moves', on_delete=models.CASCADE)
    move_number = models.IntegerField()
    notation = models.CharField(max_length=10) # e.g., "e4"
    fen = models.TextField() # Position after this move
    evaluation = models.FloatField() # +1.5, -0.8, etc.
    classification = models.CharField(max_length=20) # Brilliant, Blunder, etc.
    explanation = models.TextField(blank=True) # Text like "d5 is a book move"