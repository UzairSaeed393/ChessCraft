/* ============================================================
   analysis_board.js — Shared analysis board logic
   Supports: PGN paste, FEN setup, New Game (free explore)
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {

    // ── State ──
    let game = new Chess();
    let board = null;
    let orientation = 'white';
    let positions = [game.fen()];  // FEN history
    let currentPly = 0;
    let analyzing = false;
    let isSettingUp = window.ANALYSIS_MODE === 'fen';

    // ── DOM refs ──
    const evalRow = document.getElementById('evalRow');
    const evalScore = document.getElementById('evalScore');
    const bestMoveText = document.getElementById('bestMoveText');
    const evalDepth = document.getElementById('evalDepth');
    const moveListCard = document.getElementById('moveListCard');
    const moveList = document.getElementById('abMoveList');
    const statusEl = document.getElementById('abStatus');
    const statusText = document.getElementById('abStatusText');

    // ── CSRF ──
    function getCSRF() {
        const c = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
        return c ? c.trim().substring(10) : '';
    }

    async function postJson(url, body) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || err.message || `HTTP ${resp.status}`);
        }
        return resp.json();
    }

    // ── Init Board ──
    function initBoard(fen) {
        game = new Chess(fen || undefined);
        positions = [game.fen()];
        currentPly = 0;

        board = Chessboard('analysisBoard', {
            draggable: true,
            sparePieces: isSettingUp,
            dropOffBoard: isSettingUp ? 'trash' : 'snapback',
            position: fen && isSettingUp ? fen.split(' ')[0] : game.fen(),
            orientation: orientation,
            onDragStart: onDragStart,
            onDrop: onDrop,
            onSnapEnd: () => {
                if (!isSettingUp) board.position(game.fen());
            },
            pieceTheme: 'https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png',
        });

        if (!isSettingUp) {
            renderMoveList();
            analyzePosition(game.fen());
        } else {
            evalRow.style.display = 'none';
            document.getElementById('engineLinesContainer').innerHTML = '';
            moveListCard.style.display = 'none';
        }
    }

    function onDragStart(source, piece) {
        if (isSettingUp) return true; // Allow moving any piece to setup
        if (game.game_over()) return false;
        // Allow free movement in analysis mode
        if ((game.turn() === 'w' && piece.search(/^b/) !== -1) ||
            (game.turn() === 'b' && piece.search(/^w/) !== -1)) {
            return false;
        }
    }

    function onDrop(source, target, piece, newPos, oldPos, orientation) {
        if (isSettingUp) {
            setTimeout(() => {
                if (fenInput) fenInput.value = board.fen() + ' w KQkq - 0 1';
            }, 50);
            return; // allow anything
        }

        const move = game.move({ from: source, to: target, promotion: 'q' });
        if (!move) return 'snapback';

        // Truncate future if we branched off
        positions = positions.slice(0, currentPly + 1);
        positions.push(game.fen());
        currentPly = positions.length - 1;

        renderMoveList();
        analyzePosition(game.fen());
    }

    // ── Position analysis ──
    async function analyzePosition(fen) {
        if (analyzing) return;
        analyzing = true;
        evalRow.style.display = 'flex';
        setStatus('loading', 'Analyzing position...');

        try {
            const data = await postJson('/analysis/api/analyze/', { fen, multipv: 3 });
            const cp = data.evaluation_cp || 0;
            const evalVal = data.evaluation || (cp / 100).toFixed(2);
            const mate = data.mate;

            let displayEval;
            if (mate !== null && mate !== undefined) {
                displayEval = `M${mate}`;
            } else {
                displayEval = (evalVal >= 0 ? '+' : '') + evalVal;
            }

            evalScore.textContent = displayEval;
            evalDepth.textContent = `depth ${data.depth || '?'}`;

            updateEvalBar(cp, mate);

            if (data.best_move) {
                try {
                    const tmpBoard = new Chess(fen);
                    const m = tmpBoard.move({ from: data.best_move.substring(0, 2), to: data.best_move.substring(2, 4), promotion: data.best_move.length > 4 ? data.best_move[4] : undefined });
                    bestMoveText.textContent = m ? `Best: ${m.san}` : '';
                } catch { bestMoveText.textContent = `Best: ${data.best_move}`; }
            } else {
                bestMoveText.textContent = '';
            }

            const container = document.getElementById('engineLinesContainer');
            if (container) {
                if (data.lines && data.lines.length > 0) {
                    container.innerHTML = data.lines.map(l => {
                        const val = l.mate ? `M${l.mate}` : (l.evaluation > 0 ? '+' : '') + l.evaluation;
                        const pvstr = (l.pv_san && l.pv_san.length > 0) ? l.pv_san.join(' ') : (l.pv || []).join(' ');
                        return `<div class="ab-engine-line"><div class="line-eval">${val}</div><div class="line-pv" title="${pvstr}">${pvstr}</div></div>`;
                    }).join('');
                } else {
                    container.innerHTML = '';
                }
            }

            setStatus('success', 'Position analyzed.');
        } catch (err) {
            setStatus('error', 'Analysis failed: ' + err.message);
        }
        analyzing = false;
    }

    function updateEvalBar(cp, mate) {
        const fillEl = document.getElementById('evalBarFill');
        if (!fillEl) return;

        let winPct = 50; // default 0.0 is 50%
        if (mate !== null && mate !== undefined) {
            winPct = mate > 0 ? 100 : 0;
            if (mate === 0 && game.turn() === 'w') winPct = 0; // white mated
            if (mate === 0 && game.turn() === 'b') winPct = 100; // black mated
        } else {
            // cp logic: 100cp = 1 pawn. clamp between -800 and 800 roughly.
            const w = 2 / (1 + Math.exp(-0.00368208 * cp)) - 1; // sigmoid function centered at 0
            winPct = 50 + (w * 50);
        }

        // if board is flipped, the visual represents black from the bottom.
        if (orientation === 'black') {
            winPct = 100 - winPct;
            fillEl.style.backgroundColor = '#403e3c'; // dark fill
            fillEl.parentElement.style.backgroundColor = '#fff'; // light bg
        } else {
            fillEl.style.backgroundColor = '#fff'; // light fill
            fillEl.parentElement.style.backgroundColor = '#403e3c'; // dark bg
        }

        fillEl.style.height = `${winPct}%`;
    }

    // ── Navigation ──
    function goTo(ply) {
        ply = Math.max(0, Math.min(ply, positions.length - 1));
        currentPly = ply;
        game = new Chess(positions[ply]);
        board.position(game.fen(), false);
        highlightMove(ply);
        analyzePosition(game.fen());
    }

    document.getElementById('abBtnStart').addEventListener('click', () => goTo(0));
    document.getElementById('abBtnPrev').addEventListener('click', () => goTo(currentPly - 1));
    document.getElementById('abBtnNext').addEventListener('click', () => goTo(currentPly + 1));
    document.getElementById('abBtnEnd').addEventListener('click', () => goTo(positions.length - 1));
    document.getElementById('abBtnFlip').addEventListener('click', () => {
        orientation = orientation === 'white' ? 'black' : 'white';
        board.orientation(orientation);
        analyzePosition(game.fen()); // re-trigger to update eval bar orientation
    });

    // Keyboard nav
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.key === 'ArrowLeft') goTo(currentPly - 1);
        if (e.key === 'ArrowRight') goTo(currentPly + 1);
        if (e.key === 'Home') goTo(0);
        if (e.key === 'End') goTo(positions.length - 1);
    });

    // ── Move list rendering ──
    function renderMoveList() {
        if (positions.length <= 1) {
            moveListCard.style.display = 'none';
            return;
        }
        moveListCard.style.display = 'block';

        // Rebuild game from positions to get SAN notation
        const tmpGame = new Chess(positions[0]);
        let html = '';
        let moveNum = 1;

        for (let i = 1; i < positions.length; i++) {
            const prevGame = new Chess(positions[i - 1]);
            const nextGame = new Chess(positions[i]);

            // Figure out what move was made
            const legalMoves = prevGame.moves({ verbose: true });
            const move = legalMoves.find(m => {
                const test = new Chess(positions[i - 1]);
                test.move(m);
                return test.fen().split(' ').slice(0, 4).join(' ') === nextGame.fen().split(' ').slice(0, 4).join(' ');
            });
            const san = move ? move.san : '?';

            if (i % 2 === 1) {
                // White's move — start new row
                html += `<div class="ab-move-row"><span class="ab-move-num">${moveNum}.</span>`;
                html += `<span class="ab-move-cell${currentPly === i ? ' active' : ''}" data-ply="${i}">${san}</span>`;
            } else {
                // Black's move
                html += `<span class="ab-move-cell${currentPly === i ? ' active' : ''}" data-ply="${i}">${san}</span></div>`;
                moveNum++;
            }
        }
        // Close row if last was white
        if (positions.length % 2 === 0) {
            html += '<span class="ab-move-cell" style="visibility:hidden;">—</span></div>';
            // adjust moveNum not needed
        }

        moveList.innerHTML = html;

        // Click to navigate
        moveList.querySelectorAll('.ab-move-cell[data-ply]').forEach(cell => {
            cell.addEventListener('click', () => goTo(parseInt(cell.dataset.ply)));
        });

        // Scroll active into view
        const active = moveList.querySelector('.ab-move-cell.active');
        if (active) active.scrollIntoView({ block: 'nearest' });
    }

    function highlightMove(ply) {
        moveList.querySelectorAll('.ab-move-cell').forEach(c => c.classList.remove('active'));
        const cell = moveList.querySelector(`.ab-move-cell[data-ply="${ply}"]`);
        if (cell) {
            cell.classList.add('active');
            cell.scrollIntoView({ block: 'nearest' });
        }
    }

    // ── Status helper ──
    function setStatus(type, msg) {
        statusEl.className = 'ab-status ' + type;
        const icon = type === 'loading' ? '<div class="spinner"></div>'
            : type === 'success' ? '<i class="bi bi-check-circle"></i>'
            : type === 'error' ? '<i class="bi bi-exclamation-circle"></i>'
            : '<i class="bi bi-info-circle"></i>';
        statusText.innerHTML = msg;
        statusEl.querySelector('i, .spinner')?.remove();
        statusEl.insertAdjacentHTML('afterbegin', icon);
    }

    // ── PGN Mode ──
    const btnLoadPgn = document.getElementById('btnLoadPgn');
    const btnClearPgn = document.getElementById('btnClearPgn');
    const pgnInput = document.getElementById('pgnInput');

    if (btnLoadPgn) {
        btnLoadPgn.addEventListener('click', () => {
            const pgn = (pgnInput.value || '').trim();
            if (!pgn) {
                setStatus('error', 'Please paste a PGN first.');
                return;
            }

            const tmpGame = new Chess();
            const success = tmpGame.load_pgn(pgn);
            if (!success) {
                setStatus('error', 'Invalid PGN format. Please check and try again.');
                return;
            }

            // Rebuild positions
            const gameFromStart = new Chess();
            const moves = tmpGame.history();
            positions = [gameFromStart.fen()];

            moves.forEach(san => {
                gameFromStart.move(san);
                positions.push(gameFromStart.fen());
            });

            game = new Chess(positions[0]);
            currentPly = 0;
            board.position(game.fen(), false);
            renderMoveList();
            analyzePosition(game.fen());

            // Hide input card, show success
            document.getElementById('pgnInputCard').style.display = 'none';
            setStatus('success', `Loaded ${moves.length} moves. Use arrows or click moves to navigate.`);
        });

        btnClearPgn.addEventListener('click', () => {
            pgnInput.value = '';
            document.getElementById('pgnInputCard').style.display = 'block';
            initBoard();
            setStatus('info', 'Paste a PGN above and click "Load & Analyze".');
        });
    }

    // ── FEN Mode ──
    const btnLoadFen = document.getElementById('btnLoadFen');
    const btnResetFen = document.getElementById('btnResetFen');
    const fenInput = document.getElementById('fenInput');

    if (btnLoadFen) {
        btnLoadFen.addEventListener('click', () => {
            const fen = (fenInput.value || '').trim();
            if (!fen) {
                setStatus('error', 'Please enter a FEN string.');
                return;
            }

            try {
                const testGame = new Chess(fen);
                if (!testGame) throw new Error('Invalid');
            } catch {
                setStatus('error', 'Invalid FEN string. Please check the format.');
                return;
            }

            isSettingUp = false; // Switch to analysis mode
            initBoard(fen);
            setStatus('success', 'Position loaded. Make moves to explore or view the engine evaluation.');
        });

        btnResetFen.addEventListener('click', () => {
            fenInput.value = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
            isSettingUp = true;
            initBoard('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1');
            setStatus('info', 'Position reset. Drag pieces on or off the board.');
        });
    }

    // ── New Game Mode ──
    const btnResetBoard = document.getElementById('btnResetBoard');
    if (btnResetBoard) {
        btnResetBoard.addEventListener('click', () => {
            initBoard();
            setStatus('info', 'Board reset. Make a move to begin analysis.');
        });
    }

    // ── Window resize ──
    window.addEventListener('resize', () => { if (board) board.resize(); });

    // ── Boot ──
    initBoard();
});
