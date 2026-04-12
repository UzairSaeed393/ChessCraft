(() => {
    const root = document.querySelector('.review-shell');
    if (!root) {
        return;
    }

    const gameId = Number.parseInt(root.dataset.gameId || '', 10);
    if (!Number.isInteger(gameId)) {
        return;
    }

    const categoryOrder = [
        'brilliant',
        'great',
        'best',
        'excellent',
        'good',
        'book',
        'inaccuracy',
        'miss',
        'mistake',
        'blunder',
    ];

    const categoryLabel = {
        book: 'Book',
        brilliant: 'Brilliant',
        great: 'Great',
        best: 'Best',
        excellent: 'Excellent',
        good: 'Good',
        inaccuracy: 'Inaccuracy',
        miss: 'Miss',
        mistake: 'Mistake',
        blunder: 'Blunder',
    };

    const categoryIcon = {
        book: 'bi-book-fill',
        brilliant: 'bi-lightning-fill',
        great: 'bi-stars',
        best: 'bi-check-circle-fill',
        excellent: 'bi-check2-circle',
        good: 'bi-check2',
        inaccuracy: 'bi-exclamation-triangle-fill',
        miss: 'bi-x-diamond-fill',
        mistake: 'bi-x-circle-fill',
        blunder: 'bi-exclamation-octagon-fill',
    };

    const state = {
        reviewData: null,
        positions: [],
        currentPly: 0,
        currentFen: 'start',
        inVariation: false,
        chart: null,
        board: null,
        progressInterval: null,
    };

    const el = {
        summaryPanel: document.getElementById('summaryPanel'),
        summaryText: document.getElementById('summaryText'),
        reviewProgress: document.getElementById('reviewProgress'),
        startReviewBtn: document.getElementById('startReviewBtn'),
        finishReviewBtn: document.getElementById('finishReviewBtn'),
        reviewStage: document.getElementById('reviewStage'),
        whiteName: document.getElementById('whiteName'),
        blackName: document.getElementById('blackName'),
        whiteAcc: document.getElementById('whiteAcc'),
        blackAcc: document.getElementById('blackAcc'),
        whiteRating: document.getElementById('whiteRating'),
        blackRating: document.getElementById('blackRating'),
        whiteGameRating: document.getElementById('whiteGameRating'),
        blackGameRating: document.getElementById('blackGameRating'),
        breakdownRows: document.getElementById('breakdownRows'),
        phaseOpeningWhite: document.getElementById('phaseOpeningWhite'),
        phaseOpeningBlack: document.getElementById('phaseOpeningBlack'),
        phaseMiddleWhite: document.getElementById('phaseMiddleWhite'),
        phaseMiddleBlack: document.getElementById('phaseMiddleBlack'),
        phaseEndWhite: document.getElementById('phaseEndWhite'),
        phaseEndBlack: document.getElementById('phaseEndBlack'),
        evalFill: document.getElementById('eval-fill'),
        evalScore: document.getElementById('eval-score'),
        moveTitle: document.getElementById('moveTitle'),
        moveClass: document.getElementById('moveClass'),
        moveDesc: document.getElementById('moveDesc'),
        bestMove: document.getElementById('bestMove'),
        followLine: document.getElementById('followLine'),
        resetLineBtn: document.getElementById('resetLineBtn'),
        moveList: document.getElementById('moveList'),
        chartCanvas: document.getElementById('reviewChart'),
        openingInfo: document.getElementById('openingInfo'),
        btnStart: document.getElementById('btnStart'),
        btnPrev: document.getElementById('btnPrev'),
        btnNext: document.getElementById('btnNext'),
        btnEnd: document.getElementById('btnEnd'),
    };

    function startProgress() {
        let width = 0;
        el.reviewProgress.style.width = '0%';
        state.progressInterval = setInterval(() => {
            if (width < 92) {
                width += (95 - width) * 0.05;
                el.reviewProgress.style.width = `${width}%`;
            }
        }, 400);
    }

    function finishProgress() {
        clearInterval(state.progressInterval);
        el.reviewProgress.style.width = '100%';
        setTimeout(() => {
            el.reviewProgress.parentElement.style.opacity = '0';
        }, 1000);
    }

    function renderSummary(summary, evalHistory) {
        el.whiteName.textContent = summary.players.white.name || 'White';
        el.blackName.textContent = summary.players.black.name || 'Black';
        el.whiteAcc.textContent = `${Math.round(summary.players.white.accuracy)}%`;
        el.blackAcc.textContent = `${Math.round(summary.players.black.accuracy)}%`;

        if (el.whiteRating) el.whiteRating.textContent = summary.players.white.rating ?? '--';
        if (el.blackRating) el.blackRating.textContent = summary.players.black.rating ?? '--';
        if (el.whiteGameRating) el.whiteGameRating.textContent = summary.players.white.rating_estimate ?? '--';
        if (el.blackGameRating) el.blackGameRating.textContent = summary.players.black.rating_estimate ?? '--';

        el.phaseOpeningWhite.textContent = `${Math.round(summary.phase_accuracy.white.opening)}%`;
        el.phaseOpeningBlack.textContent = `${Math.round(summary.phase_accuracy.black.opening)}%`;
        el.phaseMiddleWhite.textContent = `${Math.round(summary.phase_accuracy.white.middlegame)}%`;
        el.phaseMiddleBlack.textContent = `${Math.round(summary.phase_accuracy.black.middlegame)}%`;
        el.phaseEndWhite.textContent = `${Math.round(summary.phase_accuracy.white.endgame)}%`;
        el.phaseEndBlack.textContent = `${Math.round(summary.phase_accuracy.black.endgame)}%`;

        if (el.openingInfo) {
            el.openingInfo.textContent = summary.opening_name || '--';
        }

        renderBreakdown(summary.counts);
        initChart(evalHistory);
    }

    function escapeHtml(value) {
        return String(value)
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('\"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    function pieceFromSan(san) {
        const text = String(san || '');
        if (text.startsWith('O-O')) return 'K';
        const promotion = text.match(/=([QRBN])/);
        if (promotion?.[1]) return promotion[1];
        const head = text.charAt(0);
        if ('KQRBN'.includes(head)) return head;
        return 'P';
    }

    function sanDisplayText(san) {
        const text = String(san || '');
        const head = text.charAt(0);
        if ('KQRBN'.includes(head)) return text.slice(1);
        return text;
    }

    function movePieceImgHtml(move) {
        const piece = pieceFromSan(move?.san);
        const side = move?.side === 'black' ? 'b' : 'w';
        const url = `https://chessboardjs.com/img/chesspieces/wikipedia/${side}${piece}.png`;
        return `<img class="move-piece" src="${url}" alt="${piece}" loading="lazy">`;
    }

    function clearBoardHighlights() {
        const squares = document.querySelectorAll('#mainBoard .square-55d63');
        squares.forEach((sq) => sq.classList.remove('highlight-from', 'highlight-to'));
    }

    function clearBoardAnnotations() {
        const markers = document.querySelectorAll('#mainBoard .move-annotation');
        markers.forEach((node) => node.remove());
    }

    function annotateSquare(square, classification) {
        if (!square) return;
        const sqEl = document.querySelector(`#mainBoard .square-${square}`);
        if (!sqEl) {
            // Retry once if chessboard.js hasn't finished rendering the DOM
            setTimeout(() => annotateSquare(square, classification), 50);
            return;
        }

        const key = String(classification || '').trim();
        const icon = categoryIcon[key] || 'bi-dot';

        const marker = document.createElement('div');
        marker.className = `move-annotation chip-${key || 'good'}`;
        marker.innerHTML = `<i class="bi ${icon}"></i>`;
        sqEl.appendChild(marker);
    }

    function highlightSquare(square, className) {
        if (!square) return;
        const sqEl = document.querySelector(`#mainBoard .square-${square}`);
        if (sqEl) sqEl.classList.add(className);
    }

    function highlightUciMove(uci, classification) {
        clearBoardHighlights();
        clearBoardAnnotations();
        if (!uci || typeof uci !== 'string' || uci.length < 4) return;
        const from = uci.slice(0, 2);
        const to = uci.slice(2, 4);
        highlightSquare(from, 'highlight-from');
        highlightSquare(to, 'highlight-to');
        
        // Slight delay to ensure board re-rendering doesn't wipe the annotation
        setTimeout(() => annotateSquare(to, classification), 0);
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i += 1) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === `${name}=`) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify(payload),
        });

        const data = await response.json();
        if (!response.ok || data.error) {
            throw new Error(data.error || 'Request failed');
        }
        return data;
    }

    function formatEval(value) {
        const num = Number(value || 0);
        const text = num.toFixed(2);
        return num > 0 ? `+${text}` : text;
    }

    function setEvalBar(evalValue) {
        const v = Number(evalValue || 0);
        const height = Math.max(4, Math.min(96, 50 + (v * 7)));
        if (el.evalFill) {
            el.evalFill.style.height = `${height}%`;
        }
        if (el.evalScore) {
            el.evalScore.textContent = formatEval(v);
        }
    }

    function initChart(evalHistory) {
        if (!el.chartCanvas) return;
        const ctx = el.chartCanvas.getContext('2d');
        if (state.chart) {
            state.chart.destroy();
        }
        state.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: evalHistory.map((_, i) => i + 1),
                datasets: [
                    {
                        data: evalHistory,
                        borderColor: '#81b64c',
                        backgroundColor: 'rgba(129, 182, 76, 0.2)',
                        fill: true,
                        tension: 0.32,
                        pointRadius: 0,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    x: { display: false },
                    y: { display: false, min: -9, max: 9 },
                },
            },
        });
    }

    function renderBreakdown(counts) {
        el.breakdownRows.innerHTML = '';
        categoryOrder.forEach((key) => {
            const row = document.createElement('div');
            row.className = 'breakdown-row';
            const whiteCount = counts.white?.[key] || 0;
            const blackCount = counts.black?.[key] || 0;
            row.innerHTML = `
                <div class="chip-${key}"><i class="bi ${categoryIcon[key] || 'bi-dot'}"></i><span>${categoryLabel[key]}</span></div>
                <span>${whiteCount}</span>
                <span>${blackCount}</span>
            `;
            el.breakdownRows.appendChild(row);
        });
    }

    function createMoveButton(move) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'move-item';
        btn.dataset.ply = String(move.ply);

        const sidePrefix = move.side === 'white' ? `${move.move_number}.` : `${move.move_number}...`;
        const icon = categoryIcon[move.classification] || 'bi-dot';
        btn.innerHTML = `
            <span>${escapeHtml(sidePrefix)} ${movePieceImgHtml(move)} ${escapeHtml(sanDisplayText(move.san))}</span>
            <div class="chip-${move.classification}"><i class="bi ${icon}"></i><span>${categoryLabel[move.classification] || move.classification}</span></div>
        `;
        return btn;
    }

    function renderMoveList(moves) {
        el.moveList.innerHTML = '';
        moves.forEach((move) => {
            el.moveList.appendChild(createMoveButton(move));
        });
    }

    function setMoveDetails(move) {
        el.moveTitle.textContent = `Move ${move.move_number} (${move.side})`;
        const icon = categoryIcon[move.classification] || 'bi-dot';
        el.moveClass.innerHTML = `Category: <div class="chip-${move.classification}"><i class="bi ${icon}"></i><span>${categoryLabel[move.classification] || move.classification}</span></div>`;
        el.moveDesc.textContent = move.explanation || 'No explanation available.';
        el.bestMove.textContent = move.best_move_san || move.best_move || '--';
        el.followLine.textContent = move.follow_line?.join(' ') || '--';
    }

    function markActiveMove(ply) {
        const items = el.moveList.querySelectorAll('.move-item');
        items.forEach((item) => {
            item.classList.toggle('active', parseInt(item.dataset.ply || '0') === ply);
        });
    }

    function showMainlinePly(ply) {
        if (!state.reviewData) return;

        const maxPly = state.positions.length - 1;
        const targetPly = Math.max(0, Math.min(maxPly, ply));
        state.currentPly = targetPly;
        state.inVariation = false;

        const fen = state.positions[targetPly];
        state.currentFen = fen;
        state.board.position(fen, false); // false to disable animation and stop blinking

        if (targetPly === 0) {
            el.moveTitle.textContent = 'Initial Position';
            el.moveClass.textContent = 'Category: --';
            el.moveDesc.textContent = 'Navigate moves or drag a piece to test alternatives.';
            el.bestMove.textContent = '--';
            el.followLine.textContent = '--';
            setEvalBar(0);
            clearBoardHighlights();
            clearBoardAnnotations();
        } else {
            const move = state.reviewData.moves[targetPly - 1];
            setMoveDetails(move);
            setEvalBar(move.evaluation_after);
            highlightUciMove(move.uci, move.classification);
        }

        el.resetLineBtn.hidden = true;
        markActiveMove(targetPly);
    }

    async function analyzeVariation(baseFen, moveUci) {
        el.moveDesc.textContent = 'Analyzing your candidate move...';
        const data = await postJson('/analysis/api/variation/', {
            fen: baseFen,
            move: moveUci,
        });

        state.inVariation = true;
        state.currentFen = data.after_fen;
        state.board.position(data.after_fen, false);

        el.moveTitle.textContent = 'Alternative Move Review';
        const icon = categoryIcon[data.classification] || 'bi-dot';
        el.moveClass.innerHTML = `Category: <div class="chip-${data.classification}"><i class="bi ${icon}"></i><span>${categoryLabel[data.classification] || data.classification}</span></div>`;
        el.moveDesc.textContent = data.explanation || 'No explanation available.';
        el.bestMove.textContent = data.best_line?.[0] || data.best_move || '--';
        el.followLine.textContent = data.follow_line?.join(' ') || '--';
        setEvalBar(data.evaluation);
        el.resetLineBtn.hidden = false;
        highlightUciMove(moveUci, data.classification);
    }

    function onDrop(source, target) {
        if (!state.reviewData) return 'snapback';

        const game = new Chess(state.currentFen);
        const move = game.move({
            from: source,
            to: target,
            promotion: 'q',
        });

        if (!move) return 'snapback';

        const moveUci = `${move.from}${move.to}${move.promotion || ''}`;
        analyzeVariation(state.currentFen, moveUci).catch((error) => {
            el.moveDesc.textContent = error.message || 'Failed to analyze variation.';
            state.board.position(state.currentFen, false);
        });

        return undefined;
    }

    function initBoard() {
        state.board = Chessboard('mainBoard', {
            draggable: true,
            position: 'start',
            onDrop,
            pieceTheme: 'https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png',
            moveSpeed: 'fast',
            snapbackSpeed: 50,
            snapSpeed: 50,
        });
    }

    function bindEvents() {
        el.startReviewBtn.addEventListener('click', () => {
            el.summaryPanel.classList.add('fade-out');
            setTimeout(() => {
                el.summaryPanel.classList.add('hidden');
                el.reviewStage.hidden = false;
                el.reviewStage.style.opacity = '0';
                setTimeout(() => {
                    el.reviewStage.style.opacity = '1';
                    state.board.resize();
                    showMainlinePly(0);
                }, 50);
            }, 400);
        });

        el.btnStart.addEventListener('click', () => showMainlinePly(0));
        el.btnPrev.addEventListener('click', () => showMainlinePly(state.currentPly - 1));
        el.btnNext.addEventListener('click', () => showMainlinePly(state.currentPly + 1));
        el.btnEnd.addEventListener('click', () => showMainlinePly(state.positions.length - 1));

        el.resetLineBtn.addEventListener('click', () => showMainlinePly(state.currentPly));

        el.finishReviewBtn.addEventListener('click', () => {
            const finishUrl = root.dataset.finishUrl || '/user/game/';
            window.location.assign(finishUrl);
        });

        el.moveList.addEventListener('click', (event) => {
            const btn = event.target.closest('.move-item');
            if (!btn) return;
            const ply = parseInt(btn.dataset.ply || '0');
            showMainlinePly(ply);
        });

        window.addEventListener('resize', () => {
            if (state.board) state.board.resize();
        });
    }

    async function loadReviewData() {
        el.summaryText.textContent = 'Analyzing your game...';
        startProgress();
        
        try {
            const data = await postJson('/analysis/api/review/start/', {
                game_id: gameId,
            });

            state.reviewData = data;
            state.positions = [data.start_fen, ...data.moves.map((item) => item.fen_after)];
            state.currentFen = data.start_fen;

            renderSummary(data.summary, data.eval_history);
            renderMoveList(data.moves);
            finishProgress();

            const side = data.summary?.user_side === 'black' ? 'black' : 'white';
            state.board.orientation(side);

            el.startReviewBtn.disabled = false;
            el.summaryText.textContent = 'Game analysis complete.';
        } catch (err) {
            clearInterval(state.progressInterval);
            throw err;
        }
    }

    initBoard();
    bindEvents();

    loadReviewData().catch((error) => {
        el.summaryText.textContent = error.message || 'Could not generate review.';
    });
})();