# Final engine_service/app.py (PRIORITY QUEUE & STABILITY)
import os, chess, chess.engine, asyncio
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from pydantic import BaseModel
from typing import List, Optional, Any
from dataclasses import dataclass, field

app = FastAPI(title="ChessCraft Stockfish Service (V3 - Priority Queue)")
ENGINE_TOKEN = os.getenv("ENGINE_TOKEN", "UzairChessCraftToken1740")
STOCKFISH_PATH = "/usr/games/stockfish"

# Priority levels
PRIORITY_HIGH = 0    # Manual analysis
PRIORITY_NORMAL = 1  # Batch / Insights

@dataclass(order=True)
class AnalysisTask:
    priority: int
    fen: str = field(compare=False)
    depth: int = field(compare=False)
    elo: Optional[int] = field(compare=False, default=None)
    future: asyncio.Future = field(compare=False, default=None)

# Global queue and state
task_queue = asyncio.PriorityQueue()
active_tasks = 0

class AnalysisRequest(BaseModel):
    fen: str
    depth: int = 16
    elo: Optional[int] = None

class BatchAnalysisRequest(BaseModel):
    fens: List[str]
    depth: int = 16
    # Batch analysis usually doesn't use Elo limits, but we could add it if needed

class AnalysisResponse(BaseModel):
    evaluation_cp: Optional[int] = None
    evaluation: Optional[float] = None
    best_move: str
    pv: List[str]
    depth: int
    mate: Optional[int] = None

def verify_token(authorization: Optional[str] = Header(None)):
    if ENGINE_TOKEN and (authorization != f"Bearer {ENGINE_TOKEN}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# ── Background Worker ───────────────────────────────────────
async def stockfish_worker():
    global active_tasks
    while True:
        # Get next task (highest priority first)
        task: AnalysisTask = await task_queue.get()
        active_tasks += 1
        
        try:
            if not os.path.exists(STOCKFISH_PATH):
                task.future.set_exception(Exception("Stockfish binary not found"))
                continue
            
            engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            
            # Apply Elo scaling if requested
            if task.elo is not None:
                engine.configure({
                    "UCI_LimitStrength": True,
                    "UCI_Elo": task.elo
                })
            
            board = chess.Board(task.fen)
            result = await asyncio.to_thread(engine.analyse, board, chess.engine.Limit(depth=task.depth))
            top = result[0] if isinstance(result, list) else result
            score = top.get("score").pov(chess.WHITE)
            pv_moves = [m.uci() for m in (top.get("pv") or [])]
            engine.quit()

            response = AnalysisResponse(
                evaluation_cp=score.score(mate_score=100000),
                evaluation=round(score.score(mate_score=100000) / 100.0, 2),
                best_move=pv_moves[0] if pv_moves else "",
                pv=pv_moves, depth=task.depth, mate=score.mate()
            )
            task.future.set_result(response)
        except Exception as e:
            task.future.set_exception(e)
        finally:
            active_tasks -= 1
            task_queue.task_done()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(stockfish_worker())

# ── Endpoints ───────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_tasks": active_tasks,
        "queue_length": task_queue.qsize()
    }

@app.post("/analyze", response_model=AnalysisResponse, dependencies=[Depends(verify_token)])
async def analyze(request: AnalysisRequest, req: Request):
    priority = int(req.headers.get("x-priority", PRIORITY_HIGH))
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    
    task = AnalysisTask(
        priority=priority, 
        fen=request.fen, 
        depth=request.depth, 
        elo=request.elo,
        future=future
    )
    await task_queue.put(task)
    
    # Wait for the worker to finish the task
    try:
        return await future
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze_batch", response_model=List[AnalysisResponse], dependencies=[Depends(verify_token)])
async def analyze_batch(request: BatchAnalysisRequest, req: Request):
    priority = int(req.headers.get("x-priority", PRIORITY_NORMAL))
    loop = asyncio.get_running_loop()
    futures = []
    
    # Split batch into individual tasks to allow interleaving with high-priority manual requests
    for fen in request.fens:
        future = loop.create_future()
        task = AnalysisTask(priority=priority, fen=fen, depth=request.depth, future=future)
        await task_queue.put(task)
        futures.append(future)
    
    # Wait for all individual game analyses to complete
    try:
        return await asyncio.gather(*futures)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
