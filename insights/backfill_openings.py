"""
One-time script to backfill opening names.
Run with: python3 manage.py runscript backfill_openings
Or just: python3 insights/backfill_openings.py  (from project root)
"""
import os, sys, django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ChessCraft.settings')
django.setup()

import chess.pgn
import io
from user.models import Game

def extract_opening(pgn_text):
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text or ''))
        if game:
            eco_url = game.headers.get('ECOUrl', '')
            if eco_url:
                name = eco_url.rstrip('/').split('/')[-1].replace('-', ' ')
                if name:
                    return name
            opening = game.headers.get('Opening', '')
            if opening and opening not in ('?', '-', ''):
                return opening
    except Exception:
        pass
    return None

updated = 0
for g in Game.objects.filter(pgn__isnull=False).exclude(pgn=''):
    if g.opening and g.opening != 'Unknown':
        continue
    name = extract_opening(g.pgn)
    if name:
        g.opening = name
        g.save(update_fields=['opening'])
        updated += 1

print(f"Backfilled {updated} games with opening names.")
