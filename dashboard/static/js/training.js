// ═══════════════════════════════════════════════════════════════
// Training Progress
// ═══════════════════════════════════════════════════════════════
let trainingInited = false;
let trainingCharts = {};
let trainingRefreshTimer = null;
let trainingSelectedSession = null;

async function trainingInit() {
    if (trainingInited) { trainingRefresh(); return; }
    trainingInited = true;
    await trainingRefresh();
    trainingRefreshTimer = setInterval(trainingRefresh, 15000);
}

function trainingGroupOf(modelVersion) {
    const m = (modelVersion || '').toLowerCase();
    if (m.startsWith('v2') || m === 'action') return { key: 'action', label: 'Action Model' };
    if (m.startsWith('winrate') || m.startsWith('win_')) return { key: 'winrate', label: 'Win Probability' };
    if (m.startsWith('lead')) return { key: 'lead', label: 'Lead Advisor' };
    return { key: 'other', label: 'Other' };
}

const TRAINING_GROUP_ORDER = ['action', 'winrate', 'lead', 'other'];

function trainingRenderCard(s) {
    const active = s.active;
    const pct = s.total_epochs ? Math.round(s.current_epoch / s.total_epochs * 100) : 0;
    const dotClass = active ? 'green' : 'yellow';
    const cfg = s.config || {};
    return `<div class="card" style="cursor:pointer; min-width:220px; max-width:300px; border-color:${trainingSelectedSession === s.session_id ? '#1f6feb' : '#30363d'};" onclick="trainingSelect('${s.session_id}')">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-size:12px; font-weight:600; color:#c9d1d9;"><span class="dot ${dotClass}"></span>${s.machine}</span>
            <span style="font-size:10px; color:#484f58;">${s.model_version}</span>
        </div>
        <div style="font-size:10px; color:#8b949e; margin-bottom:6px;">${s.session_id}</div>
        <div style="background:#21262d; border-radius:3px; height:6px; margin-bottom:6px; overflow:hidden;">
            <div style="background:${active ? '#3fb950' : '#d29922'}; height:100%; width:${pct}%; transition:width 0.3s;"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:11px;">
            <span style="color:#8b949e;">Epoch ${s.current_epoch}/${s.total_epochs}</span>
            <span style="color:#58a6ff;">${s.latest_val_top1 != null ? s.latest_val_top1 + '%' : '--'}</span>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:10px; color:#484f58; margin-top:2px;">
            <span>Loss: ${s.latest_val_loss != null ? s.latest_val_loss.toFixed(4) : '--'}</span>
            <span>Best: ${s.best_val_loss != null ? s.best_val_loss.toFixed(4) : '--'}</span>
        </div>
        ${cfg.params ? `<div style="font-size:9px; color:#484f58; margin-top:4px;">${(cfg.params).toLocaleString()} params · ${cfg.dataset_size ? cfg.dataset_size.toLocaleString() + ' samples' : ''}${cfg.min_rating ? ' · ELO\u2265' + cfg.min_rating : ''} · ${cfg.device || ''}</div>` : ''}
    </div>`;
}

async function trainingRefresh() {
    const sessions = await api('/api/training/sessions');
    const container = document.getElementById('training-sessions');

    if (!sessions.length) {
        container.innerHTML = '<div style="padding:16px; background:#161b22; border:1px solid #30363d; border-radius:8px; color:#484f58;">No training sessions yet. Start training with <code>--dashboard https://champions.colefoster.ca</code></div>';
        return;
    }

    // Group by model type
    const groups = {};
    for (const s of sessions) {
        const g = trainingGroupOf(s.model_version);
        if (!groups[g.key]) groups[g.key] = { label: g.label, sessions: [] };
        groups[g.key].sessions.push(s);
    }

    const groupHtml = TRAINING_GROUP_ORDER
        .filter(k => groups[k])
        .map(k => {
            const g = groups[k];
            const activeCount = g.sessions.filter(s => s.active).length;
            const badge = activeCount
                ? `<span style="font-size:10px; color:#3fb950; margin-left:8px;">${activeCount} active</span>`
                : '';
            return `<div style="margin-bottom:20px;">
                <div style="display:flex; align-items:baseline; gap:8px; margin-bottom:8px; padding-bottom:4px; border-bottom:1px solid #21262d;">
                    <span style="font-size:13px; font-weight:600; color:#c9d1d9;">${g.label}</span>
                    <span style="font-size:10px; color:#484f58;">${g.sessions.length} session${g.sessions.length === 1 ? '' : 's'}</span>
                    ${badge}
                </div>
                <div style="display:flex; gap:12px; flex-wrap:wrap;">
                    ${g.sessions.map(trainingRenderCard).join('')}
                </div>
            </div>`;
        }).join('');

    container.innerHTML = groupHtml;

    if (trainingSelectedSession) {
        await trainingShowDetail(trainingSelectedSession);
    } else if (sessions.length) {
        await trainingSelect(sessions[0].session_id);
    }
}

