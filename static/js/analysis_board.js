/* ============================================================
   analysis_board.js — Shared analysis board logic
   Supports: PGN paste, FEN setup, New Game (free explore)
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {

    // ── State ──
    let game = new Chess();
    let board = null;
    let orientation = 'white';
    // Multi-line move history (mainline + variations)
    // Each line stores its own FEN sequence; branching creates a new line instead of deleting future moves.
    let lines = [];
    let nextLineId = 1;
    let currentLineId = 0;
    let currentPly = 0; // index into line.fens
    let analyzing = false;
    let isSettingUp = window.ANALYSIS_MODE === 'fen';

    // ── DOM refs ──
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

    function fenKey(fen) {
        return String(fen || '').split(' ').slice(0, 4).join(' ');
    }

    function getCurrentLine() {
        return lines.find(l => l.id === currentLineId) || lines[0];
    }

    function resetLinesFromFen(fen) {
        const startFen = fen || game.fen();
        lines = [{
            id: 0,
            parentId: null,
            branchPly: 0,
            fens: [startFen],
            sans: [],
            ucis: [],
        }];
        nextLineId = 1;
        currentLineId = 0;
        currentPly = 0;
    }

    function findExistingLineForBranch(baseLine, branchPly, afterFen) {
        const targetKey = fenKey(afterFen);
        const prefixKeys = baseLine.fens.slice(0, branchPly + 1).map(fenKey);

        return lines.find(l => {
            if (l.fens.length <= branchPly + 1) return false;
            for (let i = 0; i <= branchPly; i++) {
                if (fenKey(l.fens[i]) !== prefixKeys[i]) return false;
            }
            return fenKey(l.fens[branchPly + 1]) === targetKey;
        });
    }

    // ── Init Board ──
    function initBoard(fen) {
        game = new Chess(fen || undefined);
        resetLinesFromFen(game.fen());

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
            analyzePosition(getCurrentLine().fens[currentPly]);
        } else {
            // Hide engine UI elements in setup mode
            const linesContainer = document.getElementById('engineLinesContainer');
            if (linesContainer) linesContainer.innerHTML = '';
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

        const line = getCurrentLine();
        const baseFen = line.fens[currentPly];
        game = new Chess(baseFen);

        const move = game.move({ from: source, to: target, promotion: 'q' });
        if (!move) return 'snapback';

        const afterFen = game.fen();
        const uci = `${move.from}${move.to}${move.promotion || ''}`;

        const atEnd = currentPly === line.fens.length - 1;
        if (atEnd) {
            line.sans.push(move.san);
            line.ucis.push(uci);
            line.fens.push(afterFen);
            currentPly = line.fens.length - 1;
        } else {
            const forwardKey = fenKey(line.fens[currentPly + 1]);
            if (fenKey(afterFen) === forwardKey) {
                // User played the existing mainline move — just advance
                currentPly += 1;
            } else {
                const existing = findExistingLineForBranch(line, currentPly, afterFen);
                if (existing) {
                    currentLineId = existing.id;
                    currentPly += 1;
                } else {
                    // Create a new variation line instead of truncating the current one
                    const newLine = {
                        id: nextLineId++,
                        parentId: line.id,
                        branchPly: currentPly,
                        fens: line.fens.slice(0, currentPly + 1),
                        sans: line.sans.slice(0, currentPly),
                        ucis: line.ucis.slice(0, currentPly),
                    };
                    newLine.sans.push(move.san);
                    newLine.ucis.push(uci);
                    newLine.fens.push(afterFen);

                    lines.push(newLine);
                    currentLineId = newLine.id;
                    currentPly = newLine.fens.length - 1;
                }
            }
        }

        renderMoveList();
        analyzePosition(getCurrentLine().fens[currentPly]);
    }

    // ── Format a PV line for display ──
    function formatPvLine(pvSan, startPly) {
        if (!pvSan || pvSan.length === 0) return '';
        let out = '';
        let moveNum = Math.floor(startPly / 2) + 1;
        let isWhite = (startPly % 2 === 0);
        for (let i = 0; i < pvSan.length; i++) {
            if (isWhite) {
                out += `${moveNum}. ${pvSan[i]} `;
            } else {
                if (i === 0) out += `${moveNum}... `;
                out += `${pvSan[i]} `;
                moveNum++;
            }
            if (isWhite) {
                // After white move, next is black (same moveNum)
                isWhite = false;
            } else {
                isWhite = true;
            }
        }
        return out.trim();
    }

    // ── Format eval for display ──
    function formatEval(cp, mate) {
        if (mate !== null && mate !== undefined) {
            return `M${mate}`;
        }
        const ev = (cp / 100).toFixed(1);
        return (cp >= 0 ? '+' : '') + ev;
    }

    // ── Position analysis ──
    async function analyzePosition(fen) {
        if (analyzing) return;
        analyzing = true;
        setStatus('loading', 'Analyzing position...');

        try {
            const data = await postJson('/analysis/api/analyze/', { fen, multipv: 3 });

            const engineLines = data.lines || [];
            const topLine = engineLines[0] || data;
            const secondLine = engineLines[1] || null;

            const cp = topLine.evaluation_cp || 0;
            const mate = topLine.mate;
            const displayEval = formatEval(cp, mate);

            // 1. Update Eval Bar score overlay
            const scoreTop = document.getElementById('evalBarScoreTop');
            const scoreBottom = document.getElementById('evalBarScoreBottom');
            if (scoreTop && scoreBottom) {
                const isWhiteAdv = (mate !== null && mate !== undefined) ? mate > 0 : cp > 0;
                if (orientation === 'white') {
                    scoreTop.textContent = isWhiteAdv ? '' : displayEval;
                    scoreBottom.textContent = isWhiteAdv ? displayEval : '';
                } else {
                    scoreTop.textContent = isWhiteAdv ? displayEval : '';
                    scoreBottom.textContent = isWhiteAdv ? '' : displayEval;
                }
            }

            updateEvalBar(cp, mate);

            // 2. Update Engine Lines above the board (2 lines)
            const linesContainer = document.getElementById('engineLinesContainer');
            if (linesContainer) {
                let linesHtml = '';

                // Line 1: Top engine move
                if (topLine) {
                    const topEval = formatEval(topLine.evaluation_cp || 0, topLine.mate);
                    const topPvSan = topLine.pv_san || [];
                    const topPvFormatted = formatPvLine(topPvSan, currentPly);
                    linesHtml += `
                        <div class="ab-engine-line">
                            <span class="line-rank">1</span>
                            <span class="line-eval">${topEval}</span>
                            <span class="line-pv">${topPvFormatted || '...'}</span>
                        </div>`;
                }

                // Line 2: Second best engine move
                if (secondLine) {
                    const secEval = formatEval(secondLine.evaluation_cp || 0, secondLine.mate);
                    const secPvSan = secondLine.pv_san || [];
                    const secPvFormatted = formatPvLine(secPvSan, currentPly);
                    linesHtml += `
                        <div class="ab-engine-line">
                            <span class="line-rank">2</span>
                            <span class="line-eval">${secEval}</span>
                            <span class="line-pv">${secPvFormatted || '...'}</span>
                        </div>`;
                }

                linesContainer.innerHTML = linesHtml;
                linesContainer.style.display = linesHtml ? 'flex' : 'none';
            }

            setStatus('success', 'Position analyzed.');
        } catch (err) {
            setStatus('error', 'Analysis failed: ' + err.message);
            // Clear engine lines on failure
            const linesContainer = document.getElementById('engineLinesContainer');
            if (linesContainer) { linesContainer.innerHTML = ''; linesContainer.style.display = 'none'; }
            // Clear bar overlay scores
            ['evalBarScoreTop', 'evalBarScoreBottom'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = '';
            });
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
        const line = getCurrentLine();
        ply = Math.max(0, Math.min(ply, line.fens.length - 1));
        currentPly = ply;
        game = new Chess(line.fens[ply]);
        board.position(line.fens[ply], false);
        highlightMove(currentLineId, ply);
        analyzePosition(line.fens[ply]);
    }

    function goToLinePly(lineId, ply) {
        const line = lines.find(l => l.id === lineId);
        if (!line) return;
        currentLineId = lineId;
        goTo(ply);
    }

    document.getElementById('abBtnStart').addEventListener('click', () => goTo(0));
    document.getElementById('abBtnPrev').addEventListener('click', () => goTo(currentPly - 1));
    document.getElementById('abBtnNext').addEventListener('click', () => goTo(currentPly + 1));
    document.getElementById('abBtnEnd').addEventListener('click', () => {
        const line = getCurrentLine();
        goTo(line.fens.length - 1);
    });
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
        if (e.key === 'End') {
            const line = getCurrentLine();
            goTo(line.fens.length - 1);
        }
    });

    // ── Move list rendering ──
    function renderMoveList() {
        const main = lines.find(l => l.id === 0) || getCurrentLine();
        if (!main || main.fens.length <= 1) {
            moveListCard.style.display = 'none';
            return;
        }
        moveListCard.style.display = 'block';

        function renderLine(line, startPly, isVariation) {
            if (!line || line.fens.length <= startPly) return '';
            let html = '';
            let openRow = false;
            let lastPlyRendered = null;

            for (let ply = startPly; ply < line.fens.length; ply++) {
                lastPlyRendered = ply;
                const san = line.sans[ply - 1] || '?';
                const isActive = (line.id === currentLineId && ply === currentPly);
                const cellHtml = `<span class="ab-move-cell${isActive ? ' active' : ''}" data-line-id="${line.id}" data-ply="${ply}">${san}</span>`;

                if (ply % 2 === 1) {
                    // White move starts a row
                    const moveNum = Math.ceil(ply / 2);
                    html += `<div class="ab-move-row"><span class="ab-move-num">${moveNum}.</span>`;
                    html += cellHtml;
                    openRow = true;
                } else {
                    const moveNum = ply / 2;
                    if (!openRow) {
                        // Variation can start on black to move
                        html += `<div class="ab-move-row"><span class="ab-move-num">${moveNum}...</span>`;
                        html += '<span class="ab-move-cell" style="visibility:hidden;">—</span>';
                        html += cellHtml;
                        html += '</div>';
                    } else {
                        // Black move closes the row
                        html += cellHtml + '</div>';
                    }
                    openRow = false;
                }
            }

            if (openRow && lastPlyRendered !== null) {
                html += '<span class="ab-move-cell" style="visibility:hidden;">—</span></div>';
            }

            const cls = isVariation ? 'ab-line-block variation' : 'ab-line-block';
            return `<div class="${cls}">${html}</div>`;
        }

        let html = '';
        html += renderLine(main, 1, false);

        const variations = lines.filter(l => l.id !== main.id);
        if (variations.length > 0) {
            variations.sort((a, b) => a.id - b.id);
            variations.forEach((line, idx) => {
                const branchMovePly = (line.branchPly || 0) + 1;
                const moveNum = Math.ceil(branchMovePly / 2);
                const suffix = branchMovePly % 2 === 1 ? '.' : '...';
                html += `<div class="ab-line-title">Variation ${idx + 1} (from ${moveNum}${suffix})</div>`;
                html += renderLine(line, branchMovePly, true);
            });
        }

        moveList.innerHTML = html;

        // Click to navigate (ply within the clicked line)
        moveList.querySelectorAll('.ab-move-cell[data-line-id][data-ply]').forEach(cell => {
            cell.addEventListener('click', () => {
                const lid = parseInt(cell.dataset.lineId || '0', 10);
                const ply = parseInt(cell.dataset.ply || '0', 10);
                goToLinePly(lid, ply);
            });
        });

        const active = moveList.querySelector('.ab-move-cell.active');
        if (active) {
            moveList.scrollTop = active.offsetTop - (moveList.clientHeight / 2);
        }
    }

    function highlightMove(lineId, ply) {
        moveList.querySelectorAll('.ab-move-cell').forEach(c => c.classList.remove('active'));
        const cell = moveList.querySelector(`.ab-move-cell[data-line-id="${lineId}"][data-ply="${ply}"]`);
        if (cell) {
            cell.classList.add('active');
            moveList.scrollTop = cell.offsetTop - (moveList.clientHeight / 2);
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

            // Rebuild mainline (line 0)
            const gameFromStart = new Chess();
            const moves = tmpGame.history({ verbose: true });
            resetLinesFromFen(gameFromStart.fen());
            const line0 = getCurrentLine();

            moves.forEach(m => {
                gameFromStart.move(m);
                line0.sans.push(m.san);
                line0.ucis.push(`${m.from}${m.to}${m.promotion || ''}`);
                line0.fens.push(gameFromStart.fen());
            });

            game = new Chess(line0.fens[0]);
            currentLineId = 0;
            currentPly = 0;
            board.position(line0.fens[0], false);
            renderMoveList();
            analyzePosition(line0.fens[0]);

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

            const testGame = new Chess();
            const validation = testGame.validate_fen(fen);

            if (!validation.valid) {
                // Customized user-friendly messages for common errors
                let msg = 'Invalid position: ' + validation.error;
                if (validation.error_number === 5) msg = 'Invalid FEN: Each side must have exactly one King.';
                if (validation.error_number === 7) msg = 'Invalid position: Opponent King is in check (impossible state).';
                
                setStatus('error', msg);
                return;
            }

            // check_js validate_fen(5) is "more than one king" or "no king". 
            // Let's be extra explicit about missing kings just in case.
            if (fen.indexOf('k') === -1 || fen.indexOf('K') === -1) {
                setStatus('error', 'Invalid position: Both players must have a King.');
                return;
            }

            isSettingUp = false; // Switch to analysis mode
            initBoard(fen);
            setStatus('success', 'Position loaded. Use the engine to evaluate.');
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
