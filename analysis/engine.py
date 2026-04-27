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


def _engine_result_to_payload(result: EngineResult) -> dict[str, Any]:
    return {
        "evaluation_cp": result.cp,
        "evaluation": result.evaluation,
        "best_move": result.best_move,
        "pv": result.pv,
        "depth": result.depth,
        "mate": result.mate,
    }


def _payload_to_engine_result(body: dict[str, Any], depth: int) -> EngineResult:
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


class StockfishManager:
    """Engine adapter: remote API first (Azure), local binary fallback."""

    def __init__(self) -> None:
        self.remote_url = getattr(settings, "ANALYSIS_ENGINE_URL", "").strip()
        self.remote_token = getattr(settings, "ANALYSIS_ENGINE_TOKEN", "").strip()
        self.remote_timeout = int(getattr(settings, "ANALYSIS_ENGINE_TIMEOUT", 25))
        self.remote_batch_timeout = int(getattr(settings, "ANALYSIS_ENGINE_BATCH_TIMEOUT", 90))
        self._remote_batch_multipv_supported: bool | None = None

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

    def get_health(self) -> dict[str, Any]:
        """Check if the remote engine is busy."""
        if self.mode != "remote" or not self.remote_url:
            local_bin = os.path.basename(self.local_path) if self.local_path else "stockfish"
            return {
                "status": "ok",
                "active_tasks": 0,
                "mode": self.mode,
                "engine_version": f"local:{local_bin}",
            }
        
        health_url = self.remote_url.replace("/analyze", "/health")
        try:
            response = requests.get(health_url, timeout=5)
            if response.ok:
                return response.json()
        except Exception:
            pass
        return {
            "status": "unknown",
            "active_tasks": 0,
            "engine_version": "remote:unknown",
        }

    def get_engine_version(self) -> str:
        """Stable version token used for selective re-analysis caching."""
        if self.mode == "remote" and self.remote_url:
            health = self.get_health()
            remote_version = str(health.get("engine_version") or "remote:unknown")
            if remote_version.startswith("remote:"):
                return remote_version
            return f"remote:{remote_version}"
        local_bin = os.path.basename(self.local_path) if self.local_path else "stockfish"
        return f"local:{local_bin}"

    def supports_batch_multipv(self) -> bool:
        """Detect whether remote batch API returns per-position multi-PV lines."""
        if self.mode != "remote":
            return True

        if self._remote_batch_multipv_supported is not None:
            return self._remote_batch_multipv_supported

        force_setting = getattr(settings, "ANALYSIS_REMOTE_BATCH_MULTIPV", None)
        if force_setting is not None:
            self._remote_batch_multipv_supported = bool(force_setting)
            return self._remote_batch_multipv_supported

        health = self.get_health()
        if "supports_batch_lines" in health:
            self._remote_batch_multipv_supported = bool(health.get("supports_batch_lines"))
            return self._remote_batch_multipv_supported

        version = str(health.get("engine_version") or "").lower()
        self._remote_batch_multipv_supported = ("multipv" in version) or ("v4" in version)
        return self._remote_batch_multipv_supported

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
        requested_multipv = max(1, multipv)

        if self.mode == "remote" and requested_multipv > 1 and not self.supports_batch_multipv():
            # Older remote services do not return batch "lines"; keep a fast single-pass batch.
            requested_multipv = 1

        if self.mode == "remote":
            line_sets = self._analyze_batch_remote(fens, target_depth, requested_multipv, priority=priority)
        else:
            line_sets = self._analyze_batch_local(fens, target_depth, requested_multipv)

        output = []
        for lines in line_sets:
            if not lines:
                lines = [
                    EngineResult(
                        cp=0,
                        evaluation=0.0,
                        best_move="",
                        pv=[],
                        depth=target_depth,
                        mate=None,
                    )
                ]

            top = lines[0]
            payload = _engine_result_to_payload(top)
            payload["lines"] = [_engine_result_to_payload(item) for item in lines]
            output.append(payload)
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

        lines_data = body.get("lines") if isinstance(body, dict) else None
        if isinstance(lines_data, list) and lines_data:
            return _payload_to_engine_result(lines_data[0], depth)
        return _payload_to_engine_result(body, depth)

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
            
        try:
            response = requests.post(
                self.remote_url,
                json=payload,
                headers=headers,
                timeout=self.remote_timeout,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            # Provide more helpful error if the remote engine says no
            if hasattr(e, 'response') and e.response is not None:
                try:
                    err_json = e.response.json()
                    msg = err_json.get('error', str(e))
                except Exception:
                    msg = str(e)
            else:
                msg = str(e)
            raise RuntimeError(f"Remote engine failure: {msg}")

        body = response.json()

        # Check if the server responds with an array of "lines"
        lines_data = body.get("lines")
        # If not, create a fallback single list from the top-level keys
        if not lines_data:
            lines_data = [body]

        results = []
        for line_data in lines_data:
            if not isinstance(line_data, dict):
                continue
            results.append(_payload_to_engine_result(line_data, depth))
            
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

    def _analyze_batch_remote(self, fens: list[str], depth: int, multipv: int, priority: int = 1) -> list[list[EngineResult]]:
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
            timeout=self.remote_batch_timeout,
        )
        response.raise_for_status()

        raw_items = response.json()
        output: list[list[EngineResult]] = []
        missing_multipv_indices: list[int] = []

        for idx, body in enumerate(raw_items):
            if not isinstance(body, dict):
                output.append([])
                missing_multipv_indices.append(idx)
                continue

            lines_data = body.get("lines") if isinstance(body.get("lines"), list) else None
            if lines_data:
                lines = []
                for line_item in lines_data:
                    if isinstance(line_item, dict):
                        lines.append(_payload_to_engine_result(line_item, depth))
                output.append(lines)
                continue

            output.append([_payload_to_engine_result(body, depth)])
            if multipv > 1:
                missing_multipv_indices.append(idx)

        # Optional compatibility fallback for older remote batch servers that only return top line.
        if multipv > 1 and missing_multipv_indices:
            allow_fallback = bool(
                getattr(settings, "ANALYSIS_REMOTE_PER_POSITION_MULTIPV_FALLBACK", False)
            )
            fallback_max = int(
                getattr(settings, "ANALYSIS_REMOTE_PER_POSITION_MULTIPV_FALLBACK_MAX", 6)
            )

            if allow_fallback and len(missing_multipv_indices) <= max(0, fallback_max):
                for idx in missing_multipv_indices:
                    try:
                        output[idx] = self._analyze_remote_multipv(
                            fen=fens[idx],
                            depth=depth,
                            multipv=multipv,
                            priority=priority,
                        )
                    except Exception:
                        if not output[idx]:
                            output[idx] = [
                                EngineResult(
                                    cp=0,
                                    evaluation=0.0,
                                    best_move="",
                                    pv=[],
                                    depth=depth,
                                    mate=None,
                                )
                            ]
        return output

    def _analyze_batch_local(self, fens: list[str], depth: int, multipv: int) -> list[list[EngineResult]]:
        if not os.path.exists(self.local_path):
            raise RuntimeError(f"Stockfish binary not found at '{self.local_path}'")

        engine = chess.engine.SimpleEngine.popen_uci(self.local_path)
        try:
            config = {"Threads": self.local_threads, "Hash": self.local_hash}
            engine.configure(config)
            
            output: list[list[EngineResult]] = []
            time_limit = max(0.08, self.default_time * (depth / max(1, self.default_depth)))
            for fen in fens:
                try:
                    board = chess.Board(fen)
                except ValueError:
                    output.append(
                        [
                            EngineResult(
                                cp=0,
                                evaluation=0.0,
                                best_move="",
                                pv=[],
                                depth=depth,
                                mate=None,
                            )
                        ]
                    )
                    continue
                
                info = engine.analyse(
                    board,
                    chess.engine.Limit(depth=depth, time=time_limit),
                    multipv=max(1, multipv),
                )
                rows = info if isinstance(info, list) else [info]
                fen_lines: list[EngineResult] = []
                for row in rows:
                    score = row.get("score")
                    pv_moves = row.get("pv") or []

                    cp = 0
                    mate = None
                    if score is not None:
                        cp = score.pov(chess.WHITE).score(mate_score=MATE_CP) or 0
                        mate = score.pov(chess.WHITE).mate()

                    best_move = pv_moves[0].uci() if pv_moves else ""
                    pv = [mv.uci() for mv in pv_moves]
                    fen_lines.append(EngineResult(
                        cp=int(cp),
                        evaluation=round(int(cp) / 100.0, 2),
                        best_move=best_move,
                        pv=pv,
                        depth=depth,
                        mate=mate,
                    ))

                output.append(fen_lines)
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


