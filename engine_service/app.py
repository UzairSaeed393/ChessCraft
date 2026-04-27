import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

import chess
import chess.engine
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel


SERVICE_VERSION = "v4-multipv"
app = FastAPI(title=f"ChessCraft Stockfish Service ({SERVICE_VERSION})")
ENGINE_TOKEN = os.getenv("ENGINE_TOKEN", "")
STOCKFISH_PATH = "/usr/games/stockfish"

# Priority levels
PRIORITY_HIGH = 0    # Manual analysis
PRIORITY_NORMAL = 1  # Batch / Insights


@dataclass(order=True)
class AnalysisTask:
    priority: int
    fen: str = field(compare=False)
    depth: int = field(compare=False)
    multipv: int = field(compare=False, default=1)
    elo: Optional[int] = field(compare=False, default=None)
    future: asyncio.Future = field(compare=False, default=None)


# Global queue and state
task_queue = asyncio.PriorityQueue()
active_tasks = 0


class AnalysisRequest(BaseModel):
    fen: str
    depth: int = 16
    multipv: int = 1
    elo: Optional[int] = None


class BatchAnalysisRequest(BaseModel):
    fens: List[str]
    depth: int = 16
    multipv: int = 1


def verify_token(authorization: Optional[str] = Header(None)):
    if ENGINE_TOKEN and (authorization != f"Bearer {ENGINE_TOKEN}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def _parse_priority(header_value: Optional[str], fallback: int) -> int:
    if header_value is None:
        return fallback
    try:
        return int(header_value)
    except (TypeError, ValueError):
        return fallback


def _result_line_payload(row: dict[str, Any], depth: int) -> dict[str, Any]:
    score_obj = row.get("score")
    score = score_obj.pov(chess.WHITE) if score_obj is not None else None
    pv_moves = [m.uci() for m in (row.get("pv") or [])]

    cp = 0
    mate = None
    if score is not None:
        cp = score.score(mate_score=100000) or 0
        mate = score.mate()

    return {
        "evaluation_cp": int(cp),
        "evaluation": round(int(cp) / 100.0, 2),
        "best_move": pv_moves[0] if pv_moves else "",
        "pv": pv_moves,
        "depth": depth,
        "mate": mate,
    }


def _analysis_payload(result: Any, depth: int, multipv: int) -> dict[str, Any]:
    rows = result if isinstance(result, list) else [result]
    lines = [_result_line_payload(row, depth) for row in rows[:max(1, multipv)] if isinstance(row, dict)]

    if not lines:
        lines = [
            {
                "evaluation_cp": 0,
                "evaluation": 0.0,
                "best_move": "",
                "pv": [],
                "depth": depth,
                "mate": None,
            }
        ]

    payload = dict(lines[0])
    payload["lines"] = lines
    return payload


# -- Background Worker -------------------------------------------------
async def stockfish_worker():
    global active_tasks
    while True:
        task: AnalysisTask = await task_queue.get()
        active_tasks += 1

        try:
            if not os.path.exists(STOCKFISH_PATH):
                task.future.set_exception(Exception("Stockfish binary not found"))
                continue

            engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

            if task.elo is not None:
                engine.configure(
                    {
                        "UCI_LimitStrength": True,
                        "UCI_Elo": task.elo,
                    }
                )

            board = chess.Board(task.fen)
            result = await asyncio.to_thread(
                engine.analyse,
                board,
                chess.engine.Limit(depth=task.depth),
                multipv=max(1, task.multipv),
            )
            engine.quit()

            task.future.set_result(_analysis_payload(result, task.depth, task.multipv))
        except Exception as exc:
            task.future.set_exception(exc)
        finally:
            active_tasks -= 1
            task_queue.task_done()


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(stockfish_worker())


# -- Endpoints ---------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_tasks": active_tasks,
        "queue_length": task_queue.qsize(),
        "engine_version": SERVICE_VERSION,
    }


@app.post("/analyze", response_model=Any, dependencies=[Depends(verify_token)])
async def analyze(request: AnalysisRequest, req: Request):
    priority = _parse_priority(req.headers.get("x-priority"), PRIORITY_HIGH)
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    task = AnalysisTask(
        priority=priority,
        fen=request.fen,
        depth=request.depth,
        multipv=max(1, request.multipv),
        elo=request.elo,
        future=future,
    )
    await task_queue.put(task)

    try:
        return await future
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/analyze_batch", response_model=List[Any], dependencies=[Depends(verify_token)])
async def analyze_batch(request: BatchAnalysisRequest, req: Request):
    priority = _parse_priority(req.headers.get("x-priority"), PRIORITY_NORMAL)
    loop = asyncio.get_running_loop()
    futures = []

    for fen in request.fens:
        future = loop.create_future()
        task = AnalysisTask(
            priority=priority,
            fen=fen,
            depth=request.depth,
            multipv=max(1, request.multipv),
            future=future,
        )
        await task_queue.put(task)
        futures.append(future)

    try:
        return await asyncio.gather(*futures)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
