from __future__ import annotations

import io
import json
from collections import defaultdict

import chess
import chess.pgn
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from datetime import timedelta
from ChessCraft.utils import api_error_handler

from user.models import Game

from .engine import (
    StockfishManager,
    accuracy_from_move_accuracies,
    classify_move,
    move_accuracy_from_category,
)
from .models import MoveAnalysis, SavedAnalysis


CATEGORIES = [
    "brilliant",
    "best",
    "great",
    "excellent",
    "good",
    "book",
    "inaccuracy",
    "miss",
    "mistake",
    "blunder",
]

PHASES = ["opening", "middlegame", "endgame"]
REVIEW_ALGO_VERSION = 5
OPENING_API_BLOCKED = False


def _json_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _phase_for_position(board: chess.Board, ply_index: int) -> str:
    if ply_index <= 16:
        return "opening"

    white_queens = len(board.pieces(chess.QUEEN, chess.WHITE))
    black_queens = len(board.pieces(chess.QUEEN, chess.BLACK))
    non_king_pieces = sum(
        1 for piece in board.piece_map().values() if piece.piece_type != chess.KING
    )
    if (white_queens + black_queens == 0) or non_king_pieces <= 10:
        return "endgame"
    return "middlegame"


def _to_san_line(start_fen: str, uci_line: list[str], max_moves: int = 6) -> list[str]:
    board = chess.Board(start_fen)
    san_line = []
    for uci in uci_line[:max_moves]:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        san_line.append(board.san(move))
        board.push(move)
    return san_line


def _estimate_rating(accuracy: float, baseline: int) -> int:
    # Keep rating estimate stable around real game rating while reflecting move quality.
    delta = int((accuracy - 50.0) * 8)
    estimated = baseline + delta
    return max(400, min(3200, estimated))


def _accuracy_label(acc: float) -> str:
    if acc >= 92:
        return "excellent"
    if acc >= 82:
        return "good"
    if acc >= 70:
        return "fair"
    return "needs work"


def _build_move_explanation(
    category: str,
    move_san: str,
    best_san: str,
    cp_loss: int,
    phase: str,
) -> str:
    phase_name = "middlegame" if phase == "middlegame" else phase

    if category == "brilliant":
        return f"{move_san} is a brilliant practical move and keeps top-engine advantage in the {phase_name}."
    if category == "best":
        return f"{move_san} matches the top engine choice for this position."
    if category == "excellent":
        return f"{move_san} is very strong. Best was {best_san}, but your move keeps the position healthy."
    if category == "great":
        return f"{move_san} is a great move. You missed only a tiny improvement ({best_san})."
    if category == "good":
        return f"{move_san} is playable, but {best_san} was more accurate by about {cp_loss} centipawns."
    if category == "inaccuracy":
        return f"{move_san} is an inaccuracy. {best_san} was the cleaner continuation here."
    if category == "miss":
        return f"{move_san} missed a tactical chance. Engine preferred {best_san} to gain more advantage."
    if category == "mistake":
        return f"{move_san} is a mistake and gives up a noticeable edge. Better was {best_san}."
    if category == "blunder":
        return f"{move_san} is a blunder. {best_san} was critical to avoid a major swing."
    if category == "book":
        return f"{move_san} is a standard opening book move."
    
    return f"{move_san} was played."

