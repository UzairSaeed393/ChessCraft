from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from typing import Any

import chess
import chess.engine
import requests
from django.conf import settings


MATE_CP = 100000


@dataclass
class EngineResult:
    cp: int
    evaluation: float
    best_move: str
    pv: list[str]
    depth: int
    mate: int | None = None


class StockfishManager:
    """Engine adapter: remote API first (Azure), local binary fallback."""

    def __init__(self) -> None:
        self.remote_url = getattr(settings, "ANALYSIS_ENGINE_URL", "").strip()
        self.remote_token = getattr(settings, "ANALYSIS_ENGINE_TOKEN", "").strip()
        self.remote_timeout = int(getattr(settings, "ANALYSIS_ENGINE_TIMEOUT", 25))

        explicit_mode = getattr(settings, "ANALYSIS_ENGINE_MODE", "").strip().lower()
        if explicit_mode in {"remote", "local"}:
            self.mode = explicit_mode
        else:
            self.mode = "remote" if self.remote_url else "local"

        default_local = (
            r"D:\Web development\Stockfish\stockfish-windows-x86-64-avx2.exe"
            if platform.system() == "Windows"
            else "/usr/games/stockfish"
        )
        self.local_path = getattr(settings, "STOCKFISH_PATH", default_local)
        self.local_threads = int(getattr(settings, "ANALYSIS_ENGINE_THREADS", 1))
        self.local_hash = int(getattr(settings, "ANALYSIS_ENGINE_HASH", 32))
        self.default_depth = int(getattr(settings, "ANALYSIS_ENGINE_DEPTH", 14))
        self.default_time = float(getattr(settings, "ANALYSIS_ENGINE_TIME", 0.18))

    def get_analysis(self, fen: str, depth: int | None = None, multipv: int = 1) -> dict[str, Any]:
        """Return a normalized engine payload for UI and review pipelines."""
        if not fen:
            raise ValueError("FEN is required")

        target_depth = depth or self.default_depth

        if self.mode == "remote":
            result = self._analyze_remote(fen, target_depth, multipv)
        else:
            result = self._analyze_local(fen, target_depth, multipv)

        return {
            "evaluation_cp": result.cp,
            "evaluation": result.evaluation,
            "best_move": result.best_move,
            "pv": result.pv,
            "depth": result.depth,
            "mate": result.mate,
        }

    def _analyze_remote(self, fen: str, depth: int, multipv: int) -> EngineResult:
        if not self.remote_url:
            raise RuntimeError("ANALYSIS_ENGINE_URL is not configured for remote mode")

        headers = {"Content-Type": "application/json"}
        if self.remote_token:
            headers["Authorization"] = f"Bearer {self.remote_token}"

        payload = {
            "fen": fen,
            "depth": depth,
            "multipv": multipv,
        }
        response = requests.post(
            self.remote_url,
            json=payload,
            headers=headers,
            timeout=self.remote_timeout,
        )
        response.raise_for_status()
        body = response.json()

        cp = body.get("evaluation_cp")
        mate = body.get("mate")
        if cp is None:
            raw_eval = body.get("evaluation")
            if raw_eval is not None:
                cp = int(float(raw_eval) * 100)
            elif mate is not None:
                cp = MATE_CP if int(mate) > 0 else -MATE_CP
            else:
                cp = 0

        best_move = (body.get("best_move") or "").strip()
        pv = body.get("pv") or body.get("principal_variation") or []
        if isinstance(pv, str):
            pv = [item for item in pv.split() if item]

        if best_move and (not pv or pv[0] != best_move):
            pv = [best_move, *pv]

        result_depth = int(body.get("depth") or depth)
        return EngineResult(
            cp=int(cp),
            evaluation=round(int(cp) / 100.0, 2),
            best_move=best_move,
            pv=pv,
            depth=result_depth,
            mate=(int(mate) if mate is not None else None),
        )

    def _analyze_local(self, fen: str, depth: int, multipv: int) -> EngineResult:
        if not os.path.exists(self.local_path):
            raise RuntimeError(
                f"Stockfish binary not found at '{self.local_path}'. "
                "Set ANALYSIS_ENGINE_URL for Azure or STOCKFISH_PATH for local mode."
            )

        board = chess.Board(fen)
        engine = chess.engine.SimpleEngine.popen_uci(self.local_path)
        try:
            engine.configure({"Threads": self.local_threads, "Hash": self.local_hash})
            info = engine.analyse(
                board,
                chess.engine.Limit(depth=depth, time=self.default_time),
                multipv=max(1, multipv),
            )
            top = info[0] if isinstance(info, list) else info
            score = top.get("score")
            pv_moves = top.get("pv") or []
            cp = 0
            mate = None
            if score is not None:
                cp = score.pov(chess.WHITE).score(mate_score=MATE_CP) or 0
                mate = score.pov(chess.WHITE).mate()

            best_move = pv_moves[0].uci() if pv_moves else ""
            pv = [mv.uci() for mv in pv_moves]

            return EngineResult(
                cp=int(cp),
                evaluation=round(int(cp) / 100.0, 2),
                best_move=best_move,
                pv=pv,
                depth=depth,
                mate=mate,
            )
        finally:
            engine.quit()


def material_points(board: chess.Board, color: chess.Color) -> int:
    values = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
    }
    total = 0
    for piece_type, value in values.items():
        total += len(board.pieces(piece_type, color)) * value
    return total


def is_sacrifice_move(board_before: chess.Board, move: chess.Move) -> bool:
    """Heuristic: move is a sacrifice if material drops after a non-forced capture move."""
    if move not in board_before.legal_moves:
        return False
    before_points = material_points(board_before, board_before.turn)
    test_board = board_before.copy()
    test_board.push(move)
    after_points = material_points(test_board, not test_board.turn)
    return (before_points - after_points) >= 2


def classify_move(
    cp_loss: int,
    cp_gain: int,
    potential_gain: int,
    move_uci: str,
    best_move_uci: str,
    board_before: chess.Board,
) -> str:
    move_uci = (move_uci or "").strip()
    best_move_uci = (best_move_uci or "").strip()
    is_best = move_uci and move_uci == best_move_uci

    if is_best and cp_loss <= 20:
        try:
            if is_sacrifice_move(board_before, chess.Move.from_uci(move_uci)):
                return "brilliant"
        except ValueError:
            pass

    if is_best and cp_loss <= 8:
        return "best"
    if cp_loss <= 20:
        return "excellent"
    if cp_loss <= 45:
        return "great"
    if cp_loss <= 90:
        return "good"
    if potential_gain >= 180 and cp_loss >= 130:
        return "miss"
    if cp_loss <= 170:
        return "inaccuracy"
    if cp_loss <= 280:
        return "mistake"
    return "blunder"


def accuracy_from_losses(losses: list[int]) -> float:
    if not losses:
        return 100.0
    avg_loss = sum(losses) / len(losses)
    accuracy = 100.0 - (avg_loss * 0.11)
    return round(max(0.0, min(100.0, accuracy)), 1)