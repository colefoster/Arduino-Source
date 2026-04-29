// ═══════════════════════════════════════════════════════════════
// Dashboard
// ═══════════════════════════════════════════════════════════════
const chartOpts = {
    responsive: true,
    maintainAspectRatio: true,
    animation: false,
    plugins: { legend: { labels: { color: '#8b949e', font: { size: 10, family: 'SF Mono, Fira Code, Consolas, monospace' } } } },
    scales: {
        x: { ticks: { color: '#484f58', font: { size: 10 } }, grid: { color: '#21262d' } },
        y: { ticks: { color: '#484f58', font: { size: 10 } }, grid: { color: '#21262d' }, beginAtZero: true },
    },
};
const VGC_COLOR = '#58a6ff';
const BSS_COLOR = '#d2a8ff';

let rateChart, cumulativeChart, ratingVgcChart, ratingBssChart, datasetVgcChart, datasetBssChart;
let dashboardInited = false;
let dashboardIntervals = [];

function dashboardInit() {
    if (dashboardInited) return;
    dashboardInited = true;

    rateChart = new Chart(document.getElementById('rate-chart'), {
        type: 'bar', data: { labels: [], datasets: [] },
        options: {
            ...chartOpts,
            plugins: { ...chartOpts.plugins, legend: { display: true, labels: chartOpts.plugins.legend.labels } },
            scales: { ...chartOpts.scales, x: { ...chartOpts.scales.x, stacked: true }, y: { ...chartOpts.scales.y, stacked: true } },
        },
    });
    cumulativeChart = new Chart(document.getElementById('cumulative-chart'), {
        type: 'line', data: { labels: [], datasets: [] }, options: chartOpts,
    });
    ratingVgcChart = new Chart(document.getElementById('rating-vgc-chart'), {
        type: 'bar', data: { labels: [], datasets: [] },
        options: { ...chartOpts, plugins: { ...chartOpts.plugins, legend: { display: false } } },
    });
    ratingBssChart = new Chart(document.getElementById('rating-bss-chart'), {
        type: 'bar', data: { labels: [], datasets: [] },
        options: { ...chartOpts, plugins: { ...chartOpts.plugins, legend: { display: false } } },
    });
    const stackedOpts = {
        ...chartOpts,
        plugins: { ...chartOpts.plugins, legend: { display: true, labels: chartOpts.plugins.legend.labels } },
        scales: { ...chartOpts.scales, x: { ...chartOpts.scales.x, stacked: true }, y: { ...chartOpts.scales.y, stacked: true } },
    };
    datasetVgcChart = new Chart(document.getElementById('dataset-vgc-chart'), {
        type: 'bar', data: { labels: [], datasets: [] }, options: stackedOpts,
    });
    datasetBssChart = new Chart(document.getElementById('dataset-bss-chart'), {
        type: 'bar', data: { labels: [], datasets: [] }, options: stackedOpts,
    });

    loadStatus(); loadCollection(); loadRatings(); loadRecent(); loadCoverage(); loadDataset(); loadSyncStatus();
    dashboardIntervals.push(setInterval(() => { loadStatus(); loadRecent(); }, 30000));
    dashboardIntervals.push(setInterval(() => { loadCollection(); loadRatings(); loadDataset(); }, 120000));
    dashboardIntervals.push(setInterval(loadCoverage, 300000));
    dashboardIntervals.push(setInterval(loadSyncStatus, 60000));
}

function agoStr(sec) {
    if (sec < 60) return `${sec}s ago`;
    if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
    return `${Math.round(sec / 3600)}h ago`;
}

