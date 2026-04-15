from __future__ import annotations
import math
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
        self.default_depth = int(getattr(settings, "ANALYSIS_ENGINE_DEPTH", 16))
        self.default_time = float(getattr(settings, "ANALYSIS_ENGINE_TIME", 0.18))

    def get_health(self) -> dict[str, Any]:
        """Check if the remote engine is busy."""
        if self.mode != "remote" or not self.remote_url:
            return {"status": "ok", "active_tasks": 0, "mode": self.mode}
        
        health_url = self.remote_url.replace("/analyze", "/health")
        try:
            response = requests.get(health_url, timeout=5)
            if response.ok:
                return response.json()
        except:
            pass
        return {"status": "unknown", "active_tasks": 0}

    def get_analysis(self, fen: str, depth: int | None = None, multipv: int = 1, elo_limit: int | None = None, priority: int = 1) -> dict[str, Any]:
        """Return a normalized engine payload for UI and review pipelines."""
        if not fen:
            raise ValueError("FEN is required")

        target_depth = depth or self.default_depth

        if self.mode == "remote":
            result = self._analyze_remote(fen, target_depth, multipv, elo_limit, priority=priority)
        else:
            result = self._analyze_local(fen, target_depth, multipv, elo_limit)

        return {
            "evaluation_cp": result.cp,
            "evaluation": result.evaluation,
            "best_move": result.best_move,
            "pv": result.pv,
            "depth": result.depth,
            "mate": result.mate,
        }

    def analyze_batch(self, fens: list[str], depth: int | None = None, multipv: int = 1, priority: int = 1) -> list[dict[str, Any]]:
        target_depth = depth or self.default_depth

        if self.mode == "remote":
            results = self._analyze_batch_remote(fens, target_depth, multipv, priority=priority)
        else:
            results = self._analyze_batch_local(fens, target_depth, multipv)

        output = []
        for result in results:
            output.append({
                "evaluation_cp": result.cp,
                "evaluation": result.evaluation,
                "best_move": result.best_move,
                "pv": result.pv,
                "depth": result.depth,
                "mate": result.mate,
            })
        return output

    def _analyze_remote(self, fen: str, depth: int, multipv: int, elo_limit: int | None = None, priority: int = 1) -> EngineResult:
        if not self.remote_url:
            raise RuntimeError("ANALYSIS_ENGINE_URL is not configured for remote mode")

        headers = {"Content-Type": "application/json"}
        if self.remote_token:
            headers["Authorization"] = f"Bearer {self.remote_token}"
        headers["x-priority"] = str(priority)

        payload = {
            "fen": fen,
            "depth": depth,
            "multipv": multipv,
        }
        if elo_limit:
            payload["elo"] = elo_limit
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

    def get_analysis_multipv(self, fen: str, depth: int | None = None, multipv: int = 3, elo_limit: int | None = None, priority: int = 1) -> list[dict[str, Any]]:
        """Return a normalized array of engine payloads for multi-PV."""
        if not fen:
            raise ValueError("FEN is required")

        target_depth = depth or self.default_depth

        if self.mode == "remote":
            results = self._analyze_remote_multipv(fen, target_depth, multipv, elo_limit, priority)
        else:
            results = self._analyze_local_multipv(fen, target_depth, multipv, elo_limit)

        output = []
        for result in results:
            output.append({
                "evaluation_cp": result.cp,
                "evaluation": result.evaluation,
                "best_move": result.best_move,
                "pv": result.pv,
                "depth": result.depth,
                "mate": result.mate,
            })
        return output

    def _analyze_remote_multipv(self, fen: str, depth: int, multipv: int, elo_limit: int | None = None, priority: int = 1) -> list[EngineResult]:
        if not self.remote_url:
            raise RuntimeError("ANALYSIS_ENGINE_URL is not configured for remote mode")

        headers = {"Content-Type": "application/json"}
        if self.remote_token:
            headers["Authorization"] = f"Bearer {self.remote_token}"
        headers["x-priority"] = str(priority)

        payload = {
            "fen": fen,
            "depth": depth,
            "multipv": multipv,
        }
        if elo_limit:
            payload["elo"] = elo_limit
            
        response = requests.post(
            self.remote_url,
            json=payload,
            headers=headers,
            timeout=self.remote_timeout,
        )
        response.raise_for_status()
        body = response.json()

        # Check if the server responds with an array of "lines"
        lines_data = body.get("lines")
        # If not, create a fallback single list from the top-level keys
        if not lines_data:
            lines_data = [body]

        results = []
        for line_data in lines_data:
            cp = line_data.get("evaluation_cp")
            mate = line_data.get("mate")
            if cp is None:
                raw_eval = line_data.get("evaluation")
                if raw_eval is not None:
                    cp = int(float(raw_eval) * 100)
                elif mate is not None:
                    cp = MATE_CP if int(mate) > 0 else -MATE_CP
                else:
                    cp = 0

            best_move = (line_data.get("best_move") or "").strip()
            pv = line_data.get("pv") or line_data.get("principal_variation") or []
            if isinstance(pv, str):
                pv = [item for item in pv.split() if item]

            if best_move and (not pv or pv[0] != best_move):
                pv = [best_move, *pv]

            result_depth = int(line_data.get("depth") or depth)
            
            results.append(EngineResult(
                cp=int(cp),
                evaluation=round(int(cp) / 100.0, 2),
                best_move=best_move,
                pv=pv,
                depth=result_depth,
                mate=(int(mate) if mate is not None else None),
            ))
            
        return results

    def _analyze_local_multipv(self, fen: str, depth: int, multipv: int, elo_limit: int | None = None) -> list[EngineResult]:
        if not os.path.exists(self.local_path):
            raise RuntimeError(
                f"Stockfish binary not found at '{self.local_path}'. "
                "Set ANALYSIS_ENGINE_URL for Azure or STOCKFISH_PATH for local mode."
            )

        board = chess.Board(fen)
        engine = chess.engine.SimpleEngine.popen_uci(self.local_path)
        try:
            config = {"Threads": self.local_threads, "Hash": self.local_hash}
            if elo_limit:
                config["UCI_LimitStrength"] = True
                config["UCI_Elo"] = max(1320, min(elo_limit, 3190))

            engine.configure(config)

            time_limit = 0.5 if elo_limit else self.default_time
            info = engine.analyse(
                board,
                chess.engine.Limit(depth=depth, time=time_limit),
                multipv=max(1, multipv),
            )
            
            # info is a list if multipv > 1 and list is not empty, else a dict
            if not isinstance(info, list):
                info = [info]
                
            results = []
            for i in info:
                score = i.get("score")
                pv_moves = i.get("pv") or []
                cp = 0
                mate = None
                if score is not None:
                    cp = score.pov(chess.WHITE).score(mate_score=MATE_CP) or 0
                    mate = score.pov(chess.WHITE).mate()

                best_move = pv_moves[0].uci() if pv_moves else ""
                pv = [mv.uci() for mv in pv_moves]

                results.append(EngineResult(
                    cp=int(cp),
                    evaluation=round(int(cp) / 100.0, 2),
                    best_move=best_move,
                    pv=pv,
                    depth=depth,
                    mate=mate,
                ))
            return results
        finally:
            engine.quit()

    def _analyze_local(self, fen: str, depth: int, multipv: int, elo_limit: int | None = None) -> EngineResult:
        if not os.path.exists(self.local_path):
            raise RuntimeError(
                f"Stockfish binary not found at '{self.local_path}'. "
                "Set ANALYSIS_ENGINE_URL for Azure or STOCKFISH_PATH for local mode."
            )

        board = chess.Board(fen)
        engine = chess.engine.SimpleEngine.popen_uci(self.local_path)
        try:
            config = {"Threads": self.local_threads, "Hash": self.local_hash}
            if elo_limit:
                config["UCI_LimitStrength"] = True
                config["UCI_Elo"] = max(1320, min(elo_limit, 3190)) # UCI_Elo valid range is roughly 1320 to 3190
            
            engine.configure(config)
            
            # Use smaller time limits in play mode so AI responds snappily
            time_limit = 0.5 if elo_limit else self.default_time
            info = engine.analyse(
                board,
                chess.engine.Limit(depth=depth, time=time_limit),
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

    def _analyze_batch_remote(self, fens: list[str], depth: int, multipv: int, priority: int = 1) -> list[EngineResult]:
        if not self.remote_url:
            raise RuntimeError("ANALYSIS_ENGINE_URL is not configured for remote mode")

        # Automatically deduce the batch URL
        batch_url = self.remote_url.replace("/analyze", "/analyze_batch")
        
        headers = {"Content-Type": "application/json"}
        if self.remote_token:
            headers["Authorization"] = f"Bearer {self.remote_token}"
        headers["x-priority"] = str(priority)

        # Increased timeout because batch analysis for a whole game takes ~5-15 seconds
        response = requests.post(
            batch_url,
            json={"fens": fens, "depth": depth, "multipv": multipv},
            headers=headers,
            timeout=180,
        )
        response.raise_for_status()
        
        output = []
        for body in response.json():
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
            pv = body.get("pv") or []
            if isinstance(pv, str):
                pv = [item for item in pv.split() if item]

            if best_move and (not pv or pv[0] != best_move):
                pv = [best_move, *pv]

            result_depth = int(body.get("depth") or depth)
            output.append(EngineResult(
                cp=int(cp),
                evaluation=round(int(cp) / 100.0, 2),
                best_move=best_move,
                pv=pv,
                depth=result_depth,
                mate=(int(mate) if mate is not None else None),
            ))
        return output

    def _analyze_batch_local(self, fens: list[str], depth: int, multipv: int) -> list[EngineResult]:
        if not os.path.exists(self.local_path):
            raise RuntimeError(f"Stockfish binary not found at '{self.local_path}'")

        engine = chess.engine.SimpleEngine.popen_uci(self.local_path)
        try:
            config = {"Threads": self.local_threads, "Hash": self.local_hash}
            engine.configure(config)
            
            output = []
            for fen in fens:
                try:
                    board = chess.Board(fen)
                except ValueError:
                    continue
                
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

                output.append(EngineResult(
                    cp=int(cp),
                    evaluation=round(int(cp) / 100.0, 2),
                    best_move=best_move,
                    pv=pv,
                    depth=depth,
                    mate=mate,
                ))
            return output
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
    is_book: bool = False,
    cp_before: int | None = None,
    cp_after: int | None = None,
    side: str | None = None,
    mate_before: int | None = None,
    mate_after: int | None = None,
) -> str:
    if is_book:
        return "book"

    move_uci = (move_uci or "").strip()
    best_move_uci = (best_move_uci or "").strip()
    is_best = move_uci and move_uci == best_move_uci

    cp_before_pov = 0
    cp_after_pov = 0
    if cp_before is not None and cp_after is not None:
        if side == "black":
            cp_before_pov = -int(cp_before)
            cp_after_pov = -int(cp_after)
        else:
            cp_before_pov = int(cp_before)
            cp_after_pov = int(cp_after)

    # Deterministic rule: exact engine move is always Best.
    if is_best:
        return "best"

    # If the move walks into a fresh forced mate, treat it as a blunder.
    side_mate_before = None
    side_mate_after = None
    if mate_before is not None:
        side_mate_before = int(mate_before) if side != "black" else -int(mate_before)
    if mate_after is not None:
        side_mate_after = int(mate_after) if side != "black" else -int(mate_after)

    if side_mate_after is not None and side_mate_after < 0:
        if side_mate_before is None or side_mate_before >= 0:
            return "blunder"

    # CAPS2-like core grading buckets.
    if cp_loss <= 15:
        return "excellent"
    if cp_loss <= 40:
        return "good"
    if cp_loss <= 100:
        return "inaccuracy"
    if cp_loss <= 250:
        return "mistake"
    return "blunder"


