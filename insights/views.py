from __future__ import annotations

import chess.pgn
import io
from collections import defaultdict
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum, Q, Max
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from analysis.models import SavedAnalysis
from user.models import Game
from user.utils import is_bullet_time_control

def api_error_handler(view_func):
    """
    Decorator to catch all exceptions in API views and return a 
    standardized JSON error response with reporting instructions.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'error': 'Internal Error',
                'message': 'Oops! Something went wrong while processing your insights. Please report this to chesscraftinfo@gmail.com or via the Contact page.',
                'details': str(e)
            }, status=500)
    return _wrapped_view

def _get_analyses(request, username: str):
    """Return SavedAnalysis rows for a username, excluding bullet games."""
    latest_ids = SavedAnalysis.objects.filter(
        user=request.user, game__chess_username_at_time__iexact=username
    ).values('game').annotate(max_id=Max('id')).values_list('max_id', flat=True)

    analyses = list(SavedAnalysis.objects.filter(id__in=latest_ids).select_related('game'))
    return [analysis for analysis in analyses if not is_bullet_time_control(getattr(analysis.game, 'time_control', None))]


def _opening_from_pgn(pgn_text: str) -> str | None:
    """Extract opening name from PGN headers."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text or ''))
        if game:
            for key in ('Opening', 'ECOUrl', 'Variant'):
                val = game.headers.get(key, '')
                if val and val not in ('?', '-', ''):
                    if key == 'ECOUrl':
                        val = val.rstrip('/').split('/')[-1].replace('-', ' ')
                    return val
    except Exception:
        pass
    return None


def _generate_tips(stats: dict, phase: dict) -> list[str]:
    tips = []
    total = stats.get('total_moves', 1) or 1
    blunder_rate = (stats.get('blunder', 0) / total) * 100
    inaccuracy_rate = (stats.get('inaccuracy', 0) / total) * 100
    avg_acc = stats.get('avg_accuracy', 75)
    white_acc = stats.get('white_accuracy', 75)
    black_acc = stats.get('black_accuracy', 75)
    opening_acc = phase.get('opening', 75)
    endgame_acc = phase.get('endgame', 75)

    if blunder_rate > 10:
        tips.append("⚠️ Your blunder rate is high. Always double-check if your pieces are safe before moving.")
    if inaccuracy_rate > 20:
        tips.append("💡 You make many inaccuracies. Slow down and look for the most forcing moves.")
    if endgame_acc < opening_acc - 15:
        tips.append("🏁 Your endgame play lags behind your opening. Study basic king + pawn and rook endgames.")
    if black_acc < white_acc - 8:
        tips.append("♟️ You play significantly better as White. Spend time studying your Black repertoire.")
    if white_acc < black_acc - 8:
        tips.append("♙ You play significantly better as Black. Consider practicing more as White.")
    if avg_acc >= 85:
        tips.append("🏆 Excellent play! You're performing at a very high level. Keep it up!")
    elif avg_acc >= 75:
        tips.append("✅ Solid performance. Focus on reducing small inaccuracies to break into the next level.")
    elif avg_acc < 60:
        tips.append("📚 Your accuracy needs improvement. Review your games move by move to find patterns in your mistakes.")
    if not tips:
        tips.append("📈 Keep analyzing your games regularly to track your improvement over time.")
    return tips


@login_required
def insights_home(request):
    usernames = (
        Game.objects.filter(user=request.user)
        .values_list('chess_username_at_time', flat=True)
        .distinct()
        .order_by('chess_username_at_time')
    )
    return render(request, 'insights/insights.html', {
        'chess_usernames': list(usernames),
    })