async function loadStatus() {
    try {
        const d = await api('/api/status');
        const el = document.getElementById('status-val');
        if (d.alive) {
            el.innerHTML = `<span class="dot green"></span>Active`;
            el.style.color = '#3fb950';
        } else {
            el.innerHTML = `<span class="dot red"></span>Down`;
            el.style.color = '#f85149';
        }
        document.getElementById('status-sub').textContent = d.last_save_ago_sec >= 0 ? `Last save: ${agoStr(d.last_save_ago_sec)}` : '';
        document.getElementById('instances-val').textContent = `${d.connections}/${d.total_connections}`;
        document.getElementById('instances-sub').textContent = `${d.rooms_in_use}/${d.capacity} rooms`;
        document.getElementById('total-val').textContent = d.total_replays.toLocaleString();
        const fmts = d.formats || {};
        const parts = Object.values(fmts).map(f => `${f.label}: ${f.total.toLocaleString()} (${f.downloaded.toLocaleString()} dl + ${f.spectated.toLocaleString()} spec)`);
        document.getElementById('total-sub').textContent = parts.join(' | ');
        const totalLastHour = Object.values(fmts).reduce((a, f) => a + (f.last_1h || 0), 0);
        document.getElementById('rate-val').textContent = totalLastHour.toLocaleString();
        const totalLast24h = Object.values(fmts).reduce((a, f) => a + (f.last_24h || 0), 0);
        document.getElementById('rate-sub').textContent = `${totalLast24h.toLocaleString()} in 24h`;
        const breakdown = document.getElementById('format-breakdown');
        breakdown.innerHTML = Object.entries(fmts).map(([id, f]) => `
            <div class="format-pill">
                <div class="fmt-label">${f.label}</div>
                <div class="fmt-value">${f.total.toLocaleString()}</div>
                <div class="fmt-sub">${f.downloaded.toLocaleString()} dl + ${f.spectated.toLocaleString()} spec | ${f.last_1h}/hr live</div>
            </div>
        `).join('');
        document.getElementById('last-updated').textContent = `Updated: ${new Date().toLocaleTimeString()}`;
    } catch (e) { console.error('loadStatus:', e); }
}

async function loadCoverage() {
    try {
        const d = await api('/api/coverage');
        if (d.error) {
            document.getElementById('coverage-val').textContent = '?';
            document.getElementById('coverage-sub').textContent = d.error;
            return;
        }
        const pct = d.coverage_pct || 0;
        document.getElementById('coverage-val').textContent = `${pct}%`;
        document.getElementById('coverage-sub').textContent = `${d.capacity} slots / ${d.total_active}${d.total_active_note ? '+' : ''} active`;
        const barColor = pct >= 80 ? '#3fb950' : pct >= 50 ? '#d29922' : '#f85149';
        document.getElementById('cov-bar').style.width = `${Math.min(pct, 100)}%`;
        document.getElementById('cov-bar').style.background = barColor;
        document.getElementById('cov-pct').textContent = `${pct}%`;
        document.getElementById('cov-label').textContent = `${d.connections} conn${d.connections !== 1 ? 's' : ''} x 45 rooms = ${d.capacity} capacity (${d.rooms_in_use || 0} in use)`;
        const fmtNames = { gen9championsvgc2026regma: 'VGC', gen9championsbssregma: 'BSS' };
        const covBreakdown = document.getElementById('cov-breakdown');
        covBreakdown.innerHTML = Object.entries(d.active_battles || {}).map(([fmt, count]) => {
            const label = fmtNames[fmt] || fmt;
            const capped = count >= 100;
            return `<div style="background:#21262d; border-radius:4px; padding:6px 12px; font-size:12px;">
                <span style="color:#8b949e;">${label}:</span>
                <strong>${count}${capped ? '+' : ''}</strong> active
                ${capped ? '<span style="color:#d29922; font-size:10px;"> (PS 100 cap)</span>' : ''}
            </div>`;
        }).join('');
        const slices = d.elo_slices || [];
        const note = document.getElementById('cov-note');
        if (slices.length > 1) {
            note.textContent = `Querying ${slices.length} ELO slices (${slices.join(', ')}) to discover battles past PS 100-room cap. High-rated battles prioritized.`;
        }
        document.getElementById('cov-detail').textContent = Object.entries(d.active_battles || {})
            .map(([fmt, count]) => `${fmtNames[fmt] || fmt}: ${count}${count >= 100 ? '+' : ''}`)
            .join(' | ');
    } catch (e) { console.error('loadCoverage:', e); }
}

