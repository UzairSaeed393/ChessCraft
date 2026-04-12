/* insights.js — ChessCraft Insights Frontend */

(function () {
    'use strict';

    // ── Chart.js defaults ──────────────────────────────────
    Chart.defaults.color = '#8a8480';
    Chart.defaults.font.family = "'Inter', sans-serif";

    // Chart instances (kept for destroy-on-reload)
    let trendChart = null;
    let breakdownChart = null;
    let phaseChart = null;

    let activeUsername = null;
    let activeColor = 'white';

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

    // ── Load all sections ──────────────────────────────────
    function loadAll(username) {
        show('insLoading');
        hide('insContent');
        Promise.all([
            fetchJSON(`/insights/api/summary/?username=${encodeURIComponent(username)}`),
            fetchJSON(`/insights/api/trend/?username=${encodeURIComponent(username)}`),
            fetchJSON(`/insights/api/move-breakdown/?username=${encodeURIComponent(username)}`),
            fetchJSON(`/insights/api/phases/?username=${encodeURIComponent(username)}`),
            fetchJSON(`/insights/api/openings/?username=${encodeURIComponent(username)}&color=${activeColor}`),
        ]).then(([summary, trend, breakdown, phases, openings]) => {
            hide('insLoading');
            show('insContent');
            renderSummary(summary);
            renderTrend(trend);
            renderBreakdown(breakdown);
            renderPhases(phases);
            renderOpenings(openings);
            renderTips(summary.tips || []);
        }).catch(err => {
            hide('insLoading');
            console.error('Insights load error:', err);
        });
    }

    // ── Summary ────────────────────────────────────────────
    function renderSummary(d) {
        setText('statAvgAcc', d.avg_accuracy + '%');
        setText('statGames', d.total_games);
        setText('statWinRate', d.win_rate + '%');
        setText('statBestAcc', d.best_accuracy !== null ? d.best_accuracy + '%' : '--');
        setText('statWorstAcc', d.worst_accuracy !== null ? d.worst_accuracy + '%' : '--');
        setText('whiteAcc', d.white_accuracy + '%');
        setText('blackAcc', d.black_accuracy + '%');

        // Best / worst game links
        if (d.best_game_id) {
            document.getElementById('statBestAcc').style.cursor = 'pointer';
            document.getElementById('statBestAcc').onclick = () => {
                window.location.href = `/analysis/game/${d.best_game_id}/`;
            };
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
        const labels = catOrder.map(k => CAT_LABELS[k]);
        const values = catOrder.map(k => data[k] || 0);
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
                    tooltip: { callbacks: { label: item => `${item.label}: ${item.raw}` } },
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
                        data: [data.white.opening, data.white.middlegame, data.white.endgame],
                        backgroundColor: 'rgba(240,192,64,0.8)',
                        borderRadius: 4,
                    },
                    {
                        label: 'Black',
                        data: [data.black.opening, data.black.middlegame, data.black.endgame],
                        backgroundColor: 'rgba(91,156,246,0.8)',
                        borderRadius: 4,
                    },
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
    window.setOpeningColor = function (color) {
        activeColor = color;
        document.getElementById('tabWhite').classList.toggle('active', color === 'white');
        document.getElementById('tabBlack').classList.toggle('active', color === 'black');
        if (!activeUsername) return;
        fetchJSON(`/insights/api/openings/?username=${encodeURIComponent(activeUsername)}&color=${color}`)
            .then(renderOpenings);
    };

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
            const gameUrl = `/user/game/?opening=${encodeURIComponent(row.opening)}`;
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
    function fetchJSON(url) {
        return fetch(url).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
    }
    function show(id) { const e = document.getElementById(id); if (e) e.style.display = ''; }
    function hide(id) { const e = document.getElementById(id); if (e) e.style.display = 'none'; }
    function setText(id, val) { const e = document.getElementById(id); if (e) e.textContent = val; }
    function setStyle(id, prop, val) { const e = document.getElementById(id); if (e) e.style[prop] = val; }

})();