def _is_tactical_pv(board_before: chess.Board, pv: list[str] | None) -> bool:
    """Detect forcing tactical content in the first part of a PV line."""
    if not pv:
        return False

    board = board_before.copy()
    forcing = 0
    for uci in pv[:2]:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break

        if move not in board.legal_moves:
            break

        if board.is_capture(move) or board.gives_check(move) or move.promotion:
            forcing += 1

        board.push(move)

    return forcing >= 1


def classify_move(
    cp_loss: int,
    cp_gain: int,
    potential_gain: int,
    move_uci: str,
    best_move_uci: str,
    board_before: chess.Board,
    second_best_move_uci: str | None = None,
    second_best_cp: int | None = None,
    move_rank: int | None = None,
    best_pv: list[str] | None = None,
    follow_pv: list[str] | None = None,
    is_book: bool = False,
    cp_before: int | None = None,
    cp_after: int | None = None,
    side: str | None = None,
    mate_before: int | None = None,
    mate_after: int | None = None,
    best_mate: int | None = None,
    second_best_mate: int | None = None,
) -> str:
    if is_book:
        return "book"

    move_uci = (move_uci or "").strip()
    best_move_uci = (best_move_uci or "").strip()
    second_best_move_uci = (second_best_move_uci or "").strip()
    is_best = move_uci and move_uci == best_move_uci
    if move_rank is None and is_best:
        move_rank = 1
    elif move_rank is None and second_best_move_uci and move_uci == second_best_move_uci:
        move_rank = 2

    # Convert evals to side-relative POV
    cp_before_pov = 0
    cp_after_pov = 0
    if cp_before is not None and cp_after is not None:
        if side == "black":
            cp_before_pov = -int(cp_before)
            cp_after_pov = -int(cp_after)
        else:
            cp_before_pov = int(cp_before)
            cp_after_pov = int(cp_after)

    second_best_pov = None
    if second_best_cp is not None:
        second_best_pov = -int(second_best_cp) if side == "black" else int(second_best_cp)

    critical_gap = 0
    if second_best_pov is not None:
        critical_gap = max(0, cp_before_pov - second_best_pov)

    # Side-relative mate values
    side_mate_before = None
    side_mate_after = None
    side_best_mate = None
    side_second_best_mate = None
    if mate_before is not None:
        side_mate_before = int(mate_before) if side != "black" else -int(mate_before)
    if mate_after is not None:
        side_mate_after = int(mate_after) if side != "black" else -int(mate_after)
    if best_mate is not None:
        side_best_mate = int(best_mate) if side != "black" else -int(best_mate)
    if second_best_mate is not None:
        side_second_best_mate = int(second_best_mate) if side != "black" else -int(second_best_mate)

    # ─── Checkmate is ALWAYS "best" ───
    try:
        move_obj = chess.Move.from_uci(move_uci)
        test_board = board_before.copy()
        if move_obj in test_board.legal_moves:
            test_board.push(move_obj)
            if test_board.is_checkmate():
                return "best"
    except (ValueError, IndexError):
        pass

    # ─── Walking into a fresh forced mate against us → blunder ───
    if side_mate_after is not None and side_mate_after < 0:
        if side_mate_before is None or side_mate_before >= 0:
            return "blunder"

    # ─── If the move walks into forced mate for us being shortened, still bad ───
    if side_mate_after is not None and side_mate_after < 0:
        if side_mate_before is not None and side_mate_before < 0:
            # Already in a losing forced-mate sequence
            if abs(side_mate_after) < abs(side_mate_before):
                # Mate got shorter (worse for us)
                return "mistake"

    best_line_tactical = _is_tactical_pv(board_before, best_pv)
    follow_line_tactical = _is_tactical_pv(board_before, follow_pv)
    tactical_pv_shift = best_line_tactical and not follow_line_tactical and cp_loss >= 45

    # Missed tactical chance: forcing best line exists but move sidesteps it.
    if not is_best and tactical_pv_shift and cp_before_pov >= -120:
        if cp_loss >= 70:
            return "miss"
        return "inaccuracy"

    # Missed mating shot from top line.
    if side_best_mate is not None and side_best_mate > 0 and not is_best:
        if side_second_best_mate is None or side_second_best_mate <= 0:
            return "miss"

    # ─── Brilliant: Best move + involves a sacrifice ───
    if is_best and cp_loss <= 5:
        try:
            move_obj = chess.Move.from_uci(move_uci)
            if is_sacrifice_move(board_before, move_obj):
                # Must maintain practical soundness and usually be a critical line.
                if cp_after_pov >= -70 and (critical_gap >= 70 or cp_after_pov >= cp_before_pov - 10):
                    return "brilliant"
        except (ValueError, IndexError):
            pass

    # ─── Great: best move in a critical (best vs second-best) spot ───
    if is_best and cp_loss <= 5:
        if critical_gap >= 90:
            return "great"
        if cp_before_pov < 0 and critical_gap >= 70 and cp_after_pov >= cp_before_pov - 8:
            return "great"

    # ─── Best: exact engine move ───
    if is_best:
        return "best"

    # Near-top move handling using true PV ranking and delta.
    if move_rank == 2 and cp_loss <= 20:
        return "excellent"
    if move_rank == 3 and cp_loss <= 35:
        return "good"

    # ─── Miss: Player had a chance to exploit opponent's blunder/mistake 
    # but played a different (non-punishing) move ───
    # Detected when: before_pov was very good (opponent blundered), and
    # the player's move lets the advantage slip significantly
    if cp_before_pov >= 150 and cp_loss >= 80:
        # The player had a big advantage and didn't capitalize
        # This is a "miss" if they were winning and let it slip
        if cp_after_pov < cp_before_pov - 80:
            return "miss"

    # Also detect missed mate opportunities
    if side_mate_before is not None and side_mate_before > 0:
        # We had a forced mate and didn't play it
        if side_mate_after is None or side_mate_after <= 0:
            return "miss"
        # We had mate in N but played a move that extends it significantly
        if side_mate_after > side_mate_before + 3:
            return "miss"

    # ─── Win-percent based grading for remaining moves ───
    # Using win% model gives more chess.com-like accuracy
    wp_before = win_percent_from_cp(cp_before_pov)
    wp_after = win_percent_from_cp(cp_after_pov)
    wp_loss = max(0, wp_before - wp_after)

    # Multi-PV + win%-aware grading tuned to reduce over-labeling inaccuracies.
    if wp_loss <= 2.8 and cp_loss <= 30:
        return "excellent"
    if wp_loss <= 6.0 and cp_loss <= 65:
        return "good"
    if wp_loss <= 12.0 and cp_loss <= 130:
        return "inaccuracy"
    if wp_loss <= 24.0 and cp_loss <= 280:
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
    cp_before: int | None = None,
    cp_after: int | None = None,
) -> float | None:
    """CAPS2-style per-move grade with win%-based fine-tuning."""
    base_scores = {
        "book": 100.0,
        "best": 100.0,
        "brilliant": 100.0,
        "great": 100.0,
        "excellent": 96.0,
        "good": 85.0,
        "inaccuracy": 58.0,
        "miss": 22.0,
        "mistake": 13.0,
        "blunder": 0.0,
    }

    score = float(base_scores.get(category, 72.0))

    # Win%-based fine-tuning within buckets for more accurate grading
    if category in {"excellent", "good", "inaccuracy", "mistake", "miss", "blunder"}:
        # Use win% loss if we have the data, otherwise fall back to cp_loss
        if cp_before is not None and cp_after is not None:
            cp_before_pov = -int(cp_before) if side == "black" else int(cp_before)
            cp_after_pov = -int(cp_after) if side == "black" else int(cp_after)
            wp_before = win_percent_from_cp(cp_before_pov)
            wp_after = win_percent_from_cp(cp_after_pov)
            wp_loss = max(0, wp_before - wp_after)
            # Scale penalty based on win% lost (more meaningful than raw cp)
            score -= min(10.0, wp_loss * 0.65)
        else:
            score -= min(12.0, max(0, cp_loss) / 30.0)

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
            score = min(score, 8.0 if abs(side_mate_after) <= 3 else 12.0)
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