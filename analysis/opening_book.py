from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import chess
import chess.polyglot
from django.conf import settings


@dataclass(frozen=True)
class EcoLine:
    eco: str
    opening: str
    moves: tuple[str, ...]


@dataclass(frozen=True)
class BookHit:
    is_book: bool
    source: str
    confidence: float
    opening: str | None = None
    eco_code: str | None = None


@lru_cache(maxsize=2)
def _load_eco_prefix_map(eco_path: str) -> dict[tuple[str, ...], list[EcoLine]]:
    prefix_map: dict[tuple[str, ...], list[EcoLine]] = {}
    path = Path(eco_path)
    if not path.exists():
        return prefix_map

    with path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for row in reader:
            if not row:
                continue
            if row[0].startswith("#"):
                continue
            if len(row) < 3:
                continue

            eco = (row[0] or "").strip()
            opening = (row[1] or "").strip()
            moves = tuple(item.strip() for item in (row[2] or "").split() if item.strip())
            if not moves:
                continue

            line = EcoLine(eco=eco, opening=opening, moves=moves)
            for i in range(1, len(moves) + 1):
                prefix = moves[:i]
                prefix_map.setdefault(prefix, []).append(line)

    return prefix_map


class OpeningBookResolver:
    """Local opening detector with polyglot support and ECO-prefix fallback."""

    def __init__(self, headers: dict[str, Any] | None = None) -> None:
        headers = headers or {}
        self.header_opening = (headers.get("Opening") or "").strip() or None
        self.header_eco = (headers.get("ECO") or "").strip() or None

        default_eco_path = Path(settings.BASE_DIR) / "analysis" / "data" / "eco_lines.tsv"
        eco_db_path = getattr(settings, "ANALYSIS_ECO_DB_PATH", str(default_eco_path))
        self.prefix_map = _load_eco_prefix_map(str(eco_db_path))

        self.polyglot_reader = None
        polyglot_path = (getattr(settings, "ANALYSIS_POLYGLOT_PATH", "") or "").strip()
        if polyglot_path:
            try:
                path_obj = Path(polyglot_path)
                if path_obj.exists():
                    self.polyglot_reader = chess.polyglot.open_reader(str(path_obj))
            except Exception:
                self.polyglot_reader = None

    def close(self) -> None:
        if self.polyglot_reader is not None:
            try:
                self.polyglot_reader.close()
            except Exception:
                pass
            self.polyglot_reader = None

    def detect_move(
        self,
        board_before: chess.Board,
        move_uci: str,
        move_history_uci: list[str],
        ply_index: int,
        cp_loss: int,
        cp_before: int,
        cp_after: int,
        best_move_uci: str,
        top_candidate_moves: list[str],
    ) -> BookHit:
        move_uci = (move_uci or "").strip()
        best_move_uci = (best_move_uci or "").strip()
        top_moves = [item.strip() for item in top_candidate_moves if item]

        # 1) Polyglot lookup if an opening book file is configured.
        if self.polyglot_reader is not None:
            try:
                entries = list(self.polyglot_reader.find_all(board_before))
                if entries:
                    max_weight = max(item.weight for item in entries) or 1
                    for item in entries:
                        if item.move.uci() == move_uci:
                            conf = 0.72 + (0.25 * (item.weight / max_weight))
                            return BookHit(
                                is_book=True,
                                source="polyglot",
                                confidence=round(min(0.98, conf), 2),
                                opening=self.header_opening,
                                eco_code=self.header_eco,
                            )
            except Exception:
                pass

        # 2) Local ECO-prefix database.
        history_after = tuple(move_history_uci + [move_uci])
        eco_matches = self.prefix_map.get(history_after, [])
        if eco_matches:
            chosen = max(eco_matches, key=lambda item: len(item.moves))
            conf = min(0.97, 0.50 + (0.035 * len(history_after)))
            return BookHit(
                is_book=True,
                source="eco_db",
                confidence=round(conf, 2),
                opening=chosen.opening or self.header_opening,
                eco_code=chosen.eco or self.header_eco,
            )

        # 3) Header-guided local fallback (no external API dependency).
        if (self.header_opening or self.header_eco) and ply_index <= 18:
            if move_uci in top_moves and cp_loss <= 14 and abs(cp_before) <= 180 and abs(cp_after) <= 220:
                conf = 0.45 + (0.02 * max(0, 18 - ply_index))
                return BookHit(
                    is_book=True,
                    source="pgn_header_heuristic",
                    confidence=round(min(0.70, conf), 2),
                    opening=self.header_opening,
                    eco_code=self.header_eco,
                )

        # 4) Last-resort heuristic for quiet opening phase.
        if ply_index <= 14 and (move_uci == best_move_uci or move_uci in top_moves[:2]):
            if cp_loss <= 8 and abs(cp_before) <= 120 and abs(cp_after) <= 120:
                return BookHit(
                    is_book=True,
                    source="heuristic",
                    confidence=0.42,
                    opening=self.header_opening,
                    eco_code=self.header_eco,
                )

        return BookHit(is_book=False, source="none", confidence=0.0)

    def resolve_opening_metadata(self, strongest_hit: BookHit | None = None) -> dict[str, Any]:
        # PGN header is still highest-confidence source if present.
        if self.header_opening or self.header_eco:
            return {
                "opening": self.header_opening,
                "eco_code": self.header_eco,
                "opening_source": "pgn_header",
                "opening_confidence": 0.95,
            }

        if strongest_hit and (strongest_hit.opening or strongest_hit.eco_code):
            return {
                "opening": strongest_hit.opening,
                "eco_code": strongest_hit.eco_code,
                "opening_source": strongest_hit.source,
                "opening_confidence": strongest_hit.confidence,
            }

        return {
            "opening": None,
            "eco_code": None,
            "opening_source": "unknown",
            "opening_confidence": 0.0,
        }
