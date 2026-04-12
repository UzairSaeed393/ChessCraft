import json
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
    """
    body = json.loads(request.body or "{}")
    fen = body.get("fen")
    elo = int(body.get("elo", 1500))
    
    if not fen:
        return JsonResponse({"error": "FEN is required"}, status=400)
        
    manager = StockfishManager()
    # Request best move with a small depth to limit strength properly along with Elo
    result = manager.get_analysis(fen, depth=10, multipv=1, elo_limit=elo)
    
    return JsonResponse({
        "status": "success",
        "best_move": result.get("best_move"),
        "evaluation": result.get("evaluation"),
    })

def error_404(request, exception):
    return render(request, '404.html', status=404)

def error_500(request):
    return render(request, '500.html', status=500)
