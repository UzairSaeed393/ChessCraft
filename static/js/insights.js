/* insights.js — ChessCraft Insights Frontend */

(function () {
    'use strict';

    function byId(id) {
        return document.getElementById(id);
    }

    // ── Chart.js defaults ──────────────────────────────────
    Chart.defaults.color = '#8a8480';
    Chart.defaults.font.family = "'Inter', sans-serif";

    // Chart instances (kept for destroy-on-reload)
    let trendChart = null;
    let phaseChart = null;

    let activeUsername = null;
    let activeColor = 'white';
    let isAnalyzing = false;

    // Helper to get CSRF token
    function getCSRF() {
        return document.cookie.split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1] || '';
    }

    // Classification colors
    const CAT_COLORS = {
        brilliant: '#29d0d0',
        great: '#5b9cf6',
        best: '#81b64c',
        excellent: '#acd96a',
        good: '#c9e89a',
        book: '#f0c040',
        inaccuracy: '#f5833a',
        miss: '#e05555',
        mistake: '#cc2222',
        blunder: '#990000',
    };
    const CAT_LABELS = {
        brilliant: 'Brilliant', great: 'Great', best: 'Best',
        excellent: 'Excellent', good: 'Good', book: 'Book',
        inaccuracy: 'Inaccuracy', miss: 'Miss',
        mistake: 'Mistake', blunder: 'Blunder',
    };

    // ── Player selector ────────────────────────────────────
    document.querySelectorAll('.player-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.player-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeUsername = btn.dataset.username;
            loadAll(activeUsername);
        });
    });

    // Auto-load first player
    const firstBtn = document.querySelector('.player-btn');
    if (firstBtn) {
        activeUsername = firstBtn.dataset.username;
        loadAll(activeUsername);
    }

    // ── Load all sections (Tiered) ──────────────────────────
    function loadAll(username) {
        // Start main loading
        show('insLoading');
        hide('insContent');
        checkHealth();

        // Tier 1: Fast Data (W/L Summary, Trend, Openings)
        const t1 = [
            fetchJSON(`/insights/api/summary/?username=${encodeURIComponent(username)}`),
            fetchJSON(`/insights/api/trend/?username=${encodeURIComponent(username)}`),
            fetchJSON(`/insights/api/openings/?username=${encodeURIComponent(username)}&color=${activeColor}`),
        ];

        Promise.all(t1).then(([summary, trend, openings]) => {
            hide('insLoading');
            show('insContent');
            
            if (summary.total_games === 0) {
                // Show Empty Insights State
                const main = document.getElementById('insContent');
                main.innerHTML = `
                    <div style="text-align:center; padding: 60px 20px; color: var(--ins-muted);">
                        <i class="bi bi-bar-chart-steps" style="font-size: 3.5rem; color: #333; margin-bottom: 20px; display:block;"></i>
                        <h2 style="color:#fff; margin-bottom: 12px;">No Analyzed Games Found</h2>
                        <p style="max-width: 500px; margin: 0 auto 30px; font-size: 1.1rem;">
                            Insights are generated from your analyzed games. 
                            Start reviewing your games to see your strengths and weaknesses.
                        </p>
                        <a href="/user/game/" class="err-btn retry" style="text-decoration:none; display:inline-block;">Go to My Games</a>
                    </div>
                `;
                return;
            }

            renderSummary(summary);
            renderTrend(trend);
            renderOpenings(openings);

            // Tier 2: Slow/Analytical Data (Move Breakdown, Phases, Tips)
            loadAnalyticalData(username);
        }).catch(err => {
            hide('insLoading');
            console.error('Insights Tier 1 error:', err);
            showErrorUI(err.message);
        });
    }

    function showErrorUI(msg, details = '') {
        hide('insLoading');
        hide('insContent');
        show('insError');
        
        setText('errDesc', msg || "We encountered an issue fetching your insights.");
        
        const btnRetry = document.getElementById('btnErrRetry');
        if (btnRetry) {
            btnRetry.onclick = () => {
                hide('insError');
                if (activeUsername) loadAll(activeUsername);
            };
        }
        
        const btnReport = document.getElementById('btnErrReport');
        if (btnReport) {
            btnReport.onclick = () => {
                window.location.href = '/contact/';
            };
        }
    }

    function loadAnalyticalData(username) {
        const sections = [
            { id: 'cardBreakdown', endpoint: 'move-breakdown', render: renderBreakdown },
            { id: 'cardPhases', endpoint: 'phases', render: renderPhases },
            { id: 'cardTips', endpoint: 'summary', render: (d) => renderTips(d.tips || []) }
        ];

        sections.forEach(sec => {
            const card = document.getElementById(sec.id);
            if (!card) return;

            // Show loader in this card
            card.querySelectorAll('.analytical-loader').forEach(l => l.style.display = 'flex');
            card.querySelectorAll('.content-node').forEach(c => c.style.display = 'none');
            card.querySelectorAll('.empty-state-node').forEach(e => e.style.display = 'none');

            fetchJSON(`/insights/api/${sec.endpoint}/?username=${encodeURIComponent(username)}`)
                .then(data => {
                    card.querySelectorAll('.analytical-loader').forEach(l => l.style.display = 'none');
                    
                    // Check if data is "empty"
                    const isEmpty = checkDataEmpty(sec.endpoint, data);
                    if (isEmpty) {
                        card.querySelectorAll('.empty-state-node').forEach(e => e.style.display = 'block');
                    } else {
                        card.querySelectorAll('.content-node').forEach(c => c.style.display = 'block');
                        sec.render(data);
                    }
                })
                .catch(err => {
                    console.error(`Analytical Load Error (${sec.endpoint}):`, err);
                    card.querySelectorAll('.analytical-loader').forEach(l => l.style.display = 'none');
                    // Show small error hint in the card
                    const contentNode = card.querySelector('.content-node');
                    if (contentNode) {
                        contentNode.style.display = 'block';
                        contentNode.innerHTML = `
                            <div class="card-error-hint" style="color:var(--ins-red); font-size: 0.85rem; padding: 20px; text-align:center; border: 1px dashed rgba(232,64,64,0.3); border-radius: 12px; background: rgba(232,64,64,0.02);">
                                <i class="bi bi-exclamation-circle me-1"></i> Data unavailable. 
                                <a href="/contact/" style="color:var(--ins-cyan); text-decoration: underline;">Report?</a>
                            </div>`;
                    }
                });
        });
    }

    function checkDataEmpty(endpoint, data) {
        if (!data) return true;
        if (endpoint === 'move-breakdown') {
            return Object.values(data).every(v => v === 0);
        }
        if (endpoint === 'phases') {
            // If overall opening accuracy is 0, we assume no analysis yet
            return !data.overall || data.overall.opening === 0;
        }
        return false;
    }

    function checkHealth() {
        fetchJSON('/analysis/health/').then(d => {
            const dot = document.querySelector('.status-dot');
            const text = document.querySelector('.status-text');
            if (!dot || !text) return;

            if (d.active_tasks > 0 || d.queue_length > 0) {
                dot.className = 'status-dot busy';
                const qText = d.queue_length > 0 ? ` (Queue: ${d.queue_length})` : '';
                text.textContent = `Engine: Working${qText}`;
            } else {
                dot.className = 'status-dot free';
                text.textContent = 'Engine: Ready';
            }
        }).catch(() => {});
    }

    function runAnalysisBatch(period) {
        if (isAnalyzing || !activeUsername) return;
        
        isAnalyzing = true;
        show('analysisProgress');
        const pText = document.querySelector('.pbar-text');
        if (pText) pText.textContent = "Connecting to engine...";

        const btnSyncRecent = byId('btnSyncRecent');
        const btnSyncMonth = byId('btnSyncMonth');
        if (btnSyncRecent) btnSyncRecent.disabled = true;
        if (btnSyncMonth) btnSyncMonth.disabled = true;

        fetch('/analysis/api/analyze-period/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRF()
            },
            body: JSON.stringify({ username: activeUsername, period: period })
        })
        .then(r => r.json())
        .then(res => {
            isAnalyzing = false;
            hide('analysisProgress');
            if (btnSyncRecent) btnSyncRecent.disabled = false;
            if (btnSyncMonth) btnSyncMonth.disabled = false;

            if (res.status === 'complete' || res.status === 'success') {
                const count = res.games_processed || res.processed_count || 0;
                const msg = res.server_busy ? `Server busy: Analyzed ${count} games.` : `Analyzed ${count} games successfully.`;
                alert(msg);
                loadAll(activeUsername); // Refresh data
            } else if (res.status === 'no_games') {
                alert("All games in this period are already analyzed!");
            }
        })
        .catch(err => {
            isAnalyzing = false;
            hide('analysisProgress');
            if (btnSyncRecent) btnSyncRecent.disabled = false;
            if (btnSyncMonth) btnSyncMonth.disabled = false;
            alert("Error running analysis batch.");
        });
    }

    const btnSyncRecent = byId('btnSyncRecent');
    const btnSyncMonth = byId('btnSyncMonth');
    if (btnSyncRecent) btnSyncRecent.addEventListener('click', () => runAnalysisBatch('week'));
    if (btnSyncMonth) btnSyncMonth.addEventListener('click', () => runAnalysisBatch('month'));

    // ── Summary ────────────────────────────────────────────
    function renderSummary(d) {
        setText('statAvgAcc', (d.avg_accuracy ?? 0) + '%');
        setText('statGames', d.total_games ?? 0);
        setText('statWinRate', (d.win_rate ?? 0) + '%');
        setText('statBestAcc', d.best_accuracy !== null && d.best_accuracy !== undefined ? d.best_accuracy + '%' : '--');
        setText('statWorstAcc', d.worst_accuracy !== null && d.worst_accuracy !== undefined ? d.worst_accuracy + '%' : '--');
        setText('whiteAcc', (d.white_accuracy ?? 0) + '%');
        setText('blackAcc', (d.black_accuracy ?? 0) + '%');
        
        // Split winrates
        setText('winRateWhite', `W: ${d.white_stats.win_rate}%`);
        setText('winRateBlack', `B: ${d.black_stats.win_rate}%`);

        // Best / worst game links
        const statBestAcc = byId('statBestAcc');
        if (statBestAcc) {
            if (d.best_game_id) {
                statBestAcc.style.cursor = 'pointer';
                statBestAcc.onclick = () => {
                    window.location.href = `/analysis/game/${d.best_game_id}/`;
                };
            } else {
                statBestAcc.style.cursor = '';
                statBestAcc.onclick = null;
            }
        }

        // WDL bar
        const total = (d.wins + d.draws + d.losses) || 1;
        const pW = (d.wins / total * 100).toFixed(1);
        const pD = (d.draws / total * 100).toFixed(1);
        const pL = (d.losses / total * 100).toFixed(1);
        setStyle('wSeg', 'width', pW + '%');
        setStyle('dSeg', 'width', pD + '%');
        setStyle('lSeg', 'width', pL + '%');
        setText('wLabel', `W: ${d.wins} (${pW}%)`);
        setText('dLabel', `D: ${d.draws} (${pD}%)`);
        setText('lLabel', `L: ${d.losses} (${pL}%)`);
    }

    // ── Trend chart ────────────────────────────────────────
    function renderTrend(data) {
        if (trendChart) trendChart.destroy();
        const ctx = document.getElementById('trendChart');
        if (!ctx || !data.length) return;

        trendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => d.date),
                datasets: [{
                    label: 'Accuracy',
                    data: data.map(d => d.accuracy),
                    borderColor: '#81b64c',
                    backgroundColor: 'rgba(129,182,76,0.12)',
                    pointBackgroundColor: '#81b64c',
                    pointRadius: 3,
                    tension: 0.35,
                    fill: true,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        min: 0, max: 100,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { callback: v => v + '%' },
                    },
                    x: {
                        grid: { display: false },
                        ticks: { maxTicksLimit: 8 },
                    },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => data[items[0].dataIndex]?.opening || items[0].label,
                            label: item => `Accuracy: ${item.raw}%`,
                        },
                    },
                },
            },
        });
    }

    // ── Chess.com-style SVG icons for each move category ──
    const CAT_ICONS = {
        brilliant: `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#29d0d0"/><text x="16" y="21" text-anchor="middle" font-size="16" font-weight="bold" fill="#fff">!!</text></svg>`,
        great:     `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#5b9cf6"/><text x="16" y="21" text-anchor="middle" font-size="16" font-weight="bold" fill="#fff">!</text></svg>`,
        best:      `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#81b64c"/><text x="16" y="21" text-anchor="middle" font-size="17" fill="#fff">★</text></svg>`,
        excellent: `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#81b64c"/><text x="16" y="21" text-anchor="middle" font-size="14" fill="#fff">👍</text></svg>`,
        good:      `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#97bc5a"/><text x="16" y="20" text-anchor="middle" font-size="13" fill="#fff">●</text></svg>`,
        book:      `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#d4a843"/><text x="16" y="21" text-anchor="middle" font-size="14" fill="#fff">📖</text></svg>`,
        inaccuracy:`<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#f0a848"/><text x="16" y="21" text-anchor="middle" font-size="16" font-weight="bold" fill="#fff">?!</text></svg>`,
        miss:      `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#e87040"/><text x="16" y="20" text-anchor="middle" font-size="14" fill="#fff">…</text></svg>`,
        mistake:   `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#e05555"/><text x="16" y="21" text-anchor="middle" font-size="16" font-weight="bold" fill="#fff">?</text></svg>`,
        blunder:   `<svg viewBox="0 0 32 32" width="22" height="22"><circle cx="16" cy="16" r="15" fill="#ca3431"/><text x="16" y="21" text-anchor="middle" font-size="16" font-weight="bold" fill="#fff">??</text></svg>`,
    };

    // ── Breakdown list (chess.com style) ──────────────────
    function renderBreakdown(data) {
        const container = document.getElementById('breakdownList');
        if (!container) return;

        const catOrder = ['brilliant','great','best','excellent','good','book','inaccuracy','miss','mistake','blunder'];
        const total = catOrder.reduce((sum, k) => sum + (data[k] || 0), 0) || 1;

        let html = '';
        catOrder.forEach(key => {
            const count = data[key] || 0;
            const pct = ((count / total) * 100).toFixed(1);
            const barWidth = Math.max(count > 0 ? 2 : 0, (count / total) * 100); // min 2% if > 0

            html += `
                <div class="bd-row">
                    <div class="bd-icon">${CAT_ICONS[key]}</div>
                    <div class="bd-info">
                        <div class="bd-label-row">
                            <span class="bd-name">${CAT_LABELS[key]}</span>
                            <span class="bd-count">${count} <span class="bd-pct">(${pct}%)</span></span>
                        </div>
                        <div class="bd-bar-track">
                            <div class="bd-bar-fill" style="width:${barWidth}%;background:${CAT_COLORS[key]}"></div>
                        </div>
                    </div>
                </div>`;
        });

        container.innerHTML = html;
    }


    // ── Phase chart ────────────────────────────────────────
    function renderPhases(data) {
        if (phaseChart) phaseChart.destroy();
        const ctx = document.getElementById('phaseChart');
        if (!ctx) return;

        phaseChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['Opening', 'Middlegame', 'Endgame'],
                datasets: [
                    {
                        label: 'Your Play as White',
                        data: [data.white.opening || 0, data.white.middlegame || 0, data.white.endgame || 0],
                        backgroundColor: 'rgba(210,180,60,0.85)',
                        borderWidth: 0,
                    },
                    {
                        label: 'Your Play as Black',
                        data: [data.black.opening || 0, data.black.middlegame || 0, data.black.endgame || 0],
                        backgroundColor: 'rgba(91,156,246,0.85)',
                        borderWidth: 0,
                    },
                    {
                        label: 'Average Across All Your Sides',
                        data: [
                            data.overall.opening || 0, 
                            data.overall.middlegame || 0, 
                            data.overall.endgame || 0
                        ],
                        backgroundColor: 'rgba(255,255,255,0.08)',
                        borderColor: '#888',
                        borderWidth: 2,
                        type: 'line',
                        tension: 0.3,
                        pointRadius: 4,
                    }
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                barPercentage: 0.8,
                categoryPercentage: 0.9,
                scales: {
                    y: {
                        min: 0, max: 100,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { 
                            callback: v => v + '%',
                            font: { size: 10 }
                        },
                    },
                    x: { 
                        grid: { display: false },
                        ticks: { font: { size: 10 } }
                    },
                },
                plugins: {
                    legend: { 
                        position: 'top', 
                        labels: { 
                            boxWidth: 8, 
                            padding: 10,
                            font: { size: 10 } 
                        } 
                    },
                    tooltip: { callbacks: { label: i => `${i.dataset.label}: ${i.raw}%` } },
                },
            },
        });
    }

    // ── Openings table ─────────────────────────────────────
    function setOpeningColor(color) {
        activeColor = color;
        const tabWhite = byId('tabWhite');
        const tabBlack = byId('tabBlack');
        if (tabWhite) tabWhite.classList.toggle('active', color === 'white');
        if (tabBlack) tabBlack.classList.toggle('active', color === 'black');
        if (!activeUsername) return;
        fetchJSON(`/insights/api/openings/?username=${encodeURIComponent(activeUsername)}&color=${color}`)
            .then(renderOpenings);
    }
    
    {
        const tabWhite = byId('tabWhite');
        const tabBlack = byId('tabBlack');
        if (tabWhite) tabWhite.addEventListener('click', () => setOpeningColor('white'));
        if (tabBlack) tabBlack.addEventListener('click', () => setOpeningColor('black'));
    }

    function renderOpenings(data) {
        const container = document.getElementById('openingsContent');
        if (!container) return;
        if (!data.length) {
            container.innerHTML = `<div style="text-align:center;color:#8a8480;padding:20px">No data yet. Analyze some games first.</div>`;
            return;
        }
        let html = '';
        data.forEach((row, i) => {
            const wr = row.win_rate;
            const wrClass = wr >= 55 ? 'good' : wr >= 40 ? 'avg' : 'bad';
            const total = row.wins + row.draws + row.losses || 1;
            const wPct = ((row.wins / total) * 100).toFixed(0);
            const dPct = ((row.draws / total) * 100).toFixed(0);
            const lPct = ((row.losses / total) * 100).toFixed(0);
            const gameUrl = `/user/game/?username=${encodeURIComponent(activeUsername)}&opening=${encodeURIComponent(row.opening)}`;

            html += `
                <div class="opening-card" onclick="window.location.href='${gameUrl}'" title="View games with this opening">
                    <div class="oc-header">
                        <span class="oc-rank">${i + 1}</span>
                        <span class="oc-name">${row.opening}</span>
                        <span class="oc-games">${row.games} game${row.games > 1 ? 's' : ''}</span>
                    </div>
                    <div class="oc-bar-row">
                        <div class="oc-bar-track">
                            <div class="oc-bar-w" style="width:${wPct}%" title="Wins: ${row.wins}"></div>
                            <div class="oc-bar-d" style="width:${dPct}%" title="Draws: ${row.draws}"></div>
                            <div class="oc-bar-l" style="width:${lPct}%" title="Losses: ${row.losses}"></div>
                        </div>
                    </div>
                    <div class="oc-stats">
                        <span class="mini-w">W: ${row.wins}</span>
                        <span class="mini-d">D: ${row.draws}</span>
                        <span class="mini-l">L: ${row.losses}</span>
                        <span class="win-rate-cell ${wrClass}">${wr}%</span>
                    </div>
                </div>`;
        });
        container.innerHTML = html;
    }

    // ── Tips ───────────────────────────────────────────────
    function renderTips(tips) {
        const el = document.getElementById('tipsList');
        if (!el) return;
        el.innerHTML = (tips.length ? tips : ['Keep analyzing your games to unlock personalized tips!'])
            .map(t => `<li>${t}</li>`).join('');
    }

    // ── Helpers ────────────────────────────────────────────
    async function fetchJSON(url) {
        try {
            const r = await fetch(url);
            const contentType = r.headers.get('content-type');
            
            if (!contentType || !contentType.includes('application/json')) {
                // This is likely the HTML 500 error page
                throw new Error("Server experiencing heavy load or connection issues. Please try again later.");
            }

            const data = await r.json();
            if (!r.ok) {
                const err = new Error(data.message || `Error ${r.status}`);
                err.details = data.details;
                throw err;
            }
            return data;
        } catch (err) {
            // Re-throw standardized errors
            if (err.message.includes('Unexpected token')) {
                throw new Error("Network issues or Engine busy. Report if this persists.");
            }
            throw err;
        }
    }
    function show(id) { const e = document.getElementById(id); if (e) e.style.display = ''; }
    function hide(id) { const e = document.getElementById(id); if (e) e.style.display = 'none'; }
    function setText(id, val) { const e = document.getElementById(id); if (e) e.textContent = val; }
    function setStyle(id, prop, val) { const e = document.getElementById(id); if (e) e.style[prop] = val; }

})();
