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
        removeErrorOverlay();
        
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
    }

    function onDragStart(source, piece, position, orientation) {
        if (aiThinking) return false;
        if (game.game_over()) return false;

        // Block: only allow the player to move THEIR color
        const turnColor = game.turn() === 'w' ? 'white' : 'black';
        if (turnColor !== playerColor) {
            updateStatus("It's the AI's turn! Want to explore moves? Go to Analysis.", "thinking");
            return false;
        }

        // Block: don't let player pick up opponent's pieces
        if ((playerColor === 'white' && piece.search(/^b/) !== -1) ||
            (playerColor === 'black' && piece.search(/^w/) !== -1)) {
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

    // Request Move from Server — with silent retry
    async function triggerAIMove(retryCount = 0) {
        const MAX_RETRIES = 2;
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
                const fromSqr = aiMoveUci.substring(0, 2);
                const toSqr = aiMoveUci.substring(2, 4);
                const prom = aiMoveUci.length > 4 ? aiMoveUci.substring(4) : undefined;
                
                game.move({ from: fromSqr, to: toSqr, promotion: prom });
                board.position(game.fen());

                aiThinking = false;
                checkGameEnd();
                if (!game.game_over()) {
                    updateStatus(`AI played ${aiMoveUci}. Your turn!`);
                }
            }
        } catch (err) {
            console.warn(`AI move fetch attempt ${retryCount + 1} failed:`, err.message);

            // Silent retry up to MAX_RETRIES
            if (retryCount < MAX_RETRIES) {
                await new Promise(r => setTimeout(r, 1000)); // 1s delay between retries
                return triggerAIMove(retryCount + 1);
            }

            // All retries exhausted — show error overlay
            aiThinking = false;
            showErrorOverlay(err.message);
        }
    }

    // ── Error Overlay ─────────────────────────────────────
    function showErrorOverlay(message) {
        removeErrorOverlay();
        
        const overlay = document.createElement('div');
        overlay.id = 'aiErrorOverlay';
        overlay.innerHTML = `
            <div class="ai-error-content">
                <i class="bi bi-exclamation-triangle-fill" style="font-size: 2.5rem; color: #e84040; margin-bottom: 16px;"></i>
                <h4>AI Move Failed</h4>
                <p>The engine couldn't respond after multiple attempts.<br>
                   <span style="color: #999; font-size: 0.85rem;">${escapeHtml(message)}</span>
                </p>
                <div style="display: flex; gap: 12px; margin-top: 20px;">
                    <button id="btnReloadBoard" class="ai-err-btn primary">
                        <i class="bi bi-arrow-repeat"></i> Reload Board
                    </button>
                    <a href="/contact/" class="ai-err-btn secondary">
                        <i class="bi bi-flag"></i> Report Issue
                    </a>
                </div>
            </div>
        `;
        
        // Style the overlay inline (matches the dark theme)
        Object.assign(overlay.style, {
            position: 'absolute', top: '0', left: '0', width: '100%', height: '100%',
            background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: '100', borderRadius: '6px', textAlign: 'center', color: '#f0f0f0',
        });
        
        const wrapper = document.querySelector('.board-wrapper');
        wrapper.style.position = 'relative';
        wrapper.appendChild(overlay);

        document.getElementById('btnReloadBoard').addEventListener('click', () => {
            removeErrorOverlay();
            initBoard();
            // If playing as black, trigger AI move for white
            if (playerColor === 'black') {
                gameStarted = true;
                setTimeout(triggerAIMove, 250);
            }
        });
    }

    function removeErrorOverlay() {
        const existing = document.getElementById('aiErrorOverlay');
        if (existing) existing.remove();
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
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
