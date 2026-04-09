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
        'inaccuracy',
        'miss',
        'mistake',
        'blunder',
    ];

    const categoryLabel = {
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
    };

    const el = {
        summaryText: document.getElementById('summaryText'),
        startReviewBtn: document.getElementById('startReviewBtn'),
        reviewStage: document.getElementById('reviewStage'),
        whiteName: document.getElementById('whiteName'),
        blackName: document.getElementById('blackName'),
        whiteAcc: document.getElementById('whiteAcc'),
        blackAcc: document.getElementById('blackAcc'),
        totalAcc: document.getElementById('totalAcc'),
        whiteRatingEst: document.getElementById('whiteRatingEst'),
        blackRatingEst: document.getElementById('blackRatingEst'),
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
        btnStart: document.getElementById('btnStart'),
        btnPrev: document.getElementById('btnPrev'),
        btnNext: document.getElementById('btnNext'),
        btnEnd: document.getElementById('btnEnd'),
    };

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
        el.evalFill.style.height = `${height}%`;
        el.evalScore.textContent = formatEval(v);
    }

    function initChart(evalHistory) {
        if (!el.chartCanvas) {
            return;
        }
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
                <span class="chip-${key}"><i class="bi ${categoryIcon[key] || 'bi-dot'}"></i> ${categoryLabel[key]}</span>
                <span>${whiteCount}</span>
                <span>${blackCount}</span>
            `;
            el.breakdownRows.appendChild(row);
        });
    }

    function renderSummary(summary, evalHistory) {
        el.whiteName.textContent = summary.players.white.name || 'White';
        el.blackName.textContent = summary.players.black.name || 'Black';
        el.whiteAcc.textContent = `${summary.players.white.accuracy}%`;
        el.blackAcc.textContent = `${summary.players.black.accuracy}%`;
        el.totalAcc.textContent = `${summary.total_accuracy}%`;

        el.whiteRatingEst.textContent = summary.players.white.rating_estimate;
        el.blackRatingEst.textContent = summary.players.black.rating_estimate;

        el.phaseOpeningWhite.textContent = `${summary.phase_accuracy.white.opening}%`;
        el.phaseOpeningBlack.textContent = `${summary.phase_accuracy.black.opening}%`;
        el.phaseMiddleWhite.textContent = `${summary.phase_accuracy.white.middlegame}%`;
        el.phaseMiddleBlack.textContent = `${summary.phase_accuracy.black.middlegame}%`;
        el.phaseEndWhite.textContent = `${summary.phase_accuracy.white.endgame}%`;
        el.phaseEndBlack.textContent = `${summary.phase_accuracy.black.endgame}%`;

        renderBreakdown(summary.counts);
        initChart(evalHistory);
    }

    function createMoveButton(move) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'move-item';
        btn.dataset.ply = String(move.ply);

        const sidePrefix = move.side === 'white' ? `${move.move_number}.` : `${move.move_number}...`;
        const icon = categoryIcon[move.classification] || 'bi-dot';
        btn.innerHTML = `
            <span>${sidePrefix} ${move.san}</span>
            <span class="chip-${move.classification}"><i class="bi ${icon}"></i> ${categoryLabel[move.classification] || move.classification}</span>
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
        el.moveClass.innerHTML = `Category: <i class="bi ${icon}"></i> ${categoryLabel[move.classification] || move.classification}`;
        el.moveDesc.textContent = move.explanation || 'No explanation available.';
        el.bestMove.textContent = move.best_move_san || move.best_move || '--';
        el.followLine.textContent = move.follow_line?.join(' ') || '--';
    }

    function markActiveMove(ply) {
        const items = el.moveList.querySelectorAll('.move-item');
        items.forEach((item) => {
            item.classList.toggle('active', Number.parseInt(item.dataset.ply || '0', 10) === ply);
        });
    }

    function showMainlinePly(ply) {
        if (!state.reviewData) {
            return;
        }

        const maxPly = state.positions.length - 1;
        const targetPly = Math.max(0, Math.min(maxPly, ply));
        state.currentPly = targetPly;
        state.inVariation = false;

        const fen = state.positions[targetPly];
        state.currentFen = fen;
        state.board.position(fen, true);

        if (targetPly === 0) {
            el.moveTitle.textContent = 'Initial Position';
            el.moveClass.textContent = 'Category: --';
            el.moveDesc.textContent = 'Navigate moves or drag a piece to test alternatives.';
            el.bestMove.textContent = '--';
            el.followLine.textContent = '--';
            setEvalBar(0);
        } else {
            const move = state.reviewData.moves[targetPly - 1];
            setMoveDetails(move);
            setEvalBar(move.evaluation_after);
        }

        el.resetLineBtn.hidden = true;
        markActiveMove(targetPly);
    }

    async function analyzeVariation(baseFen, moveUci) {
        el.moveDesc.textContent = 'Analyzing your candidate move on Azure Stockfish...';
        const data = await postJson('/analysis/api/variation/', {
            fen: baseFen,
            move: moveUci,
        });

        state.inVariation = true;
        state.currentFen = data.after_fen;
        state.board.position(data.after_fen, true);

        el.moveTitle.textContent = 'Alternative Move Review';
        const icon = categoryIcon[data.classification] || 'bi-dot';
        el.moveClass.innerHTML = `Category: <i class="bi ${icon}"></i> ${categoryLabel[data.classification] || data.classification}`;
        el.moveDesc.textContent = data.explanation || 'No explanation available.';
        el.bestMove.textContent = data.best_line?.[0] || data.best_move || '--';
        el.followLine.textContent = data.follow_line?.join(' ') || '--';
        setEvalBar(data.evaluation);
        el.resetLineBtn.hidden = false;
    }

    function onDrop(source, target) {
        if (!state.reviewData) {
            return 'snapback';
        }

        const game = new Chess(state.currentFen);
        const move = game.move({
            from: source,
            to: target,
            promotion: 'q',
        });

        if (!move) {
            return 'snapback';
        }

        const moveUci = `${move.from}${move.to}${move.promotion || ''}`;
        analyzeVariation(state.currentFen, moveUci).catch((error) => {
            el.moveDesc.textContent = error.message || 'Failed to analyze variation.';
            state.board.position(state.currentFen, true);
        });

        return undefined;
    }

    function initBoard() {
        state.board = Chessboard('mainBoard', {
            draggable: true,
            position: 'start',
            onDrop,
            pieceTheme: '/static/img/chesspieces/wikipedia/{piece}.png',
        });
    }

    function bindEvents() {
        el.startReviewBtn.addEventListener('click', () => {
            el.reviewStage.hidden = false;
            showMainlinePly(0);
            state.board.resize();
            window.scrollTo({ top: el.reviewStage.offsetTop - 20, behavior: 'smooth' });
        });

        el.btnStart.addEventListener('click', () => showMainlinePly(0));
        el.btnPrev.addEventListener('click', () => showMainlinePly(state.currentPly - 1));
        el.btnNext.addEventListener('click', () => showMainlinePly(state.currentPly + 1));
        el.btnEnd.addEventListener('click', () => showMainlinePly(state.positions.length - 1));

        el.resetLineBtn.addEventListener('click', () => showMainlinePly(state.currentPly));

        el.moveList.addEventListener('click', (event) => {
            const btn = event.target.closest('.move-item');
            if (!btn) {
                return;
            }
            const ply = Number.parseInt(btn.dataset.ply || '0', 10);
            if (Number.isInteger(ply)) {
                showMainlinePly(ply);
            }
        });

        window.addEventListener('resize', () => {
            if (state.board) {
                state.board.resize();
            }
        });
    }

    async function loadReviewData() {
        el.summaryText.textContent = 'Analyzing game with Azure Stockfish. This can take a few seconds...';
        const data = await postJson('/analysis/api/review/start/', {
            game_id: gameId,
        });

        state.reviewData = data;
        state.positions = [data.start_fen, ...data.moves.map((item) => item.fen_after)];
        state.currentFen = data.start_fen;

        renderSummary(data.summary, data.eval_history);
        renderMoveList(data.moves);
        setEvalBar(0);

        const side = data.summary?.user_side === 'black' ? 'black' : 'white';
        state.board.orientation(side);

        el.startReviewBtn.disabled = false;
        el.summaryText.textContent = 'Review ready. Start Review to inspect every move and test alternatives.';
    }

    initBoard();
    bindEvents();

    loadReviewData().catch((error) => {
        el.summaryText.textContent = error.message || 'Could not generate review.';
    });
})();