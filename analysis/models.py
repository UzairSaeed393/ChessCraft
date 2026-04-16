from django.conf import settings
from django.db import models
from user.models import Game

class SavedAnalysis(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, null=True, blank=True, on_delete=models.CASCADE, related_name='analyses')
    game_date = models.DateTimeField(auto_now_add=True)
    pgn_data = models.TextField()
    
    full_payload = models.JSONField(null=True, blank=True)
    
    # Overall Stats
    white_accuracy = models.FloatField(default=0.0)
    black_accuracy = models.FloatField(default=0.0)
    white_rating_est = models.IntegerField(default=0)
    black_rating_est = models.IntegerField(default=0)
    
    # Phase Accuracies (No proxy, real engine evaluations)
    white_opening_acc = models.FloatField(blank=True, null=True)
    white_mid_acc = models.FloatField(blank=True, null=True)
    white_end_acc = models.FloatField(blank=True, null=True)
    
    black_opening_acc = models.FloatField(blank=True, null=True)
    black_mid_acc = models.FloatField(blank=True, null=True)
    black_end_acc = models.FloatField(blank=True, null=True)
    
    # Move Count Breakdown
    brilliant_count = models.IntegerField(default=0)
    great_count = models.IntegerField(default=0)
    best_count = models.IntegerField(default=0)
    excellent_count = models.IntegerField(default=0)
    good_count = models.IntegerField(default=0)
    book_count = models.IntegerField(default=0)
    inaccuracy_count = models.IntegerField(default=0)
    miss_count = models.IntegerField(default=0)
    mistake_count = models.IntegerField(default=0)
    blunder_count = models.IntegerField(default=0)

    # Opening info (populated from Lichess API / PGN headers during analysis)
    opening = models.CharField(max_length=255, blank=True, null=True)
    eco_code = models.CharField(max_length=10, blank=True, null=True)
    
    result_reason = models.CharField(max_length=255, blank=True, null=True)

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