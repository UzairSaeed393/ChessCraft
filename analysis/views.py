from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .engine import StockfishManager
from .models import SavedAnalysis, MoveAnalysis
import chess.pgn
import io
import json

@login_required
def analysis_dashboard(request):
    """
    Renders the main analysis HTML page with the user's data.
    """
    context = {
        'username': request.user.username
    }
    return render(request, 'analysis/game_review.html', context)

@login_required
def analyze_single_position(request):
    """
    Handles live drag-and-drop "What-If" moves from the frontend.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            fen = data.get("fen")
            
            if not fen:
                return JsonResponse({"error": "No FEN provided"}, status=400)
                
            manager = StockfishManager()
            result = manager.get_analysis(fen)
            return JsonResponse(result)
            
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
            
    return JsonResponse({"error": "Invalid request method"}, status=400)

@login_required
def run_full_game_review(request):
    """
    Takes a full PGN, loops through every move, evaluates it, 
    and saves the results to the Azure PostgreSQL database.
    """
    if request.method == "POST":
        try:
            pgn_text = request.POST.get("pgn", "")
            if not pgn_text:
                return JsonResponse({"error": "No PGN provided"}, status=400)

            game = chess.pgn.read_game(io.StringIO(pgn_text))
            if not game:
                return JsonResponse({"error": "Invalid PGN formatting"}, status=400)

            board = game.board()
            manager = StockfishManager()
            
            # 1. Create the parent record for this game review
            analysis_record = SavedAnalysis.objects.create(
                user=request.user,
                pgn_data=pgn_text
            )

            eval_history = []
            prev_eval = 0.35 # Standard starting advantage for white
            
            # 2. Iterate through every move played in the game
            moves = list(game.mainline_moves())
            for i, move in enumerate(moves):
                board.push(move)
                
                # Get engine data for this move
                res = manager.get_analysis(board.fen())
                curr_eval = res.get('evaluation', 0)
                eval_history.append(curr_eval)

                # Classify move quality
                classification = manager.classify_move(prev_eval, curr_eval, not board.turn)
                
                # 3. Save the specific move to the database
                MoveAnalysis.objects.create(
                    analysis=analysis_record,
                    move_number=i+1,
                    notation=move.uci(),
                    fen=board.fen(),
                    evaluation=curr_eval,
                    classification=classification
                )
                
                prev_eval = curr_eval

            # Return success and the data needed to draw the Chart.js wave
            return JsonResponse({
                "status": "success",
                "eval_history": eval_history,
                "analysis_id": analysis_record.id
            })
            
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
            
    return JsonResponse({"error": "Invalid request method"}, status=400)