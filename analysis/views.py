from __future__ import annotations

import io
import json
from collections import defaultdict
from typing import Any

import chess
import chess.pgn
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
from .opening_book import BookHit, OpeningBookResolver
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
REVIEW_ALGO_VERSION = 10


def _json_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _phase_for_position(board: chess.Board, ply_index: int) -> str:
    """Determine game phase from material on the board (pure calculation).
    
    Material values: P=1, N=3, B=3, R=5, Q=9
    Total starting material (excluding kings) = 78 (39 per side)
    """
    piece_values = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
    }
    
    white_material = 0
    black_material = 0
    white_queens = 0
    black_queens = 0
    
    for piece_type, value in piece_values.items():
        white_count = len(board.pieces(piece_type, chess.WHITE))
        black_count = len(board.pieces(piece_type, chess.BLACK))
        white_material += white_count * value
        black_material += black_count * value
        if piece_type == chess.QUEEN:
            white_queens = white_count
            black_queens = black_count
    
    total_material = white_material + black_material
    
    # Endgame: both sides have no queen, or very low material
    if total_material <= 24:
        return "endgame"
    if white_queens == 0 and black_queens == 0 and total_material <= 32:
        return "endgame"
    
    # Opening: most material still on the board and early in the game
    # Opening transitions to middlegame if more than 2 minor pieces are traded
    # OR if we are past move 10 (ply 20)
    if ply_index <= 20 and total_material >= 70:
        return "opening"
    
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

def _is_book_move_heuristic(
    ply_index: int,
    cp_loss: int,
    move_uci: str,
    best_move_uci: str,
    cp_before: int,
    cp_after: int,
) -> bool:
    """Fast local heuristic to detect opening book moves.
    
    A move is considered 'book' when:
    - We are in the first 14 plies (7 full moves)
    - The centipawn loss is negligible (≤ 5)
    - The eval stays close to 0 (both before and after are within ±60 cp)
    - OR the player matched the engine's top move exactly

    This replaces the slow Lichess API which added 16+ seconds of sleep delays.
    """
    if ply_index > 14:
        return False
    # If you match engine's best move in the first 14 plies, it's book-like
    if move_uci and best_move_uci and move_uci == best_move_uci and ply_index <= 14:
        if abs(cp_before) <= 80 and abs(cp_after) <= 80:
            return True
    # Very low cp_loss and balanced position = likely theory
    if cp_loss <= 5 and abs(cp_before) <= 60 and abs(cp_after) <= 60:
        return True
    return False


def _position_complexity(board: chess.Board) -> dict[str, int | bool]:
    legal_moves = list(board.legal_moves)
    captures = 0
    checks = 0
    promotions = 0

    for mv in legal_moves:
        if board.is_capture(mv):
            captures += 1
        if board.gives_check(mv):
            checks += 1
        if mv.promotion:
            promotions += 1

    return {
        "legal_count": len(legal_moves),
        "captures": captures,
        "checks": checks,
        "promotions": promotions,
        "in_check": board.is_check(),
    }


def _adaptive_depth_for_position(base_depth: int, board: chess.Board, ply_index: int) -> int:
    min_depth = int(getattr(settings, "ANALYSIS_REVIEW_MIN_DEPTH", 12))
    max_boost = int(getattr(settings, "ANALYSIS_REVIEW_MAX_DEPTH_BOOST", 3))

    phase = _phase_for_position(board, ply_index)
    complexity = _position_complexity(board)
    legal_count = int(complexity["legal_count"])
    captures = int(complexity["captures"])
    checks = int(complexity["checks"])
    promotions = int(complexity["promotions"])
    in_check = bool(complexity["in_check"])

    forcing_score = captures + checks + promotions + (3 if in_check else 0)
    depth = base_depth

    # Phase-aware baseline
    if phase == "opening":
        depth -= 1
    elif phase == "endgame":
        depth += 1

    # Tactical nodes get deeper search.
    if in_check or forcing_score >= 8 or captures >= 5:
        depth += min(max_boost, 2)
    elif forcing_score >= 4:
        depth += 1

    # Quiet/forced recapture style positions get a shallower pass.
    if (not in_check) and legal_count <= 10 and captures <= 1 and checks == 0:
        depth -= 2

    return max(min_depth, min(base_depth + max_boost, depth))