def _fetch_opening_info(session: requests.Session, fen: str, move_uci: str = None) -> dict:
    """Fetch opening name and check if move_uci is theoretical via Lichess."""
    global OPENING_API_BLOCKED
    if OPENING_API_BLOCKED:
        return {"name": None, "eco": None, "is_theory": False, "failed": True}

    try:
        url = "https://explorer.lichess.ovh/masters"
        # Always use params so requests correctly urlencodes the FEN
        resp = session.get(url, params={"fen": fen, "moves": 12}, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            opening = data.get("opening")
            
            is_book = False
            # If we have a move_uci, check if it exists in the top theoretical moves
            if move_uci:
                theory_moves = [m.get("uci") for m in data.get("moves", [])]
                if move_uci in theory_moves:
                    is_book = True
            elif opening:
                is_book = True

            return {
                "name": opening.get("name") if opening else None,
                "eco": opening.get("eco") if opening else None,
                "is_theory": is_book,
                "failed": False
            }
        if resp.status_code in (401, 403):
            OPENING_API_BLOCKED = True
    except Exception:
        pass
    return {"name": None, "eco": None, "is_theory": False, "failed": True}


def _empty_side_stats():
    return {
        "move_accuracies": [],
        "counts": {key: 0 for key in CATEGORIES},
        "phase": {name: [] for name in PHASES},
        "severe_streak": 0,
    }


def _parse_pgn_or_raise(pgn_text: str):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        raise ValueError("Invalid PGN data")
    return game


def _build_game_review_payload(game_obj, user, priority=0) -> tuple[dict, SavedAnalysis]:
    engine = StockfishManager()
    parsed_game = _parse_pgn_or_raise(game_obj.pgn or "")

    # Use a deeper search for full game review only.
    # Live board/position analysis still uses the regular engine default depth.
    review_depth = int(getattr(settings, "ANALYSIS_GAME_REVIEW_DEPTH", 20))
    review_depth = max(16, review_depth)

    board = parsed_game.board()
    start_fen = board.fen()
    eval_history = []
    moves_payload = []
    
    # Try to extract opening from PGN headers first
    opening_name = parsed_game.headers.get("Opening", "Initial Position")

    side_stats = {
        "white": _empty_side_stats(),
        "black": _empty_side_stats(),
    }

    # Before creating new SavedAnalysis, delete previous ones for this game to prevent duplicates in insights
    SavedAnalysis.objects.filter(user=user, game=game_obj).delete()

    analysis_record = SavedAnalysis.objects.create(
        user=user,
        game=game_obj,
        pgn_data=game_obj.pgn or "",
    )

    move_rows = []
    mainline_moves = list(parsed_game.mainline_moves())

    # 1. Collect all FENs for batch processing
    all_fens = [start_fen]
    temp_board = parsed_game.board()
    for move in mainline_moves:
        temp_board.push(move)
        all_fens.append(temp_board.fen())

    # 2. Send all FENs to engine in a single batch request
    print(f"Batch analyzing {len(all_fens)} positions with priority {priority}...")
    batch_results = engine.analyze_batch(
        all_fens,
        depth=review_depth,
        multipv=1,
        priority=priority,
    )

    session = requests.Session()
    # Add a custom User-Agent to avoid Lichess blocking the default python-requests UA
    session.headers.update({"User-Agent": "ChessCraft-Analysis-Engine/1.0"})
    in_book = True  # We assume we are in book until a non-theory move is played

    for ply_index, move in enumerate(mainline_moves, start=1):
        fen_before = board.fen()
        side = "white" if board.turn else "black"
        phase = _phase_for_position(board, ply_index)

        is_book = False

        # Retrieve cached batch results (0-indexed logic)
        if ply_index - 1 < len(batch_results):
            before_eval = batch_results[ply_index - 1]
            cp_before = int(before_eval.get("evaluation_cp") or 0)
            best_move_uci = before_eval.get("best_move") or ""
            best_pv_uci = before_eval.get("pv") or []
        else:
            cp_before = 0
            best_move_uci = ""
            best_pv_uci = []

        move_san = board.san(move)
        move_uci = move.uci()

        after_board = board.copy()
        after_board.push(move)
        fen_after = after_board.fen()

        if ply_index < len(batch_results):
            after_eval = batch_results[ply_index]
            cp_after = int(after_eval.get("evaluation_cp") or 0)
            follow_pv_uci = after_eval.get("pv") or []
            mate_after = after_eval.get("mate")
        else:
            cp_after = cp_before
            follow_pv_uci = []
            mate_after = None

        mate_before = before_eval.get("mate") if ply_index - 1 < len(batch_results) else None

        if side == "white":
            cp_loss = max(0, cp_before - cp_after)
            cp_gain = cp_after - cp_before
            potential_gain = cp_loss
        else:
            cp_loss = max(0, cp_after - cp_before)
            cp_gain = cp_before - cp_after
            potential_gain = cp_loss

        # Apply Book detection now that we have CP loss
        if in_book and ply_index <= 20:
            info = _fetch_opening_info(session, fen_before, move_uci=move_uci)
            if info.get("failed"):
                # Offline Fallback if Lichess is rate-limited: 
                # First 3 full moves (6 plies) that don't lose advantage are "book"
                if ply_index <= 6 and cp_loss <= 25:
                    is_book = True
                else:
                    in_book = False
            else:
                if info["is_theory"]:
                    # Treat as book only if the move does not already lose too much.
                    if cp_loss <= 40:
                        is_book = True
                        if info["name"]:
                            opening_name = info["name"]
                    else:
                        in_book = False
                else:
                    in_book = False
        else:
            in_book = False

        category = classify_move(
            cp_loss=cp_loss,

            cp_gain=cp_gain,
            potential_gain=potential_gain,
            move_uci=move_uci,
            best_move_uci=best_move_uci,
            board_before=board,
            is_book=is_book,
            cp_before=cp_before,
            cp_after=cp_after,
            side=side,
            mate_before=mate_before,
            mate_after=mate_after,
        )

        # Book moves don't count towards accuracy loss
        if category == "book":
            cp_loss = 0
            cp_gain = 0

        if category in {"mistake", "blunder"}:
            side_stats[side]["severe_streak"] += 1
        else:
            side_stats[side]["severe_streak"] = 0

        move_accuracy = move_accuracy_from_category(
            category=category,
            cp_loss=cp_loss,
            side=side,
            mate_before=mate_before,
            mate_after=mate_after,
            severe_streak=side_stats[side]["severe_streak"],
        )

        best_san = "(none)"
        if best_move_uci:
            try:
                best_move = chess.Move.from_uci(best_move_uci)
                if best_move in board.legal_moves:
                    best_san = board.san(best_move)
            except ValueError:
                best_san = "(none)"

        explanation = _build_move_explanation(
            category=category,
            move_san=move_san,
            best_san=best_san,
            cp_loss=cp_loss,
            phase=phase,
        )

        best_line_san = _to_san_line(fen_before, best_pv_uci)
        follow_line_san = _to_san_line(fen_after, follow_pv_uci)

        side_stats[side]["move_accuracies"].append(move_accuracy)
        side_stats[side]["phase"][phase].append(move_accuracy)
        side_stats[side]["counts"][category] += 1

        moves_payload.append(
            {
                "ply": ply_index,
                "move_number": (ply_index + 1) // 2,
                "side": side,
                "san": move_san,
                "uci": move_uci,
                "phase": phase,
                "fen_before": fen_before,
                "fen_after": fen_after,
                "evaluation_before": round(cp_before / 100.0, 2),
                "evaluation_after": round(cp_after / 100.0, 2),
                "mate_before": mate_before,
                "mate_after": mate_after,
                "centipawn_loss": cp_loss,
                "classification": category,
                "best_move": best_move_uci,
                "best_move_san": best_san,
                "best_line": best_line_san,
                "follow_line": follow_line_san,
                "explanation": explanation,
            }
        )

        move_rows.append(
            MoveAnalysis(
                analysis=analysis_record,
                move_number=ply_index,
                notation=move_san[:10],
                fen=fen_after,
                evaluation=round(cp_after / 100.0, 2),
                classification=category.title(),
                explanation=explanation,
            )
        )

        eval_history.append(round(cp_after / 100.0, 2))
        board.push(move)

    if move_rows:
        MoveAnalysis.objects.bulk_create(move_rows)

    white_accuracy = accuracy_from_move_accuracies(side_stats["white"]["move_accuracies"])
    black_accuracy = accuracy_from_move_accuracies(side_stats["black"]["move_accuracies"])

    # --- Game Result & Termination Logic ---
    headers = parsed_game.headers
    result = headers.get("Result", "*")
    termination = headers.get("Termination", "Normal")
    white_name = headers.get("White", "White")
    black_name = headers.get("Black", "Black")

    winner_name = None
    if result == "1-0":
        winner_name = white_name
    elif result == "0-1":
        winner_name = black_name

    # Refine termination reason
    res_reason = termination
    if termination.lower() == "normal":
        # Check if it was checkmate
        if board.is_checkmate():
            res_reason = "Checkmate"
        elif board.is_stalemate():
            res_reason = "Stalemate"
        elif board.is_insufficient_material():
            res_reason = "Insufficient Material"
        else:
            res_reason = "Normal"

    final_result_text = ""
    if winner_name:
        final_result_text = f"{winner_name} won by {res_reason.lower()}"
    else:
        if result == "1/2-1/2":
            final_result_text = f"Draw by {res_reason.lower()}"
        else:
            final_result_text = f"Game ended: {result}"

    # Standardize result text for common terms
    final_result_text = final_result_text.replace("by time forfeit", "by timeout")

    total_counts = defaultdict(int)
    for side in ("white", "black"):
        for name, value in side_stats[side]["counts"].items():
            total_counts[name] += value

    data = {
        "id": game_obj.game_id,
        "date": game_obj.date_played.isoformat() if game_obj.date_played else None,
        "white": {"name": game_obj.white_player, "accuracy": white_accuracy, "rating": game_obj.white_rating or 0},
        "black": {"name": game_obj.black_player, "accuracy": black_accuracy, "rating": game_obj.black_rating or 0},
        "moves": moves_payload,
        "eval_history": eval_history,
        "opening": opening_name,
        "counts": dict(total_counts),
        "result_text": final_result_text,
    }

    phase_accuracy = {
        "white": {
            phase: accuracy_from_move_accuracies(side_stats["white"]["phase"][phase])
            if side_stats["white"]["phase"][phase] else None
            for phase in PHASES
        },
        "black": {
            phase: accuracy_from_move_accuracies(side_stats["black"]["phase"][phase])
            if side_stats["black"]["phase"][phase] else None
            for phase in PHASES
        },
    }

    white_base = game_obj.white_rating or 1200
    black_base = game_obj.black_rating or 1200

    white_rating_est = _estimate_rating(white_accuracy, white_base)
    black_rating_est = _estimate_rating(black_accuracy, black_base)

    analysis_record.white_accuracy = white_accuracy
    analysis_record.black_accuracy = black_accuracy
    analysis_record.white_rating_est = white_rating_est
    analysis_record.black_rating_est = black_rating_est
    
    # Save accurately calculated phase data
    analysis_record.white_opening_acc = phase_accuracy["white"].get("opening")
    analysis_record.white_mid_acc = phase_accuracy["white"].get("middlegame")
    analysis_record.white_end_acc = phase_accuracy["white"].get("endgame")
    analysis_record.black_opening_acc = phase_accuracy["black"].get("opening")
    analysis_record.black_mid_acc = phase_accuracy["black"].get("middlegame")
    analysis_record.black_end_acc = phase_accuracy["black"].get("endgame")

    analysis_record.brilliant_count = int(total_counts["brilliant"])
    analysis_record.great_count = int(total_counts["great"])
    analysis_record.best_count = int(total_counts["best"])
    analysis_record.excellent_count = int(total_counts["excellent"])
    analysis_record.good_count = int(total_counts["good"])
    analysis_record.book_count = int(total_counts["book"])
    analysis_record.inaccuracy_count = int(total_counts["inaccuracy"])
    analysis_record.miss_count = int(total_counts["miss"])
    analysis_record.mistake_count = int(total_counts["mistake"])
    analysis_record.blunder_count = int(total_counts["blunder"])
    analysis_record.result_reason = res_reason or "Normal"
    
    # Save opening info discovered during analysis
    eco_from_pgn = parsed_game.headers.get("ECO", None)
    analysis_record.opening = opening_name if opening_name != "Initial Position" else None
    analysis_record.eco_code = eco_from_pgn
    analysis_record.save()

    # Identify user side and save accuracy to Game model
    username_guess = (user.chess_username or user.username or "").lower()
    user_side = "white"
    user_acc = white_accuracy
    if (game_obj.black_player or "").lower() == username_guess:
        user_side = "black"
        user_acc = black_accuracy
    elif (game_obj.white_player or "").lower() == username_guess:
        user_side = "white"
        user_acc = white_accuracy

    game_obj.accuracy = user_acc
    game_obj.is_analyzed = True
    game_obj.save(update_fields=['accuracy', 'is_analyzed'])

    summary = {
        "players": {
            "white": {
                "name": game_obj.white_player,
                "rating": game_obj.white_rating,
                "accuracy": white_accuracy,
                "rating_estimate": white_rating_est,
                "accuracy_label": _accuracy_label(white_accuracy),
            },
            "black": {
                "name": game_obj.black_player,
                "rating": game_obj.black_rating,
                "accuracy": black_accuracy,
                "rating_estimate": black_rating_est,
                "accuracy_label": _accuracy_label(black_accuracy),
            },
        },
        "user_side": user_side,
        "counts": {
            "white": side_stats["white"]["counts"],
            "black": side_stats["black"]["counts"],
            "total": dict(total_counts),
        },
        "phase_accuracy": phase_accuracy,
        "total_accuracy": round((white_accuracy + black_accuracy) / 2.0, 1),
        "opening_name": opening_name,
    }

    payload = {
        "algo_version": REVIEW_ALGO_VERSION,
        "analysis_id": analysis_record.id,
        "game": {
            "id": game_obj.id,
            "white_player": game_obj.white_player,
            "black_player": game_obj.black_player,
            "white_rating": game_obj.white_rating,
            "black_rating": game_obj.black_rating,
            "result": game_obj.result,
            "date_played": game_obj.date_played.isoformat() if game_obj.date_played else None,
        },
        "start_fen": start_fen,
        "eval_history": eval_history,
        "summary": summary,
        "moves": moves_payload,
    }
    
    analysis_record.full_payload = payload
    analysis_record.save(update_fields=["full_payload"])
    
    return payload, analysis_record


@login_required
def analysis_home(request):
    return render(request, 'analysis/analysis_hub.html')


@login_required
def analysis_paste_pgn(request):
    return render(request, 'analysis/analysis_board.html', {
        'mode': 'pgn',
        'page_title': 'Paste PGN',
        'header_icon': 'clipboard-data-fill',
    })


@login_required
def analysis_setup_position(request):
    return render(request, 'analysis/analysis_board.html', {
        'mode': 'fen',
        'page_title': 'Setup Position',
        'header_icon': 'grid-3x3-gap-fill',
    })


@login_required
def analysis_new_game(request):
    return render(request, 'analysis/analysis_board.html', {
        'mode': 'new',
        'page_title': 'New Game Analysis',
        'header_icon': 'plus-circle-fill',
    })


@login_required
def analysis_dashboard(request, game_id: int):
    game_obj = get_object_or_404(Game, pk=game_id, user=request.user)
    context = {
        "username": request.user.username,
        "game": game_obj,
    }
    return render(request, "analysis/game_review.html", context)


@login_required
@require_POST
@api_error_handler
def run_full_game_review(request):
    body = _json_body(request)
    game_id = body.get("game_id")
    if not game_id:
        return JsonResponse({"error": "game_id is required"}, status=400)

    game_obj = get_object_or_404(Game, pk=game_id, user=request.user)
    if not game_obj.pgn:
        return JsonResponse({"error": "This game has no PGN to analyze"}, status=400)

    # Check if we already have a saved full payload
    existing_record = SavedAnalysis.objects.filter(user=request.user, game=game_obj).order_by("-id").first()
    if (
        existing_record
        and existing_record.full_payload
        and existing_record.full_payload.get("algo_version") == REVIEW_ALGO_VERSION
    ):
        return JsonResponse({"status": "success", **existing_record.full_payload})

    # Priority 0: Manual user-initiated review gets top priority in the queue
    payload, _record = _build_game_review_payload(game_obj, request.user, priority=0)
    return JsonResponse({"status": "success", **payload})


@login_required
@require_POST
@api_error_handler
def analyze_single_position(request):
    try:
        body = _json_body(request)
        fen = (body.get("fen") or "").strip()
        if not fen:
            return JsonResponse({"error": "fen is required"}, status=400)

        depth = body.get("depth")
        multipv = min(int(body.get("multipv") or 1), 3)  # max 3 lines

        manager = StockfishManager()

        if multipv > 1:
            # Multi-PV: get all lines from local engine
            results = manager.get_analysis_multipv(fen, depth=depth, multipv=multipv, priority=0)
            lines = []
            for r in results:
                pv_san = _to_san_line(fen, r.get("pv") or [], max_moves=8)
                lines.append({
                    "evaluation_cp": r.get("evaluation_cp", 0),
                    "evaluation": r.get("evaluation", 0),
                    "best_move": r.get("best_move", ""),
                    "pv": r.get("pv", []),
                    "pv_san": pv_san,
                    "depth": r.get("depth"),
                    "mate": r.get("mate"),
                })
            # Return first line as top-level for backward compatibility
            top = lines[0] if lines else {}
            return JsonResponse({"status": "success", **top, "lines": lines})
        else:
            result = manager.get_analysis(fen, depth=depth, multipv=1, priority=0)
            pv_san = _to_san_line(fen, result.get("pv") or [], max_moves=8)
            return JsonResponse({"status": "success", **result, "pv_san": pv_san, "lines": [{**result, "pv_san": pv_san}]})
    except Exception as e:
        import traceback
        trace=traceback.format_exc()
        return JsonResponse({"error": trace}, status=500)


@login_required
@require_POST
@api_error_handler
def analyze_variation(request):
    body = _json_body(request)
    fen = (body.get("fen") or "").strip()
    move_uci = (body.get("move") or "").strip()

    if not fen or not move_uci:
        return JsonResponse({"error": "fen and move are required"}, status=400)

    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            return JsonResponse({"error": "Illegal move for this position"}, status=400)

        move_san = board.san(move)

        manager = StockfishManager()
        side = "white" if board.turn else "black"

        before_eval = manager.get_analysis(fen, multipv=1, priority=0)
        cp_before = int(before_eval.get("evaluation_cp") or 0)
        mate_before = before_eval.get("mate")
        best_move_uci = before_eval.get("best_move") or ""
        best_line = _to_san_line(fen, before_eval.get("pv") or [])

        board.push(move)
        after_fen = board.fen()

        after_eval = manager.get_analysis(after_fen, multipv=1, priority=0)
        cp_after = int(after_eval.get("evaluation_cp") or 0)
        mate_after = after_eval.get("mate")
        follow_line = _to_san_line(after_fen, after_eval.get("pv") or [])

        if side == "white":
            cp_loss = max(0, cp_before - cp_after)
            cp_gain = cp_after - cp_before
            potential_gain = cp_loss
        else:
            cp_loss = max(0, cp_after - cp_before)
            cp_gain = cp_before - cp_after
            potential_gain = cp_loss

        category = classify_move(
            cp_loss=cp_loss,
            cp_gain=cp_gain,
            potential_gain=potential_gain,
            move_uci=move_uci,
            best_move_uci=best_move_uci,
            board_before=chess.Board(fen),
            cp_before=cp_before,
            cp_after=cp_after,
            side=side,
            mate_before=mate_before,
            mate_after=mate_after,
        )

        best_san = "(none)"
        if best_move_uci:
            try:
                test_board = chess.Board(fen)
                bm = chess.Move.from_uci(best_move_uci)
                if bm in test_board.legal_moves:
                    best_san = test_board.san(bm)
            except ValueError:
                pass

        explanation = _build_move_explanation(
            category=category,
            move_san=move_san,
            best_san=best_san,
            cp_loss=cp_loss,
            phase=_phase_for_position(chess.Board(fen), 30),
        )

        return JsonResponse(
            {
                "status": "success",
                "side": side,
                "after_fen": after_fen,
                "evaluation_cp": cp_after,
                "evaluation": round(cp_after / 100.0, 2),
                "mate": mate_after,
                "mate_before": mate_before,
                "best_move": best_move_uci,
                "best_line": best_line,
                "follow_line": follow_line,
                "classification": category,
                "is_best": bool(best_move_uci and move_uci == best_move_uci),
                "centipawn_loss": cp_loss,
                "explanation": explanation,
            }
        )
    except ValueError:
        return JsonResponse({"error": "Invalid move format"}, status=400)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@require_GET
@api_error_handler
def latest_saved_review(request, game_id: int):
    game_obj = get_object_or_404(Game, pk=game_id, user=request.user)
    record = SavedAnalysis.objects.filter(user=request.user, pgn_data=game_obj.pgn or "").order_by("-id").first()
    if not record:
        return JsonResponse({"status": "empty"})

    if record.full_payload:
        return JsonResponse({"status": "success", **record.full_payload})

    # Use the game model's PGN to reconstruct headers if they aren't saved
    final_result_text = game_obj.result
    try:
        if game_obj.pgn:
            import io
            import chess.pgn
            parsed = chess.pgn.read_game(io.StringIO(game_obj.pgn))
            if parsed:
                res_code = parsed.headers.get("Result", "*")
                termination = record.result_reason or parsed.headers.get("Termination", "Normal")
                white_name = parsed.headers.get("White", "White")
                black_name = parsed.headers.get("Black", "Black")
                
                winner = None
                if res_code == "1-0": winner = white_name
                elif res_code == "0-1": winner = black_name
                
                if winner:
                    final_result_text = f"{winner} won by {termination.lower()}"
                elif res_code == "1/2-1/2":
                    final_result_text = f"Draw by {termination.lower()}"
                
                final_result_text = final_result_text.replace("by time forfeit", "by timeout")
    except:
        pass

    return JsonResponse(
        {
            "status": "success",
            "analysis_id": record.id,
            "white_accuracy": record.white_accuracy,
            "black_accuracy": record.black_accuracy,
            "white_rating_est": record.white_rating_est,
            "black_rating_est": record.black_rating_est,
            "counts": {
                "brilliant": record.brilliant_count,
                "great": record.great_count,
                "best": record.best_count,
                "excellent": record.excellent_count,
                "good": record.good_count,
                "book": record.book_count,
                "inaccuracy": record.inaccuracy_count,
                "miss": record.miss_count,
                "mistake": record.mistake_count,
                "blunder": record.blunder_count,
            },
            "result_text": final_result_text,
        }
    )


@login_required
@require_POST
@api_error_handler
def api_analyze_period(request):
    """
    Finds and analyzes up to 20 un-analyzed games for a period (week/month).
    Uses server health check to decide batch size.
    """
    data = _json_body(request)
    period = data.get("period", "week")  # week or month
    chess_username = data.get("username", "").strip()

    if not chess_username:
        return JsonResponse({"error": "No chess username provided"}, status=400)

    now = timezone.now()
    if period == "month":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        # Default: current week
        start_date = now - timedelta(days=7)

    # 1. Find un-analyzed games
    games_to_analyze = Game.objects.filter(
        user=request.user,
        chess_username_at_time__iexact=chess_username,
        is_analyzed=False,
        date_played__gte=start_date
    ).order_by("-date_played")

    if not games_to_analyze.exists():
        return JsonResponse({"status": "no_games", "message": "All games in this period are already analyzed."})

    # 2. Check Server Health to decide limit
    manager = StockfishManager()
    health = manager.get_health()
    active_tasks = health.get("active_tasks", 0)
    
    # User's limit request: 20 max, 10 if busy
    limit = 20 if active_tasks == 0 else 10
    
    selected_games = games_to_analyze[:limit]
    
    # 3. Process the batch
    results = []
    for game in selected_games:
        try:
            # Priority 1: This is an automatic/periodic batch sync
            _build_game_review_payload(game, request.user, priority=1)
            results.append({"id": game.id, "status": "success"})
        except Exception as e:
            results.append({"id": game.id, "status": "error", "message": str(e)})

    return JsonResponse({
        "status": "complete",
        "games_processed": len(results),
        "results": results,
        "server_busy": active_tasks > 0,
        "limit_used": limit
    })


@login_required
def api_engine_health(request):
    """Bridge to check remote engine health from frontend."""
    manager = StockfishManager()
    return JsonResponse(manager.get_health())
