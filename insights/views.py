from __future__ import annotations

import chess.pgn
import io
from collections import defaultdict
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum, Q, Max
from django.http import JsonResponse
from django.shortcuts import render

from analysis.models import SavedAnalysis
from user.models import Game

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
            return JsonResponse({
                'error': 'Internal Error',
                'message': 'Oops! Something went wrong while processing your insights. Please report this to chesscraftinfo@gmail.com or via the Contact page.',
                'details': str(e)
            }, status=500)
    return _wrapped_view

def _get_analyses(request, username: str):
    """Return SavedAnalysis queryset for a username, preventing duplicates."""
    latest_ids = SavedAnalysis.objects.filter(
        user=request.user, game__chess_username_at_time__iexact=username
    ).values('game').annotate(max_id=Max('id')).values_list('max_id', flat=True)

    return SavedAnalysis.objects.filter(
        id__in=latest_ids
    ).exclude(
        game__time_control__in=['60', '60+1', '60+2', '30', '120', '120+1']
    ).select_related('game')


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
@api_error_handler
def api_summary(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    analyses = _get_analyses(request, username)
    agg = analyses.aggregate(
        avg_white=Avg('white_accuracy'),
        avg_black=Avg('black_accuracy'),
        total=Count('id'),
        tot_brilliant=Sum('brilliant_count'),
        tot_great=Sum('great_count'),
        tot_best=Sum('best_count'),
        tot_excellent=Sum('excellent_count'),
        tot_good=Sum('good_count'),
        tot_book=Sum('book_count'),
        tot_inaccuracy=Sum('inaccuracy_count'),
        tot_miss=Sum('miss_count'),
        tot_mistake=Sum('mistake_count'),
        tot_blunder=Sum('blunder_count'),
    )

    white_acc = round(agg['avg_white'] or 0, 1)
    black_acc = round(agg['avg_black'] or 0, 1)
    avg_accuracy = round((white_acc + black_acc) / 2, 1) if (white_acc + black_acc) else 0

    total_moves = sum([
        agg['tot_brilliant'] or 0, agg['tot_great'] or 0, agg['tot_best'] or 0,
        agg['tot_excellent'] or 0, agg['tot_good'] or 0, agg['tot_book'] or 0,
        agg['tot_inaccuracy'] or 0, agg['tot_miss'] or 0,
        agg['tot_mistake'] or 0, agg['tot_blunder'] or 0,
    ])

    games_qs = Game.objects.filter(user=request.user, chess_username_at_time__iexact=username).exclude(
        time_control__in=['60', '60+1', '60+2', '30', '120', '120+1']
    )
    white_wins = white_draws = white_losses = 0
    black_wins = black_draws = black_losses = 0
    wins = draws = losses = 0
    best_acc = worst_acc = None
    best_game_id = worst_game_id = None
    
    player_lower = username.lower()
    for g in games_qs:
        color = None
        if g.white_player and g.white_player.lower() == player_lower:
            color = 'white'
        elif g.black_player and g.black_player.lower() == player_lower:
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
        'total_moves': total_moves,
        'blunder': agg['tot_blunder'] or 0,
        'inaccuracy': agg['tot_inaccuracy'] or 0,
        'avg_accuracy': avg_accuracy,
        'white_accuracy': white_acc,
        'black_accuracy': black_acc,
    }, phase_avg)

    return JsonResponse({
        'avg_accuracy': avg_accuracy,
        'white_accuracy': white_acc,
        'black_accuracy': black_acc,
        'total_games': agg['total'] or 0,
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
        'best_accuracy': round(best_acc, 1) if best_acc else None,
        'worst_game_id': worst_game_id,
        'worst_accuracy': round(worst_acc, 1) if worst_acc else None,
        'tips': tips,
        'move_counts': {
            'brilliant': agg['tot_brilliant'] or 0,
            'great': agg['tot_great'] or 0,
            'best': agg['tot_best'] or 0,
            'excellent': agg['tot_excellent'] or 0,
            'good': agg['tot_good'] or 0,
            'book': agg['tot_book'] or 0,
            'inaccuracy': agg['tot_inaccuracy'] or 0,
            'miss': agg['tot_miss'] or 0,
            'mistake': agg['tot_mistake'] or 0,
            'blunder': agg['tot_blunder'] or 0,
        },
    })


@login_required
@api_error_handler
def api_trend(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    analyses = _get_analyses(request, username).order_by('game_date')
    data = []
    for a in analyses:
        avg = round((a.white_accuracy + a.black_accuracy) / 2, 1)
        opening = a.opening or _opening_from_pgn(a.pgn_data) or 'Unknown'
        data.append({
            'date': a.game_date.strftime('%Y-%m-%d'),
            'accuracy': avg,
            'white': round(a.white_accuracy, 1),
            'black': round(a.black_accuracy, 1),
            'opening': opening,
            'game_id': a.game.id if a.game else None,
        })
    return JsonResponse(data, safe=False)


@login_required
@api_error_handler
def api_move_breakdown(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    agg = _get_analyses(request, username).aggregate(
        brilliant=Sum('brilliant_count'),
        great=Sum('great_count'),
        best=Sum('best_count'),
        excellent=Sum('excellent_count'),
        good=Sum('good_count'),
        book=Sum('book_count'),
        inaccuracy=Sum('inaccuracy_count'),
        miss=Sum('miss_count'),
        mistake=Sum('mistake_count'),
        blunder=Sum('blunder_count'),
    )
    return JsonResponse({k: v or 0 for k, v in agg.items()})


@login_required
@api_error_handler
def api_openings(request):
    username = request.GET.get('username', '').strip()
    color = request.GET.get('color', 'white').lower()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    games_qs = Game.objects.filter(user=request.user, chess_username_at_time__iexact=username).exclude(
        time_control__in=['60', '60+1', '60+2', '30', '120', '120+1']
    )
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

    sorted_openings = sorted(opening_stats.items(), key=lambda x: x[1]['games'], reverse=True)[:10]
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
@api_error_handler
def api_phases(request):
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    analyses = _get_analyses(request, username)
    agg = analyses.aggregate(
        w_op=Avg('white_opening_acc'),
        w_md=Avg('white_mid_acc'),
        w_en=Avg('white_end_acc'),
        b_op=Avg('black_opening_acc'),
        b_md=Avg('black_mid_acc'),
        b_en=Avg('black_end_acc'),
    )

    def _avg(a, b):
        if a and b: return round((a + b) / 2, 1)
        return round(a or b or 0, 1)

    return JsonResponse({
        'white': {
            'opening': round(agg['w_op'] or 0, 1),
            'middlegame': round(agg['w_md'] or 0, 1),
            'endgame': round(agg['w_en'] or 0, 1),
        },
        'black': {
            'opening': round(agg['b_op'] or 0, 1),
            'middlegame': round(agg['b_md'] or 0, 1),
            'endgame': round(agg['b_en'] or 0, 1),
        },
        'overall': {
            'opening': _avg(agg['w_op'], agg['b_op']),
            'middlegame': _avg(agg['w_md'], agg['b_md']),
            'endgame': _avg(agg['w_en'], agg['b_en']),
        }
    })
