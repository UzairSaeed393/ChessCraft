import os
import chess
import chess.engine
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="ChessCraft Stockfish Service")

# Security Token (Must match ANALYSIS_ENGINE_TOKEN in .env)
# Using an environment variable on the server for security
ENGINE_TOKEN = os.getenv("ENGINE_TOKEN", "UzairChessCraftToken1740")

# Path to Stockfish binary on Ubuntu (will be installed at /usr/games/stockfish)
STOCKFISH_PATH = "/usr/games/stockfish"

class AnalysisRequest(BaseModel):
    fen: str
    depth: int = 14
    multipv: int = 1

class AnalysisResponse(BaseModel):
    evaluation_cp: Optional[int] = None
    evaluation: Optional[float] = None
    best_move: str
    pv: List[str]
    depth: int
    mate: Optional[int] = None

def verify_token(authorization: Optional[str] = Header(None)):
    if ENGINE_TOKEN and (not authorization or authorization != f"Bearer {ENGINE_TOKEN}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

@app.post("/analyze", response_model=AnalysisResponse, dependencies=[Depends(verify_token)])
async def analyze(request: AnalysisRequest):
    if not os.path.exists(STOCKFISH_PATH):
        raise HTTPException(status_code=500, detail=f"Stockfish not found at {STOCKFISH_PATH}")

    try:
        board = chess.Board(request.fen)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid FEN")

    try:
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        result = engine.analyse(board, chess.engine.Limit(depth=request.depth), multipv=request.multipv)
        
        # Get top line
        top = result[0] if isinstance(result, list) else result
        score = top.get("score").pov(chess.WHITE)
        pv_moves = [m.uci() for m in (top.get("pv") or [])]
        
        cp = score.score(mate_score=100000)
        mate = score.mate()
        
        engine.quit()

        return AnalysisResponse(
            evaluation_cp=cp,
            evaluation=round(cp / 100.0, 2) if cp is not None else None,
            best_move=pv_moves[0] if pv_moves else "",
            pv=pv_moves,
            depth=request.depth,
            mate=mate
        )
    except Exception as e:
        if 'engine' in locals(): engine.quit()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok", "engine": "Stockfish 16+ (Ubuntu)"}
