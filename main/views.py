import json
import random
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from ChessCraft.utils import api_error_handler

from .forms import ContactForm
from analysis.engine import StockfishManager
from .models import ErrorLog


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

def contact(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()  # Save message into ContactMessage table
            messages.success(request, "Your message has been sent successfully!")
            return redirect('contact')
    else:
        form = ContactForm()
    return render(request, 'main/contact.html', {'form': form})

def home(request):
    return render(request, 'main/Home.html')

def about(request):
    return render(request, 'main/about.html')

@require_POST
@api_error_handler
def play_vs_ai(request):
    """
    API endpoint for playing against Stockfish natively on the home page.
    Accepts JSON: { "fen": "...", "elo": 1500 }
    Forces LOCAL engine so UCI_LimitStrength actually works.
    """
    import chess
    
    body = json.loads(request.body or "{}")
    fen = body.get("fen")
    elo = int(body.get("elo", 1500))
    
    if not fen:
        return JsonResponse({"error": "FEN is required"}, status=400)
    
    # For very low Elo (below Stockfish's minimum of 1320),
    # occasionally pick a random legal move to simulate weak play
    if elo < 1320:
        try:
            board = chess.Board(fen)
            legal_moves = list(board.legal_moves)
            if legal_moves:
                # Below 800: ~40% random, 800-1320: ~20% random
                random_chance = 0.40 if elo < 800 else 0.20
                if random.random() < random_chance:
                    random_move = random.choice(legal_moves)
                    return JsonResponse({
                        "status": "success",
                        "best_move": random_move.uci(),
                        "evaluation": 0,
                    })
        except:
            pass
    
    # Scale depth with Elo so lower ratings think less deeply
    if elo <= 800:
        depth = 3
    elif elo <= 1200:
        depth = 5
    elif elo <= 1600:
        depth = 6
    elif elo <= 1800:
        depth = 8
    elif elo <= 2000:
        depth = 9
    elif elo <= 2500:
        depth = 11
    elif elo <= 2800:
        depth = 13
    else:
        depth = 14
    
    manager = StockfishManager()
    
    result = manager.get_analysis(fen, depth=depth, multipv=1, elo_limit=elo)
    
    return JsonResponse({
        "status": "success",
        "best_move": result.get("best_move"),
        "evaluation": result.get("evaluation"),
    })

def error_404(request, exception):
    return render(request, '404.html', status=404)

def error_500(request):
    return render(request, '500.html', status=500)


@csrf_exempt
@require_POST
def client_error_report(request):
    """Collect browser-side JS errors.

    This is intentionally best-effort: it should never raise.
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    try:
        user = request.user if getattr(request, 'user', None) is not None and request.user.is_authenticated else None
        url = str(payload.get('url') or '')
        path = str(payload.get('path') or '')
        if not path and url:
            # keep the path field readable in admin
            try:
                from urllib.parse import urlparse
                path = urlparse(url).path
            except Exception:
                path = ''

        ErrorLog.objects.create(
            kind=ErrorLog.KIND_CLIENT,
            user=user,
            path=(path or '')[:512],
            method='CLIENT',
            status_code=None,
            message=str(payload.get('message') or '')[:10000],
            traceback=str(payload.get('stack') or '')[:65000],
            source=str(payload.get('source') or payload.get('type') or '')[:256],
            lineno=payload.get('lineno') if isinstance(payload.get('lineno'), int) else None,
            colno=payload.get('colno') if isinstance(payload.get('colno'), int) else None,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            ip_address=_client_ip(request),
            extra={
                'url': url,
                'referrer': str(payload.get('referrer') or ''),
                'viewport': payload.get('viewport'),
            },
        )
    except Exception:
        pass

    return JsonResponse({'status': 'ok'})