def win_percent_from_cp(cp: int) -> float:
    """Convert centipawn eval to win expectancy % for side-to-assess (0..100)."""
    # Cap extremes so mate scores do not dominate numeric stability.
    capped = max(-1200, min(1200, int(cp)))
    w = 2.0 / (1.0 + math.exp(-0.00368208 * capped)) - 1.0
    return max(0.0, min(100.0, 50.0 + (w * 50.0)))


def move_accuracy_from_category(
    category: str,
    cp_loss: int,
    side: str,
    mate_before: int | None = None,
    mate_after: int | None = None,
    severe_streak: int = 0,
) -> float | None:
    """CAPS2-style per-move grade: category score with mate and streak smoothing."""
    base_scores = {
        "book": 100.0,
        "best": 100.0,
        "brilliant": 100.0,
        "excellent": 90.0,
        "great": 85.0,
        "good": 75.0,
        "inaccuracy": 50.0,
        "mistake": 20.0,
        "miss": 20.0,
        "blunder": 0.0,
    }

    score = float(base_scores.get(category, 75.0))

    # Fine-tune within each bucket without changing category identity.
    if category in {"excellent", "great", "good", "inaccuracy", "mistake", "miss", "blunder"}:
        score -= min(15.0, max(0, cp_loss) / 30.0)

    side_mate_before = None
    side_mate_after = None
    if mate_before is not None:
        side_mate_before = int(mate_before) if side != "black" else -int(mate_before)
    if mate_after is not None:
        side_mate_after = int(mate_after) if side != "black" else -int(mate_after)

    # Mate-distance smoothing.
    if side_mate_after is not None and side_mate_after < 0:
        if side_mate_before is None or side_mate_before >= 0:
            # Freshly entering forced mate should score very poorly.
            score = min(score, 10.0 if abs(side_mate_after) <= 3 else 15.0)
        else:
            # Already in a forced-mate sequence: avoid cascading over-penalties.
            score = max(score, 40.0)
            # If move extends mate distance, give practical credit.
            if abs(side_mate_after) > abs(side_mate_before):
                score = max(score, 78.0)

    # Reduce penalty for consecutive severe mistakes/blunders.
    if category in {"mistake", "blunder"} and severe_streak > 1:
        penalty = 100.0 - score
        penalty *= 0.78 ** (severe_streak - 1)
        score = 100.0 - penalty

    return round(max(0.0, min(100.0, score)), 1)


def accuracy_from_move_accuracies(move_accuracies: list[float]) -> float:
    if not move_accuracies:
        return 100.0
    avg = sum(move_accuracies) / len(move_accuracies)
    return round(max(0.0, min(100.0, avg)), 1)


def accuracy_from_losses(losses: list[int]) -> float:
    """Legacy fallback formula based on average centipawn loss."""
    if not losses:
        return 100.0
    avg_loss = sum(losses) / len(losses)
    # Exponential formula similar to Chess.com: 100 * e^(-0.005 * avg_loss)
    accuracy = 100.0 * math.exp(-0.005 * avg_loss)
    return round(max(0.0, min(100.0, accuracy)), 1)