def _analyze_positions_with_depth_plan(
    engine: StockfishManager,
    fens: list[str],
    depth_plan: list[int],
    multipv: int,
    priority: int,
) -> list[dict[str, Any]]:
    if not fens:
        return []

    grouped_indices: dict[int, list[int]] = defaultdict(list)
    for idx, depth in enumerate(depth_plan):
        grouped_indices[int(depth)].append(idx)

    output: list[dict[str, Any] | None] = [None] * len(fens)
    for depth, indices in grouped_indices.items():
        subset_fens = [fens[i] for i in indices]
        subset_results = engine.analyze_batch(
            subset_fens,
            depth=depth,
            multipv=multipv,
            priority=priority,
        )

        for local_idx, global_idx in enumerate(indices):
            if local_idx < len(subset_results):
                output[global_idx] = subset_results[local_idx]

    fallback_depth = depth_plan[0] if depth_plan else getattr(engine, "default_depth", 16)
    for idx, item in enumerate(output):
        if item is None:
            output[idx] = {
                "evaluation_cp": 0,
                "evaluation": 0.0,
                "best_move": "",
                "pv": [],
                "depth": fallback_depth,
                "mate": None,
                "lines": [],
            }

    return [item for item in output if item is not None]


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


def _build_game_review_payload(
    game_obj,
    user,
    priority=0,
    engine: StockfishManager | None = None,
    engine_version: str | None = None,
) -> tuple[dict, SavedAnalysis]:
    engine = engine or StockfishManager()
    engine_version = engine_version or engine.get_engine_version()
    parsed_game = _parse_pgn_or_raise(game_obj.pgn or "")

    review_depth = int(getattr(settings, "ANALYSIS_GAME_REVIEW_DEPTH", 20))
    review_depth = max(int(getattr(settings, "ANALYSIS_REVIEW_MIN_DEPTH", 12)), review_depth)

    board = parsed_game.board()
    start_fen = board.fen()
    eval_history: list[float] = []
    moves_payload: list[dict[str, Any]] = []

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
        review_algo_version=REVIEW_ALGO_VERSION,
        analysis_engine_version=engine_version,
    )

    move_rows = []
    mainline_moves = list(parsed_game.mainline_moves())
    book_resolver = OpeningBookResolver(headers=parsed_game.headers)

    # Remote engine needs conservative defaults to avoid queue timeout on long games.
    if engine.mode == "remote":
        remote_max_depth = int(getattr(settings, "ANALYSIS_REVIEW_REMOTE_MAX_DEPTH", 14))
        longgame_depth = int(getattr(settings, "ANALYSIS_REVIEW_REMOTE_LONGGAME_DEPTH", 12))
        review_depth = min(review_depth, remote_max_depth)
        if len(mainline_moves) >= 120:
            review_depth = min(review_depth, longgame_depth)

    all_fens = [start_fen]
    all_boards = [parsed_game.board()]
    temp_board = parsed_game.board()
    for move in mainline_moves:
        temp_board.push(move)
        all_fens.append(temp_board.fen())
        all_boards.append(temp_board.copy())

    adaptive_enabled = bool(getattr(settings, "ANALYSIS_ADAPTIVE_DEPTH", True))
    if engine.mode == "remote":
        adaptive_enabled = bool(getattr(settings, "ANALYSIS_ADAPTIVE_DEPTH_REMOTE", False))

    review_multipv = int(getattr(settings, "ANALYSIS_REVIEW_MULTIPV", 3 if engine.mode != "remote" else 1))
    review_multipv = max(1, min(3, review_multipv))
    if engine.mode == "remote":
        review_multipv = max(
            1,
            min(3, int(getattr(settings, "ANALYSIS_REVIEW_REMOTE_MULTIPV", review_multipv))),
        )
    if engine.mode == "remote" and review_multipv > 1 and not engine.supports_batch_multipv():
        review_multipv = 1

    if adaptive_enabled:
        depth_plan = [
            _adaptive_depth_for_position(review_depth, fen_board, idx + 1)
            for idx, fen_board in enumerate(all_boards)
        ]
    else:
        depth_plan = [review_depth] * len(all_fens)

    print(
        f"Batch analyzing {len(all_fens)} positions with priority {priority} "
        f"(depth range: {min(depth_plan)}-{max(depth_plan)}, multipv={review_multipv})..."
    )
    batch_results = _analyze_positions_with_depth_plan(
        engine=engine,
        fens=all_fens,
        depth_plan=depth_plan,
        multipv=review_multipv,
        priority=priority,
    )

    move_history_uci: list[str] = []
    strongest_book_hit: BookHit | None = None

    for ply_index, move in enumerate(mainline_moves, start=1):
        fen_before = board.fen()
        side = "white" if board.turn else "black"
        phase = _phase_for_position(board, ply_index)

        move_san = board.san(move)
        move_uci = move.uci()

        before_eval: dict[str, Any] = {
            "evaluation_cp": 0,
            "evaluation": 0.0,
            "best_move": "",
            "pv": [],
            "depth": review_depth,
            "mate": None,
            "lines": [],
        }
        if ply_index - 1 < len(batch_results):
            before_eval = batch_results[ply_index - 1] or before_eval

        before_lines = [item for item in (before_eval.get("lines") or []) if isinstance(item, dict)]
        if not before_lines:
            before_lines = [before_eval]

        top_before = before_lines[0]
        second_before = before_lines[1] if len(before_lines) > 1 else None

        cp_before = int(top_before.get("evaluation_cp") or before_eval.get("evaluation_cp") or 0)
        best_move_uci = top_before.get("best_move") or before_eval.get("best_move") or ""
        best_pv_uci = top_before.get("pv") or before_eval.get("pv") or []
        second_best_move_uci = (second_before.get("best_move") if second_before else "") or ""
        second_best_cp = int(second_before.get("evaluation_cp") or 0) if second_before else None
        second_best_pv = (second_before.get("pv") if second_before else []) or []

        move_rank = None
        for idx_line, line in enumerate(before_lines, start=1):
            if (line.get("best_move") or "").strip() == move_uci:
                move_rank = idx_line
                break

        after_board = board.copy()
        after_board.push(move)
        fen_after = after_board.fen()

        after_eval: dict[str, Any] = {
            "evaluation_cp": cp_before,
            "evaluation": round(cp_before / 100.0, 2),
            "best_move": "",
            "pv": [],
            "depth": review_depth,
            "mate": None,
            "lines": [],
        }
        if ply_index < len(batch_results):
            after_eval = batch_results[ply_index] or after_eval

        after_lines = [item for item in (after_eval.get("lines") or []) if isinstance(item, dict)]
        if not after_lines:
            after_lines = [after_eval]
        top_after = after_lines[0]

        cp_after = int(top_after.get("evaluation_cp") or after_eval.get("evaluation_cp") or cp_before)
        follow_pv_uci = top_after.get("pv") or after_eval.get("pv") or []
        mate_before = top_before.get("mate", before_eval.get("mate"))
        mate_after = top_after.get("mate", after_eval.get("mate"))

        if side == "white":
            cp_loss = max(0, cp_before - cp_after)
            cp_gain = cp_after - cp_before
            potential_gain = cp_loss
        else:
            cp_loss = max(0, cp_after - cp_before)
            cp_gain = cp_before - cp_after
            potential_gain = cp_loss

        book_hit = book_resolver.detect_move(
            board_before=board,
            move_uci=move_uci,
            move_history_uci=move_history_uci,
            ply_index=ply_index,
            cp_loss=cp_loss,
            cp_before=cp_before,
            cp_after=cp_after,
            best_move_uci=best_move_uci,
            top_candidate_moves=[line.get("best_move") or "" for line in before_lines[:3]],
        )
        if book_hit.is_book and (
            strongest_book_hit is None or book_hit.confidence > strongest_book_hit.confidence
        ):
            strongest_book_hit = book_hit

        category = classify_move(
            cp_loss=cp_loss,
            cp_gain=cp_gain,
            potential_gain=potential_gain,
            move_uci=move_uci,
            best_move_uci=best_move_uci,
            board_before=board,
            second_best_move_uci=second_best_move_uci,
            second_best_cp=second_best_cp,
            move_rank=move_rank,
            best_pv=best_pv_uci,
            follow_pv=follow_pv_uci,
            is_book=book_hit.is_book,
            cp_before=cp_before,
            cp_after=cp_after,
            side=side,
            mate_before=mate_before,
            mate_after=mate_after,
            best_mate=top_before.get("mate"),
            second_best_mate=(second_before.get("mate") if second_before else None),
        )

        # Book moves do not count towards accuracy loss.
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
            cp_before=cp_before,
            cp_after=cp_after,
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
        if category == "book" and book_hit.source not in {"none", "heuristic"}:
            explanation = f"{move_san} follows {book_hit.source.replace('_', ' ')} opening theory."

        best_line_san = _to_san_line(fen_before, best_pv_uci)
        second_line_san = _to_san_line(fen_before, second_best_pv)
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
                "second_best_move": second_best_move_uci or None,
                "move_rank": move_rank,
                "best_move_san": best_san,
                "best_line": best_line_san,
                "second_best_line": second_line_san,
                "follow_line": follow_line_san,
                "book_source": book_hit.source if category == "book" else None,
                "book_confidence": book_hit.confidence if category == "book" else None,
                "engine_depth_used": int(top_before.get("depth") or before_eval.get("depth") or review_depth),
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
        move_history_uci.append(move_uci)
        board.push(move)

    if move_rows:
        MoveAnalysis.objects.bulk_create(move_rows)

    white_accuracy = accuracy_from_move_accuracies(side_stats["white"]["move_accuracies"])
    black_accuracy = accuracy_from_move_accuracies(side_stats["black"]["move_accuracies"])

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

    res_reason = termination
    if termination.lower() == "normal":
        if board.is_checkmate():
            res_reason = "Checkmate"
        elif board.is_stalemate():
            res_reason = "Stalemate"
        elif board.is_insufficient_material():
            res_reason = "Insufficient Material"
        else:
            res_reason = "Normal"

    if winner_name:
        final_result_text = f"{winner_name} won by {res_reason.lower()}"
    elif result == "1/2-1/2":
        final_result_text = f"Draw by {res_reason.lower()}"
    else:
        final_result_text = f"Game ended: {result}"
    final_result_text = final_result_text.replace("by time forfeit", "by timeout")

    total_counts = defaultdict(int)
    for side in ("white", "black"):
        for name, value in side_stats[side]["counts"].items():
            total_counts[name] += value

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

    opening_meta = book_resolver.resolve_opening_metadata(strongest_book_hit)
    book_resolver.close()
    opening_name = opening_meta.get("opening") or parsed_game.headers.get("Opening") or "Initial Position"
    eco_code = opening_meta.get("eco_code") or parsed_game.headers.get("ECO")

    analysis_record.white_accuracy = white_accuracy
    analysis_record.black_accuracy = black_accuracy
    analysis_record.white_rating_est = white_rating_est
    analysis_record.black_rating_est = black_rating_est
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
    analysis_record.opening = opening_name if opening_name != "Initial Position" else None
    analysis_record.eco_code = eco_code
    analysis_record.opening_source = opening_meta.get("opening_source")
    analysis_record.opening_confidence = opening_meta.get("opening_confidence")
    analysis_record.review_algo_version = REVIEW_ALGO_VERSION
    analysis_record.analysis_engine_version = engine_version
    analysis_record.save()

    username_guess = (game_obj.chess_username_at_time or user.chess_username or user.username or "").lower()
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
    game_obj.save(update_fields=["accuracy", "is_analyzed"])

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
        "opening_source": analysis_record.opening_source,
        "opening_confidence": analysis_record.opening_confidence,
        "result_text": final_result_text,
    }

    payload = {
        "algo_version": REVIEW_ALGO_VERSION,
        "review_algo_version": REVIEW_ALGO_VERSION,
        "analysis_engine_version": engine_version,
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

    manager = StockfishManager()
    current_engine_version = manager.get_engine_version()

    # Reuse cache when review algo matches; optionally require strict engine-version match.
    existing_record = SavedAnalysis.objects.filter(user=request.user, game=game_obj).order_by("-id").first()
    if existing_record and existing_record.full_payload:
        payload_versions = existing_record.full_payload
        saved_algo_version = (
            existing_record.review_algo_version
            or payload_versions.get("review_algo_version")
            or payload_versions.get("algo_version")
            or 0
        )
        saved_engine_version = (
            existing_record.analysis_engine_version
            or payload_versions.get("analysis_engine_version")
            or ""
        )

        try:
            saved_algo_version_int = int(saved_algo_version)
        except (TypeError, ValueError):
            saved_algo_version_int = 0

        strict_engine_cache = bool(getattr(settings, "ANALYSIS_STRICT_ENGINE_VERSION_CACHE", False))
        if saved_algo_version_int == REVIEW_ALGO_VERSION:
            if not strict_engine_cache:
                return JsonResponse({"status": "success", **existing_record.full_payload})

            same_engine = str(saved_engine_version) == str(current_engine_version)
            unknown_engine = (
                "unknown" in str(saved_engine_version).lower()
                or "unknown" in str(current_engine_version).lower()
            )
            if same_engine or unknown_engine:
                return JsonResponse({"status": "success", **existing_record.full_payload})

    # Priority 0: Manual user-initiated review gets top priority in the queue
    try:
        payload, _record = _build_game_review_payload(
            game_obj,
            request.user,
            priority=0,
            engine=manager,
            engine_version=current_engine_version,
        )
        return JsonResponse({"status": "success", **payload})
    except Exception as exc:
        msg = str(exc)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            return JsonResponse(
                {
                    "error": "Analysis engine timeout. The server is busy; please retry in 30-60 seconds.",
                    "details": msg,
                },
                status=504,
            )
        return JsonResponse(
            {
                "error": "Game analysis failed. Please retry.",
                "details": msg,
            },
            status=502,
        )


@login_required
@require_POST
@api_error_handler
def analyze_single_position(request):
    try:
        body = _json_body(request)
        fen = (body.get("fen") or "").strip()
        if not fen:
            return JsonResponse({"error": "fen is required"}, status=400)

        # 1. Server-side FEN validation
        try:
            board = chess.Board(fen)
            # board.status() checks for typical illegalities (king counts, etc.)
            status = board.status()
            if status != chess.STATUS_VALID:
                if status & (chess.STATUS_NO_WHITE_KING | chess.STATUS_NO_BLACK_KING):
                    return JsonResponse({"error": "Invalid position: Both players must have a King."}, status=400)
                if status & chess.STATUS_OPPOSITE_CHECK:
                    return JsonResponse({"error": "Invalid position: Opponent King is in check (impossible state)."}, status=400)
                # Generic fallback for other status errors
                return JsonResponse({"error": "Invalid board position."}, status=400)
        except (ValueError, IndexError):
            return JsonResponse({"error": "Invalid FEN string. Please check the format."}, status=400)

        depth = body.get("depth")
        multipv = min(int(body.get("multipv") or 1), 3)  # max 3 lines

        manager = StockfishManager()

        try:
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
                # Maintain exact same JSON structure as original success
                return JsonResponse({"status": "success", **result, "pv_san": pv_san, "lines": [{**result, "pv_san": pv_san}]})
        except Exception as engine_err:
            # Catch engine-specific errors (timeouts, remote failures) and return as clean JSON
            return JsonResponse({"error": f"Analysis engine error: {str(engine_err)}"}, status=502)

    except Exception:
        return JsonResponse({"error": "An internal error occurred during analysis."}, status=500)


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

        before_lines = manager.get_analysis_multipv(fen, multipv=3, priority=0)
        before_eval = before_lines[0] if before_lines else {}
        second_eval = before_lines[1] if len(before_lines) > 1 else {}

        cp_before = int(before_eval.get("evaluation_cp") or 0)
        mate_before = before_eval.get("mate")
        best_move_uci = before_eval.get("best_move") or ""
        best_line = _to_san_line(fen, before_eval.get("pv") or [])
        second_best_move_uci = second_eval.get("best_move") or ""
        second_best_cp = int(second_eval.get("evaluation_cp") or 0) if second_eval else None

        move_rank = None
        for idx, line in enumerate(before_lines, start=1):
            if (line.get("best_move") or "") == move_uci:
                move_rank = idx
                break

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
            second_best_move_uci=second_best_move_uci,
            second_best_cp=second_best_cp,
            move_rank=move_rank,
            best_pv=before_eval.get("pv") or [],
            follow_pv=after_eval.get("pv") or [],
            cp_before=cp_before,
            cp_after=cp_after,
            side=side,
            mate_before=mate_before,
            mate_after=mate_after,
            best_mate=before_eval.get("mate"),
            second_best_mate=second_eval.get("mate") if second_eval else None,
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
            "review_algo_version": record.review_algo_version,
            "analysis_engine_version": record.analysis_engine_version,
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

    # Exclude bullet time controls from bulk analysis here to match Insights behavior
    games_to_analyze = games_to_analyze.exclude(
        time_control__in=['60', '60+1', '60+2', '30', '120', '120+1']
    )

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
