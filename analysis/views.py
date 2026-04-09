from __future__ import annotations

import io
import json
from collections import defaultdict

import chess
import chess.pgn
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from user.models import Game

from .engine import StockfishManager, accuracy_from_losses, classify_move
from .models import MoveAnalysis, SavedAnalysis


CATEGORIES = [
    "brilliant",
    "great",
    "best",
    "excellent",
    "good",
    "inaccuracy",
    "miss",
    "mistake",
    "blunder",
]

PHASES = ["opening", "middlegame", "endgame"]


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
    return f"{move_san} is a blunder. {best_san} was critical to avoid a major swing."


def _empty_side_stats():
    return {
        "losses": [],
        "counts": {key: 0 for key in CATEGORIES},
        "phase": {name: [] for name in PHASES},
    }


def _parse_pgn_or_raise(pgn_text: str):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        raise ValueError("Invalid PGN data")
    return game


def _build_game_review_payload(game_obj: Game, user) -> tuple[dict, SavedAnalysis]:
    engine = StockfishManager()
    parsed_game = _parse_pgn_or_raise(game_obj.pgn or "")

    board = parsed_game.board()
    start_fen = board.fen()
    eval_history = []
    moves_payload = []

    side_stats = {
        "white": _empty_side_stats(),
        "black": _empty_side_stats(),
    }

    analysis_record = SavedAnalysis.objects.create(
        user=user,
        pgn_data=game_obj.pgn or "",
    )

    move_rows = []
    mainline_moves = list(parsed_game.mainline_moves())

    for ply_index, move in enumerate(mainline_moves, start=1):
        fen_before = board.fen()
        side = "white" if board.turn else "black"
        phase = _phase_for_position(board, ply_index)

        before_eval = engine.get_analysis(fen_before, multipv=1)
        cp_before = int(before_eval.get("evaluation_cp") or 0)
        best_move_uci = before_eval.get("best_move") or ""
        best_pv_uci = before_eval.get("pv") or []

        move_san = board.san(move)
        move_uci = move.uci()

        after_board = board.copy()
        after_board.push(move)
        fen_after = after_board.fen()

        after_eval = engine.get_analysis(fen_after, multipv=1)
        cp_after = int(after_eval.get("evaluation_cp") or 0)
        follow_pv_uci = after_eval.get("pv") or []

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
            board_before=board,
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

        side_stats[side]["losses"].append(cp_loss)
        side_stats[side]["counts"][category] += 1
        side_stats[side]["phase"][phase].append(cp_loss)

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

    white_accuracy = accuracy_from_losses(side_stats["white"]["losses"])
    black_accuracy = accuracy_from_losses(side_stats["black"]["losses"])

    total_counts = defaultdict(int)
    for side in ("white", "black"):
        for name, value in side_stats[side]["counts"].items():
            total_counts[name] += value

    phase_accuracy = {
        "white": {
            phase: accuracy_from_losses(side_stats["white"]["phase"][phase])
            for phase in PHASES
        },
        "black": {
            phase: accuracy_from_losses(side_stats["black"]["phase"][phase])
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
    analysis_record.brilliant_count = int(total_counts["brilliant"])
    analysis_record.great_count = int(total_counts["great"])
    analysis_record.best_count = int(total_counts["best"])
    analysis_record.excelllent_count = int(total_counts["excellent"])
    analysis_record.good_count = int(total_counts["good"])
    analysis_record.inaccuracy_count = int(total_counts["inaccuracy"])
    analysis_record.miss_count = int(total_counts["miss"])
    analysis_record.mistake_count = int(total_counts["mistake"])
    analysis_record.blunder_count = int(total_counts["blunder"])
    analysis_record.save()

    username_guess = (user.chess_username or user.username or "").lower()
    user_side = "white"
    if (game_obj.black_player or "").lower() == username_guess:
        user_side = "black"
    elif (game_obj.white_player or "").lower() == username_guess:
        user_side = "white"

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
    }

    payload = {
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
    return payload, analysis_record


@login_required
def analysis_home(request):
    return redirect('game')


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
def run_full_game_review(request):
    body = _json_body(request)
    game_id = body.get("game_id")
    if not game_id:
        return JsonResponse({"error": "game_id is required"}, status=400)

    game_obj = get_object_or_404(Game, pk=game_id, user=request.user)
    if not game_obj.pgn:
        return JsonResponse({"error": "This game has no PGN to analyze"}, status=400)

    try:
        payload, _record = _build_game_review_payload(game_obj, request.user)
        return JsonResponse({"status": "success", **payload})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@require_POST
def analyze_single_position(request):
    body = _json_body(request)
    fen = (body.get("fen") or "").strip()
    if not fen:
        return JsonResponse({"error": "fen is required"}, status=400)

    depth = body.get("depth")
    try:
        manager = StockfishManager()
        result = manager.get_analysis(fen, depth=depth, multipv=1)
        return JsonResponse({"status": "success", **result})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@require_POST
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

        manager = StockfishManager()
        side = "white" if board.turn else "black"

        before_eval = manager.get_analysis(fen, multipv=1)
        cp_before = int(before_eval.get("evaluation_cp") or 0)
        best_move_uci = before_eval.get("best_move") or ""
        best_line = _to_san_line(fen, before_eval.get("pv") or [])

        move_san = board.san(move)
        board.push(move)
        after_fen = board.fen()

        after_eval = manager.get_analysis(after_fen, multipv=1)
        cp_after = int(after_eval.get("evaluation_cp") or 0)
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
                "best_move": best_move_uci,
                "best_line": best_line,
                "follow_line": follow_line,
                "classification": category,
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
def latest_saved_review(request, game_id: int):
    game_obj = get_object_or_404(Game, pk=game_id, user=request.user)
    record = SavedAnalysis.objects.filter(user=request.user, pgn_data=game_obj.pgn or "").order_by("-id").first()
    if not record:
        return JsonResponse({"status": "empty"})

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
                "excellent": record.excelllent_count,
                "good": record.good_count,
                "inaccuracy": record.inaccuracy_count,
                "miss": record.miss_count,
                "mistake": record.mistake_count,
                "blunder": record.blunder_count,
            },
        }
    )