@login_required
@never_cache
@api_error_handler
def api_summary(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    analyses = _get_analyses(request, username)
    
    # Initialize user-centric stats
    user_white_accuracies = []
    user_black_accuracies = []
    
    user_move_counts = defaultdict(int)
    
    player_lower = username.lower()
    
    # Iterate through analyses to separate user stats from opponent
    for a in analyses:
        game_obj = a.game
        if not game_obj:
            continue
            
        # Determine user's side in this game
        is_user_white = (game_obj.white_player or "").lower() == player_lower
        is_user_black = (game_obj.black_player or "").lower() == player_lower
        
        # 1. Accuracy Attribution
        if is_user_white:
            if a.white_accuracy is not None:
                user_white_accuracies.append(a.white_accuracy)
        elif is_user_black:
            if a.black_accuracy is not None:
                user_black_accuracies.append(a.black_accuracy)
        
        # 2. Move Count Attribution (User's side only)
        # Try to use full_payload for split counts, fallback to saved total counts if needed
        # (Though current model saves totals, we want individual user counts)
        payload = a.full_payload or {}
        summary = payload.get('summary', {})
        counts = summary.get('counts', {})
        
        side_key = 'white' if is_user_white else 'black' if is_user_black else None
        
        if side_key and side_key in counts:
            # We have split counts in the payload!
            side_counts = counts[side_key]
            for cat, count in side_counts.items():
                user_move_counts[cat] += count
        else:
            # Fallback (This will happen for old analyses without full_payload)
            # We unfortunately can only use totals here, which is wrong but better than 0.
            # In a real environment, we'd trigger a re-analysis or backfill.
            pass

    # Aggregated results
    avg_white = round(sum(user_white_accuracies) / len(user_white_accuracies), 1) if user_white_accuracies else 0
    avg_black = round(sum(user_black_accuracies) / len(user_black_accuracies), 1) if user_black_accuracies else 0
    
    combined_accs = user_white_accuracies + user_black_accuracies
    avg_accuracy = round(sum(combined_accs) / len(combined_accs), 1) if combined_accs else 0

    total_games = len(combined_accs)
    
    # Win/Loss logic (Already exists in your queryset, but let's sync withGame model)
    games_qs = [
        game for game in Game.objects.filter(user=request.user, chess_username_at_time__iexact=username)
        if not is_bullet_time_control(game.time_control)
    ]
    
    white_wins = white_draws = white_losses = 0
    black_wins = black_draws = black_losses = 0
    wins = draws = losses = 0
    best_acc = worst_acc = None
    best_game_id = worst_game_id = None
    
    for g in games_qs:
        color = None
        if (g.white_player or "").lower() == player_lower:
            color = 'white'
        elif (g.black_player or "").lower() == player_lower:
            color = 'black'
            
        result = g.result or ''
        if result == 'Win':
            wins += 1
            if color == 'white': white_wins += 1
            elif color == 'black': black_wins += 1
        elif result == 'Loss':
            losses += 1
            if color == 'white': white_losses += 1
            elif color == 'black': black_losses += 1
        else:
            draws += 1
            if color == 'white': white_draws += 1
            elif color == 'black': black_draws += 1
            
        if g.accuracy is not None:
            if best_acc is None or g.accuracy > best_acc:
                best_acc = g.accuracy; best_game_id = g.id
            if worst_acc is None or g.accuracy < worst_acc:
                worst_acc = g.accuracy; worst_game_id = g.id

    phase_avg = {
        'opening': round(avg_accuracy * 1.05, 1),
        'middlegame': round(avg_accuracy, 1),
        'endgame': round(avg_accuracy * 0.92, 1),
    }

    tips = _generate_tips({
        'total_moves': sum(user_move_counts.values()),
        'blunder': user_move_counts.get('blunder', 0),
        'inaccuracy': user_move_counts.get('inaccuracy', 0),
        'avg_accuracy': avg_accuracy,
        'white_accuracy': avg_white,
        'black_accuracy': avg_black,
    }, phase_avg)

    return JsonResponse({
        'avg_accuracy': avg_accuracy,
        'white_accuracy': avg_white,
        'black_accuracy': avg_black,
        'total_games': total_games,
        'wins': wins,
        'draws': draws,
        'losses': losses,
        'win_rate': round(wins / max(wins + draws + losses, 1) * 100, 1),
        'white_stats': {
            'wins': white_wins, 'draws': white_draws, 'losses': white_losses,
            'win_rate': round(white_wins / max(white_wins + white_draws + white_losses, 1) * 100, 1) if (white_wins+white_draws+white_losses) > 0 else 0
        },
        'black_stats': {
            'wins': black_wins, 'draws': black_draws, 'losses': black_losses,
            'win_rate': round(black_wins / max(black_wins + black_draws + black_losses, 1) * 100, 1) if (black_wins+black_draws+black_losses) > 0 else 0
        },
        'best_game_id': best_game_id,
        'best_accuracy': round(best_acc, 1) if best_acc is not None else None,
        'worst_game_id': worst_game_id,
        'worst_accuracy': round(worst_acc, 1) if worst_acc is not None else None,
        'tips': tips,
        'move_counts': dict(user_move_counts),
    })


@login_required
@never_cache
@api_error_handler
def api_trend(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    analyses = sorted(_get_analyses(request, username), key=lambda analysis: analysis.game_date)
    data = []
    for a in analyses:
        # Use null-safe accuracy calculation
        w_acc = a.white_accuracy or 0.0
        b_acc = a.black_accuracy or 0.0
        avg = round((w_acc + b_acc) / 2, 1) if (w_acc or b_acc) else 0.0
        
        # Avoid expensive PGN parsing in loop; use saved opening if available
        opening = a.opening or 'Unknown'
        
        # Defensive date handling
        g_date = a.game_date
        if not g_date and a.game:
            g_date = a.game.date_played
        
        date_str = g_date.strftime('%Y-%m-%d') if g_date else 'Unknown'
        
        data.append({
            'date': date_str,
            'accuracy': avg,
            'white': round(w_acc, 1),
            'black': round(b_acc, 1),
            'opening': opening,
            'game_id': a.game.id if a.game else None,
        })
    return JsonResponse(data, safe=False)


@login_required
@never_cache
@api_error_handler
def api_move_breakdown(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    analyses = _get_analyses(request, username)
    user_move_counts = defaultdict(int)
    player_lower = username.lower()

    for a in analyses:
        game_obj = a.game
        if not game_obj: continue
        
        is_user_white = (game_obj.white_player or "").lower() == player_lower
        is_user_black = (game_obj.black_player or "").lower() == player_lower
        side_key = 'white' if is_user_white else 'black' if is_user_black else None
        
        if side_key:
            payload = a.full_payload or {}
            counts = payload.get('summary', {}).get('counts', {}).get(side_key, {})
            for cat, count in counts.items():
                user_move_counts[cat] += count

    return JsonResponse({k: v for k, v in user_move_counts.items()})


@login_required
@never_cache
@api_error_handler
def api_openings(request):
    username = request.GET.get('username', '').strip()
    color = request.GET.get('color', 'white').lower()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    games_qs = [
        game for game in Game.objects.filter(user=request.user, chess_username_at_time__iexact=username)
        if not is_bullet_time_control(game.time_control)
    ]
    opening_stats = defaultdict(lambda: {'games': 0, 'wins': 0, 'draws': 0, 'losses': 0, 'game_ids': []})
    player_lower = username.lower()

    for g in games_qs:
        is_white = g.white_player and g.white_player.lower() == player_lower
        is_black = g.black_player and g.black_player.lower() == player_lower

        if color == 'white' and not is_white: continue
        if color == 'black' and not is_black: continue

        opening = g.opening or _opening_from_pgn(g.pgn or '') or 'Unknown'
        result = g.result or ''
        st = opening_stats[opening]
        st['games'] += 1
        st['game_ids'].append(g.id)

        if result == 'Win': st['wins'] += 1
        elif result == 'Loss': st['losses'] += 1
        else: st['draws'] += 1

    sorted_openings = sorted(opening_stats.items(), key=lambda x: x[1]['games'], reverse=True)

    result_list = []
    for name, st in sorted_openings:
        total = st['games']
        result_list.append({
            'opening': name,
            'games': total,
            'wins': st['wins'],
            'draws': st['draws'],
            'losses': st['losses'],
            'win_rate': round(st['wins'] / total * 100, 1) if total else 0,
            'game_ids': st['game_ids'],
        })
    return JsonResponse(result_list, safe=False)


@login_required
@never_cache
@api_error_handler
def api_phases(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    analyses = _get_analyses(request, username)
    player_lower = username.lower()
    
    comp = {
        'white': {'opening': [], 'middlegame': [], 'endgame': []},
        'black': {'opening': [], 'middlegame': [], 'endgame': []},
    }

    for a in analyses:
        game_obj = a.game
        if not game_obj: continue
        
        if (game_obj.white_player or "").lower() == player_lower:
            if a.white_opening_acc is not None: comp['white']['opening'].append(a.white_opening_acc)
            if a.white_mid_acc is not None: comp['white']['middlegame'].append(a.white_mid_acc)
            if a.white_end_acc is not None: comp['white']['endgame'].append(a.white_end_acc)
        elif (game_obj.black_player or "").lower() == player_lower:
            if a.black_opening_acc is not None: comp['black']['opening'].append(a.black_opening_acc)
            if a.black_mid_acc is not None: comp['black']['middlegame'].append(a.black_mid_acc)
            if a.black_end_acc is not None: comp['black']['endgame'].append(a.black_end_acc)

    def _avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    res = {
        'white': {k: _avg(v) for k, v in comp['white'].items()},
        'black': {k: _avg(v) for k, v in comp['black'].items()},
    }
    
    # Calculate overall user phase averages
    overall_opening = [x for x in comp['white']['opening'] + comp['black']['opening'] if x is not None]
    overall_mid = [x for x in comp['white']['middlegame'] + comp['black']['middlegame'] if x is not None]
    overall_end = [x for x in comp['white']['endgame'] + comp['black']['endgame'] if x is not None]

    res['overall'] = {
        'opening': _avg(overall_opening),
        'middlegame': _avg(overall_mid),
        'endgame': _avg(overall_end),
    }

    return JsonResponse(res)
