/* ============================================================
   home.js — ChessCraft Home Page Play vs AI
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
    
    // UI Elements
    const eloSlider = document.getElementById('eloSlider');
    const eloValue = document.getElementById('eloValue');
    const btnPlayWhite = document.getElementById('btnPlayWhite');
    const btnPlayBlack = document.getElementById('btnPlayBlack');
    const btnNewGame = document.getElementById('btnNewGame');
    const statusBox = document.getElementById('gameStatus');
    
    // Game State
    let game = new Chess();
    let board = null;
    let playerColor = 'white'; // 'white' or 'black'
    let aiThinking = false;
    let gameStarted = false;
    
    // CSRF token for POST
    function getCSRFToken() {
        const cookies = document.cookie.split(';');
        for (let c of cookies) {
            c = c.trim();
            if (c.startsWith('csrftoken=')) return c.substring(10);
        }
        return '';
    }

    // Initialize Board
    function initBoard() {
        game.reset();
        aiThinking = false;
        gameStarted = false;
        
        board = Chessboard('homeBoard', {
            draggable: true,
            position: game.fen(),
            orientation: playerColor,
            onDragStart: onDragStart,
            onDrop: onDrop,
            onSnapEnd: onSnapEnd,
            pieceTheme: 'https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png'
        });
        
        updateStatus("Your move! Good luck.");

        // We no longer trigger AI move immediately if playing as black.
        // The game starts when the user chooses or makes a move.
    }

    function onDragStart(source, piece, position, orientation) {
        if (aiThinking) return false;
        if (game.game_over()) return false;
        // Don't let player move AI pieces
        if ((game.turn() === 'w' && piece.search(/^b/) !== -1) ||
            (game.turn() === 'b' && piece.search(/^w/) !== -1)) {
            return false;
        }
    }

    function onDrop(source, target) {
        const move = game.move({
            from: source,
            to: target,
            promotion: 'q'
        });

        if (move === null) return 'snapback';

        gameStarted = true;
        checkGameEnd();
        if (!game.game_over()) {
            window.setTimeout(triggerAIMove, 250);
        }
    }

    function onSnapEnd() {
        board.position(game.fen());
    }

    // Request Move from Server
    async function triggerAIMove() {
        aiThinking = true;
        updateStatus("AI is thinking...", "thinking");

        const elo = parseInt(eloSlider.value);
        const fen = game.fen();

        try {
            const resp = await fetch('/api/play-vs-ai/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken(),
                },
                body: JSON.stringify({ fen: fen, elo: elo })
            });

            const data = await resp.json();

            if (!resp.ok) {
                throw new Error(data.error || 'Server error');
            }

            const aiMoveUci = data.best_move;
            if (aiMoveUci) {
                // Parse UCI (e.g. e2e4 or e7e8q)
                const fromSqr = aiMoveUci.substring(0, 2);
                const toSqr = aiMoveUci.substring(2, 4);
                const prom = aiMoveUci.length > 4 ? aiMoveUci.substring(4) : undefined;
                
                // Apply move to internal chess logic
                game.move({ from: fromSqr, to: toSqr, promotion: prom });
                
                // Play move on UI board
                board.position(game.fen());

                aiThinking = false;
                checkGameEnd();
                if (!game.game_over()) {
                    updateStatus(`AI played ${aiMoveUci}. Your turn!`);
                }
            }
        } catch (err) {
            console.error(err);
            updateStatus("Error fetching AI move: " + err.message, "error");
            aiThinking = false;
        }
    }

    function checkGameEnd() {
        if (game.in_checkmate()) {
            const winner = game.turn() === 'w' ? 'Black' : 'White';
            updateStatus(`Checkmate! ${winner} wins.`, "error");
        } else if (game.in_draw() || game.in_stalemate() || game.in_threefold_repetition()) {
            updateStatus("Game drawn.", "thinking");
        }
    }

    function updateStatus(msg, statusClass = "") {
        statusBox.textContent = msg;
        statusBox.className = "status-box " + statusClass;
    }

    // Events
    eloSlider.addEventListener('input', (e) => {
        eloValue.textContent = e.target.value;
    });

    btnPlayWhite.addEventListener('click', () => {
        if (aiThinking) return;
        playerColor = 'white';
        btnPlayWhite.classList.add('active');
        btnPlayBlack.classList.remove('active');
        initBoard();
    });

    btnPlayBlack.addEventListener('click', () => {
        if (aiThinking) return;
        playerColor = 'black';
        btnPlayBlack.classList.add('active');
        btnPlayWhite.classList.remove('active');
        initBoard();
        // Since user clicked "Play Black", AI (White) starts now
        gameStarted = true;
        setTimeout(triggerAIMove, 250);
    });

    btnNewGame.addEventListener('click', () => {
        if (aiThinking) return;
        initBoard();
    });

    // Start
    initBoard();
});
