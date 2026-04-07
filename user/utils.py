import requests
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone
from .models import Game


CHESSCOM_API_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

def fetch_and_save_games(user, chess_username, date_range):
    api_username = (chess_username or '').strip().lower()
    if not api_username:
        return False

    session = requests.Session()
    session.headers.update(CHESSCOM_API_HEADERS)

    # 1. Get the list of all monthly archives for this player
    archive_url = f"https://api.chess.com/pub/player/{api_username}/games/archives"
    res = session.get(archive_url, timeout=15)
    if res.status_code != 200:
        return False
    
    archives = res.json().get('archives', [])
    if not archives:
        # Valid user but no games yet.
        return True

    # 2. Determine time limit based on range
    now = timezone.now()
    if date_range == 'week':
        limit_date = now - timedelta(days=7)
        target_archives = archives[-1:] # Just the current month
    elif date_range == 'month':
        limit_date = now - timedelta(days=30)
        target_archives = archives[-2:] # Current and previous month to be safe
    else: # year
        limit_date = now - timedelta(days=365)
        target_archives = archives[-12:] # Last 12 months

    # 3. Process each archive month
    successful_month_fetch = False
    for url in target_archives:
        games_res = session.get(url, timeout=20)
        if games_res.status_code != 200:
            continue

        successful_month_fetch = True
        
        month_games = games_res.json().get('games', [])
        
        for g in month_games:
            game_time = datetime.fromtimestamp(g['end_time'], tz=dt_timezone.utc)
            
            # Skip if the game is older than our calculated limit
            if game_time < limit_date:
                continue
            
            # Avoid duplicates (Crucial for Postgres performance)
            game_uuid = g.get('uuid')
            if not game_uuid:
                continue

            if Game.objects.filter(user=user, game_id=game_uuid).exists():
                continue

            # 4. Normalize Result (Win/Loss/Draw)
            white, black = g['white'], g['black']
            is_white = white['username'].lower() == api_username
            res_code = white['result'] if is_white else black['result']
            
            if res_code == 'win':
                outcome = 'Win'
            elif res_code in ['stalemate', 'repetition', 'insufficient', 'agreed', 'timevsinsufficient', '50move']:
                outcome = 'Draw'
            else:
                outcome = 'Loss'

            # 5. Commit to Database
            Game.objects.create(
                user=user,
                chess_username_at_time=chess_username,
                game_id=game_uuid,
                date_played=game_time,
                white_player=white['username'],
                black_player=black['username'],
                white_rating=white.get('rating', 0),
                black_rating=black.get('rating', 0),
                result=outcome,
                time_control=g.get('time_control', 'N/A'),
                pgn=g.get('pgn', '')
            )
            
    return successful_month_fetch