async function loadCollection() {
    try {
        const d = await api('/api/collection');
        const labels = d.labels.slice().reverse();
        const vgcData = (d.series.gen9championsvgc2026regma?.data || []).slice().reverse();
        const bssData = (d.series.gen9championsbssregma?.data || []).slice().reverse();
        const last24Labels = labels.slice(-24);
        const last24Vgc = vgcData.slice(-24);
        const last24Bss = bssData.slice(-24);
        rateChart.data.labels = last24Labels;
        rateChart.data.datasets = [
            { label: 'VGC', data: last24Vgc, backgroundColor: VGC_COLOR + '99', borderColor: VGC_COLOR, borderWidth: 1 },
            { label: 'BSS', data: last24Bss, backgroundColor: BSS_COLOR + '99', borderColor: BSS_COLOR, borderWidth: 1 },
        ];
        rateChart.update();
        let cumVgc = 0, cumBss = 0;
        const cumVgcData = vgcData.map(v => cumVgc += v);
        const cumBssData = bssData.map(v => cumBss += v);
        cumulativeChart.data.labels = labels;
        cumulativeChart.data.datasets = [
            { label: 'VGC', data: cumVgcData, borderColor: VGC_COLOR, backgroundColor: VGC_COLOR + '22', fill: true, pointRadius: 0, borderWidth: 2 },
            { label: 'BSS', data: cumBssData, borderColor: BSS_COLOR, backgroundColor: BSS_COLOR + '22', fill: true, pointRadius: 0, borderWidth: 2 },
        ];
        cumulativeChart.update();
    } catch (e) { console.error('loadCollection:', e); }
}

async function loadRatings() {
    try {
        const d = await api('/api/ratings');
        const vgcData = d.series.gen9championsvgc2026regma?.data || [];
        const bssData = d.series.gen9championsbssregma?.data || [];
        ratingVgcChart.data.labels = d.bins;
        ratingVgcChart.data.datasets = [{ label: 'VGC', data: vgcData, backgroundColor: VGC_COLOR + '88', borderColor: VGC_COLOR, borderWidth: 1 }];
        ratingVgcChart.update();
        ratingBssChart.data.labels = d.bins;
        ratingBssChart.data.datasets = [{ label: 'BSS', data: bssData, backgroundColor: BSS_COLOR + '88', borderColor: BSS_COLOR, borderWidth: 1 }];
        ratingBssChart.update();
    } catch (e) { console.error('loadRatings:', e); }
}

async function loadRecent() {
    try {
        const items = await api('/api/recent?limit=40');
        const feed = document.getElementById('feed');
        if (!items.length) { feed.innerHTML = '<div style="color:#484f58; font-size:12px;">No recent saves</div>'; return; }
        feed.innerHTML = items.map(r => {
            const players = r.players || [];
            const p1 = players[0] || '?';
            const p2 = players[1] || '?';
            const fmtLabel = r.format_label || '?';
            return `<div class="feed-item">
                <span class="players"><span class="fmt">${fmtLabel}</span>${p1} vs ${p2}</span>
                <span class="meta"><span class="rating">${r.rating || '?'}</span> &middot; ${agoStr(r.ago_sec)}</span>
            </div>`;
        }).join('');
    } catch (e) { console.error('loadRecent:', e); }
}