async function trainingSelect(sessionId) {
    trainingSelectedSession = sessionId;
    // Re-render cards to update border
    await trainingRefresh();
}

async function trainingShowDetail(sessionId) {
    const data = await api(`/api/training/session/${sessionId}`);
    if (data.error) return;

    const detail = document.getElementById('training-detail');
    const epochs = data.epochs || [];
    if (!epochs.length) {
        detail.innerHTML = '<div style="color:#484f58; padding:12px;">No epochs recorded yet.</div>';
        return;
    }

    const chartId1 = 'training-loss-chart';
    const chartId2 = 'training-acc-chart';

    detail.innerHTML = `
        <div class="grid-2">
            <div class="chart-box">
                <div class="chart-title">Loss</div>
                <canvas id="${chartId1}"></canvas>
            </div>
            <div class="chart-box">
                <div class="chart-title">Accuracy (Top-1 / Top-3)</div>
                <canvas id="${chartId2}"></canvas>
            </div>
        </div>
        ${epochs[epochs.length-1].team_acc != null ? `<div class="grid-2">
            <div class="chart-box">
                <div class="chart-title">Team & Lead Selection Accuracy</div>
                <canvas id="training-team-chart"></canvas>
            </div>
            <div class="chart-box">
                <div class="chart-title">Learning Rate</div>
                <canvas id="training-lr-chart"></canvas>
            </div>
        </div>` : ''}
    `;

    const labels = epochs.map(e => e.epoch);
    const axisOpts = { ticks: { color: '#484f58', font: { size: 10 } }, grid: { color: '#21262d' } };
    const baseOpts = { responsive: true, animation: false, plugins: { legend: { labels: { color: '#8b949e', font: { size: 10 } } } }, scales: { x: axisOpts, y: axisOpts } };

    // Destroy old charts
    Object.values(trainingCharts).forEach(c => c.destroy());
    trainingCharts = {};

    // Loss chart
    trainingCharts.loss = new Chart(document.getElementById(chartId1), {
        type: 'line', data: {
            labels,
            datasets: [
                { label: 'Train Loss', data: epochs.map(e => e.train_loss), borderColor: '#58a6ff', borderWidth: 1.5, pointRadius: 0, fill: false },
                { label: 'Val Loss', data: epochs.map(e => e.val_loss), borderColor: '#f85149', borderWidth: 1.5, pointRadius: 0, fill: false },
                { label: 'Best Val', data: epochs.map(e => e.best_val_loss), borderColor: '#3fb950', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false },
            ]
        }, options: baseOpts
    });

    // Accuracy chart
    trainingCharts.acc = new Chart(document.getElementById(chartId2), {
        type: 'line', data: {
            labels,
            datasets: [
                { label: 'Train Top-1', data: epochs.map(e => e.train_top1), borderColor: '#58a6ff', borderWidth: 1.5, pointRadius: 0, fill: false },
                { label: 'Val Top-1', data: epochs.map(e => e.val_top1), borderColor: '#f85149', borderWidth: 1.5, pointRadius: 0, fill: false },
                { label: 'Val Top-3', data: epochs.map(e => e.val_top3), borderColor: '#d29922', borderWidth: 1.5, pointRadius: 0, fill: false },
            ]
        }, options: baseOpts
    });

    // Team/Lead chart
    if (document.getElementById('training-team-chart')) {
        trainingCharts.team = new Chart(document.getElementById('training-team-chart'), {
            type: 'line', data: {
                labels,
                datasets: [
                    { label: 'Team Select', data: epochs.map(e => e.team_acc), borderColor: '#bc8cff', borderWidth: 1.5, pointRadius: 0, fill: false },
                    { label: 'Lead Select', data: epochs.map(e => e.lead_acc), borderColor: '#3fb950', borderWidth: 1.5, pointRadius: 0, fill: false },
                ]
            }, options: baseOpts
        });

        trainingCharts.lr = new Chart(document.getElementById('training-lr-chart'), {
            type: 'line', data: {
                labels,
                datasets: [
                    { label: 'Learning Rate', data: epochs.map(e => e.lr), borderColor: '#8b949e', borderWidth: 1.5, pointRadius: 0, fill: false },
                ]
            }, options: { ...baseOpts, scales: { x: axisOpts, y: { ...axisOpts, type: 'logarithmic' } } }
        });
    }
}
