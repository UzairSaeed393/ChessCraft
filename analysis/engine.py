import chess
import chess.engine
import platform
import os

class StockfishManager:
    def __init__(self):
        # DYNAMIC PATH: Automatically switches based on your server environment
        if platform.system() == "Windows":
            # Using the path from your previous terminal session
            self.engine_path = r"D:\Web development\Stockfish\stockfish-windows-x86-64-avx2.exe" 
        else:
            # The production path on your Azure Linux VM
            self.engine_path = "/usr/games/stockfish"

    def get_analysis(self, fen, depth=12):
        """
        Connects to the engine, analyzes the position, and closes the connection.
        """
        engine = None
        try:
            # Start the UCI connection
            engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
            
            # Resource constraints for fast web responses
            engine.configure({"Threads": 1, "Hash": 16})
            
            board = chess.Board(fen)
            
            # Analyze position (Limit: 0.1 seconds or depth 12)
            info = engine.analyse(board, chess.engine.Limit(time=0.1, depth=depth))
            
            # Extract centipawn score
            score = info["score"].relative.score(mate_score=10000)
            best_move = info["pv"][0] if "pv" in info else None
            
            return {
                "evaluation": round(score / 100.0, 2) if score is not None else 0,
                "best_move": best_move.uci() if best_move else "N/A",
                "depth": depth
            }
        except Exception as e:
            return {"error": f"Engine failed: {str(e)}"}
        finally:
            # ALWAYS quit the engine to prevent RAM leaks on your Azure VM
            if engine:
                engine.quit()

    def classify_move(self, prev_eval, current_eval, is_white):
        """
        Determines if a move is Brilliant, a Blunder, etc., based on eval change.
        """
        diff = (current_eval - prev_eval) if is_white else (prev_eval - current_eval)
        
        if diff < -2.0:
            return "Blunder"
        if diff < -1.0:
            return "Mistake"
        if diff > 0.4:
            return "Brilliant"
        return "Best"