async function loadDataset() {
    try {
        const d = await api('/api/dataset');
        const combined = d.combined || {};
        const cards = document.getElementById('dataset-cards');
        const DL_COLOR = '#f0883e';
        const SP_COLOR = '#3fb950';
        let html = '';
        for (const [key, data] of Object.entries(combined)) {
            const label = key.toUpperCase();
            html += `<div class="card">
                <div class="label">${label} Total</div>
                <div class="value">${(data.total || 0).toLocaleString()}</div>
                <div class="sub">
                    <span style="color:${DL_COLOR}">${(data.downloaded || 0).toLocaleString()} downloaded</span> +
                    <span style="color:${SP_COLOR}">${(data.spectated || 0).toLocaleString()} spectated</span>
                </div>
                <div class="sub">${(data.rated || 0).toLocaleString()} with ratings</div>
            </div>`;
        }
        const grandTotal = Object.values(combined).reduce((a, c) => a + (c.total || 0), 0);
        const grandDl = Object.values(combined).reduce((a, c) => a + (c.downloaded || 0), 0);
        const grandSp = Object.values(combined).reduce((a, c) => a + (c.spectated || 0), 0);
        html += `<div class="card">
            <div class="label">Grand Total</div>
            <div class="value">${grandTotal.toLocaleString()}</div>
            <div class="sub"><span style="color:${DL_COLOR}">${grandDl.toLocaleString()}</span> + <span style="color:${SP_COLOR}">${grandSp.toLocaleString()}</span></div>
        </div>`;
        cards.innerHTML = html;

        function renderDatasetChart(chart, buckets) {
            const labels = Object.keys(buckets).map(b => `${b}-${parseInt(b)+49}`);
            const dlData = Object.values(buckets).map(b => b.downloaded || 0);
            const spData = Object.values(buckets).map(b => b.spectated || 0);
            chart.data.labels = labels;
            chart.data.datasets = [
                { label: 'Downloaded', data: dlData, backgroundColor: DL_COLOR + '99', borderColor: DL_COLOR, borderWidth: 1 },
                { label: 'Spectated', data: spData, backgroundColor: SP_COLOR + '99', borderColor: SP_COLOR, borderWidth: 1 },
            ];
            chart.update();
        }
        if (combined.vgc?.rating_buckets) renderDatasetChart(datasetVgcChart, combined.vgc.rating_buckets);
        if (combined.bss?.rating_buckets) renderDatasetChart(datasetBssChart, combined.bss.rating_buckets);
    } catch (e) { console.error('loadDataset:', e); }
}


// ═══════════════════════════════════════════════════════════════
// Sync
// ═══════════════════════════════════════════════════════════════

async function loadSyncStatus() {
    try {
        const d = await api('/api/sync/status');
        const statusEl = document.getElementById('sync-status');
        const btn = document.getElementById('sync-btn');
        const resultEl = document.getElementById('sync-result');

        if (d.running) {
            statusEl.innerHTML = '<span class="dot yellow"></span>Syncing...';
            btn.disabled = true;
            btn.textContent = 'Syncing...';
        } else if (d.colepc_reachable) {
            statusEl.innerHTML = '<span class="dot green"></span>ColePC online';
            btn.disabled = false;
            btn.textContent = 'Sync Now';
        } else {
            statusEl.innerHTML = '<span class="dot red"></span>ColePC offline';
            btn.disabled = true;
            btn.textContent = 'Sync Now';
        }

        if (d.last_error) {
            resultEl.innerHTML = `<span style="color:#f85149;">Last error: ${d.last_error}</span>`;
        } else if (d.last_result) {
            const r = d.last_result;
            const ago = agoStr(Math.round(Date.now() / 1000 - r.timestamp));
            const fmtDetails = Object.values(r.formats)
                .map(f => `${f.format.replace('gen9champions', '').replace('regma', '')}: ${f.synced.toLocaleString()} new`)
                .join(', ');
            resultEl.innerHTML = `Last sync: ${r.total_synced.toLocaleString()} files pushed ${ago} (${fmtDetails})`;
        }
    } catch (e) { console.error('loadSyncStatus:', e); }
}

async function triggerSync() {
    const btn = document.getElementById('sync-btn');
    const statusEl = document.getElementById('sync-status');
    const resultEl = document.getElementById('sync-result');

    btn.disabled = true;
    btn.textContent = 'Syncing...';
    statusEl.innerHTML = '<span class="dot yellow"></span>Syncing...';
    resultEl.innerHTML = 'Calculating delta and pushing new replays...';

    try {
        const resp = await fetch(`${API}/api/sync/trigger`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const d = await resp.json();
        if (d.error) {
            resultEl.innerHTML = `<span style="color:#f85149;">${d.error}</span>`;
        } else {
            const fmtDetails = Object.values(d.formats)
                .map(f => `${f.format.replace('gen9champions', '').replace('regma', '')}: ${f.synced.toLocaleString()} new`)
                .join(', ');
            resultEl.innerHTML = `<span style="color:#3fb950;">Synced ${d.total_synced.toLocaleString()} files</span> (${fmtDetails})`;
        }
    } catch (e) {
        resultEl.innerHTML = `<span style="color:#f85149;">Sync failed: ${e.message}</span>`;
    }

    btn.disabled = false;
    btn.textContent = 'Sync Now';
    loadSyncStatus();
}
