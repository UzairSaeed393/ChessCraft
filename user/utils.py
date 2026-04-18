import requests
import chess.pgn
import io
from datetime import datetime, timedelta, timezone as dt_timezone
from django.db import IntegrityError
from django.utils import timezone
from .models import Game


def _extract_opening(pgn_text: str) -> str | None:
    """Pull the opening name out of PGN headers."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text or ''))
        if game:
            # Chess.com PGNs include ECOUrl like ".../openings/Italian-Game-Evans-Gambit"
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


CHESSCOM_API_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}


def _archive_month_key(archive_url):
    parts = archive_url.rstrip('/').split('/')
    if len(parts) < 2:
        return (0, 0)
    try:
        return int(parts[-2]), int(parts[-1])
    except (TypeError, ValueError):
        return (0, 0)


def _target_archives_for_limit(archives, limit_date):
    threshold = (limit_date.year, limit_date.month)
    selected = [url for url in archives if _archive_month_key(url) >= threshold]
    return selected if selected else archives[-1:]

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
    elif date_range == '30':
        limit_date = now - timedelta(days=30)
    else:
        limit_date = now - timedelta(days=60)

    target_archives = _target_archives_for_limit(archives, limit_date)

    # 3. Process each archive month
    successful_month_fetch = False
    candidates = []

    for url in target_archives:
        games_res = session.get(url, timeout=20)
        if games_res.status_code != 200:
            continue

        successful_month_fetch = True
        
        month_games = games_res.json().get('games', [])
        
        for g in month_games:
            end_time = g.get('end_time')
            if not end_time:
                continue

            game_time = datetime.fromtimestamp(end_time, tz=dt_timezone.utc)
            
            # Skip if the game is older than our calculated limit
            if game_time < limit_date:
                continue
            
            # Use Chess.com UUID as stable dedupe key.
            game_uuid = (g.get('uuid') or '').strip()
            if not game_uuid:
                continue

            candidates.append((game_uuid, game_time, g))

    if not candidates:
        return successful_month_fetch

    existing_ids = set(
        Game.objects.filter(
            user=user,
            game_id__in={game_uuid for game_uuid, _, _ in candidates},
        ).values_list('game_id', flat=True)
    )

    staged_ids = set()
    to_create = []

    for game_uuid, game_time, g in candidates:
        if game_uuid in existing_ids or game_uuid in staged_ids:
            continue

        staged_ids.add(game_uuid)

        # 4. Normalize Result (Win/Loss/Draw)
        white = g.get('white', {})
        black = g.get('black', {})
        white_username = (white.get('username') or '').strip()
        black_username = (black.get('username') or '').strip()

        is_white = white_username.lower() == api_username
        res_code = (white.get('result') if is_white else black.get('result')) or ''

        if res_code == 'win':
            outcome = 'Win'
        elif res_code in ['stalemate', 'repetition', 'insufficient', 'agreed', 'timevsinsufficient', '50move']:
            outcome = 'Draw'
        else:
            outcome = 'Loss'

        # 5. Stage for bulk insert
        pgn_text = g.get('pgn', '')
        to_create.append(
            Game(
                user=user,
                chess_username_at_time=chess_username,
                game_id=game_uuid,
                date_played=game_time,
                white_player=white_username,
                black_player=black_username,
                white_rating=white.get('rating', 0),
                black_rating=black.get('rating', 0),
                result=outcome,
                time_control=g.get('time_control', 'N/A'),
                opening=_extract_opening(pgn_text),
                pgn=pgn_text,
            )
        )

    if to_create:
        try:
            Game.objects.bulk_create(to_create, ignore_conflicts=True)
        except IntegrityError:
            # UniqueConstraint(user, game_id) still guarantees no duplicates.
            pass
            
    return successful_month_fetch