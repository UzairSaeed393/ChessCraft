import json
import random
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from ChessCraft.utils import api_error_handler

from .forms import ContactForm
from analysis.engine import StockfishManager

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
        depth = 7
    elif elo <= 2000:
        depth = 9
    elif elo <= 2500:
        depth = 11
    else:
        depth = 13
    
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
