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
    let breakdownChart = null;
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

    // ── Breakdown pie ──────────────────────────────────────
    function renderBreakdown(data) {
        if (breakdownChart) breakdownChart.destroy();
        const ctx = document.getElementById('breakdownChart');
        if (!ctx) return;

        const catOrder = ['brilliant','great','best','excellent','good','book','inaccuracy','miss','mistake','blunder'];
        const values = catOrder.map(k => data[k] || 0);
        const total = values.reduce((sum, val) => sum + val, 0) || 1;
        // Include the count and percentage directly in the legend label
        const labels = catOrder.map(k => {
            const val = data[k] || 0;
            const pct = ((val / total) * 100).toFixed(1);
            return `${CAT_LABELS[k]} (${val}) - ${pct}%`;
        });
        const colors = catOrder.map(k => CAT_COLORS[k]);

        breakdownChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{ data: values, backgroundColor: colors, borderWidth: 1, borderColor: '#2a2927' }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: { boxWidth: 10, padding: 8, font: { size: 11 } },
                    },
                    tooltip: { callbacks: { label: item => `${item.label}` } },
                },
            },
        });
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
                        label: 'White',
                        data: [data.white.opening || null, data.white.middlegame || null, data.white.endgame || null],
                        backgroundColor: 'rgba(210,180,60,0.8)',
                    },
                    {
                        label: 'Black',
                        data: [data.black.opening || null, data.black.middlegame || null, data.black.endgame || null],
                        backgroundColor: 'rgba(91,156,246,0.8)',
                    },
                    {
                        label: 'Overall',
                        data: [
                            data.overall.opening || null, 
                            data.overall.middlegame || null, 
                            data.overall.endgame || null
                        ],
                        backgroundColor: 'rgba(255,255,255,0.15)',
                        borderColor: '#8a8480',
                        borderWidth: 1,
                        type: 'line',
                        tension: 0.4
                    }
                ],
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
                    x: { grid: { display: false } },
                },
                plugins: {
                    legend: { position: 'top', labels: { boxWidth: 12, padding: 10 } },
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
        const tbody = document.getElementById('openingsBody');
        if (!tbody) return;
        if (!data.length) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:#8a8480;padding:20px">No data yet. Analyze some games first.</td></tr>`;
            return;
        }
        tbody.innerHTML = data.map((row, i) => {
            const wr = row.win_rate;
            const wrClass = wr >= 55 ? 'good' : wr >= 40 ? 'avg' : 'bad';
            const gameUrl = `/user/game/?username=${encodeURIComponent(activeUsername)}&opening=${encodeURIComponent(row.opening)}`;
            return `<tr onclick="window.location.href='${gameUrl}'" title="View games with this opening">
                <td style="color:#8a8480">${i + 1}</td>
                <td class="opening-name-cell">${row.opening}</td>
                <td>${row.games}</td>
                <td class="mini-w">${row.wins}</td>
                <td class="mini-d">${row.draws}</td>
                <td class="mini-l">${row.losses}</td>
                <td class="win-rate-cell ${wrClass}">${wr}%</td>
            </tr>`;
        }).join('');
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
