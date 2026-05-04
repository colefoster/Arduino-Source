// ═══════════════════════════════════════════════════════════════
// Training Progress
// ═══════════════════════════════════════════════════════════════
let trainingInited = false;
let trainingCharts = {};
let trainingRefreshTimer = null;
let trainingSelectedSession = null;
let trainingNotes = {};        // run_name -> {hypothesis, changes, result, freeform, updated}
let trainingSessionsHash = ''; // skip re-renders when listing didn't change
let trainingRefreshing = false;

async function trainingInit() {
    if (typeof compareInit === 'function') compareInit();
    if (trainingInited) { trainingRefresh(); return; }
    trainingInited = true;
    trainingShowSessionsSkeleton();
    await trainingRefresh();
    trainingRefreshTimer = setInterval(trainingRefresh, 15000);
}

function trainingShowSessionsSkeleton() {
    const c = document.getElementById('training-sessions');
    if (!c) return;
    const skeletons = Array.from({length: 4}).map(() =>
        '<div class="skeleton skeleton-card"></div>').join('');
    c.innerHTML = `<div style="display:flex; gap:12px; flex-wrap:wrap;">${skeletons}</div>`;
}

// Convert a past-run listing entry (from /api/runs/list) into the session
// shape the cards / detail panel expect. Action-model jsonl has its own
// metric vocabulary (val_type_a_acc, val_full_a_acc), so we surface the
// most informative one as top1 for the card preview.
function trainingPastRunToSession(r) {
    const last = r.last_epoch || {};
    const first = r.first_epoch || {};
    const top1 = last.val_type_a_acc != null
        ? Math.round(last.val_type_a_acc * 1000) / 10
        : (last.val_top1 != null ? last.val_top1 : null);
    return {
        session_id: 'past:' + r.name,
        machine: 'unraid',
        model_version: 'action',
        config: {
            dataset_size: first.samples || null,
            min_rating: null,
            device: 'RTX 4060',
        },
        started: r.mtime,
        last_update: r.mtime,
        current_epoch: last.epoch || r.num_epochs,
        total_epochs: last.epoch || r.num_epochs,
        latest_val_loss: last.val_loss != null ? last.val_loss : null,
        latest_val_top1: top1,
        best_val_loss: null,    // unknown without scanning all rows; chart will compute it
        active: false,
        num_epochs: r.num_epochs,
        _past: true,
    };
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
    if (trainingRefreshing) return;
    trainingRefreshing = true;
    try {
        const [liveSessions, pastRuns, notes] = await Promise.all([
            api('/api/training/sessions').catch(() => []),
            api('/api/runs/list').catch(() => []),
            api('/api/runs/notes').catch(() => ({})),
        ]);
        trainingNotes = notes || {};
        const sessions = [...liveSessions, ...pastRuns.map(trainingPastRunToSession)];
        const container = document.getElementById('training-sessions');

        if (!sessions.length) {
            container.innerHTML = '<div style="padding:16px; background:#161b22; border:1px solid #30363d; border-radius:8px; color:#484f58;">No training sessions yet. Start training with <code>--dashboard https://champions.colefoster.ca</code></div>';
            trainingSessionsHash = '';
            return;
        }

        // Skip re-render on auto-refresh tick if nothing changed — kills flicker.
        // Hash captures the live-changing fields plus selection.
        const hash = JSON.stringify({
            sel: trainingSelectedSession,
            rows: sessions.map(s => [
                s.session_id, s.active, s.current_epoch, s.total_epochs,
                s.latest_val_loss, s.latest_val_top1, s.best_val_loss,
            ]),
        });
        if (hash === trainingSessionsHash) {
            // Detail panel may still need to update for the live selected run.
            if (trainingSelectedSession) await trainingShowDetail(trainingSelectedSession, { silent: true });
            return;
        }
        trainingSessionsHash = hash;

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
    } finally {
        trainingRefreshing = false;
    }
}

async function trainingSelect(sessionId) {
    trainingSelectedSession = sessionId;
    // Re-render cards to update border
    await trainingRefresh();
}

async function trainingShowDetail(sessionId, opts) {
    opts = opts || {};
    const detail = document.getElementById('training-detail');
    if (detail && !opts.silent) {
        // Tiny placeholder while we fetch — kills the blank-flash on click.
        const runName = sessionId.startsWith('past:') ? sessionId.slice('past:'.length) : sessionId;
        detail.innerHTML = `
            <div class="loading-row"><span class="spinner"></span>Loading <code>${runName.replace(/[<>&]/g,'')}</code>...</div>
            <div class="grid-2">
                <div class="chart-box skeleton skeleton-chart"></div>
                <div class="chart-box skeleton skeleton-chart"></div>
            </div>`;
    }

    let data;
    if (sessionId.startsWith('past:')) {
        const name = sessionId.slice('past:'.length);
        const resp = await api('/api/runs/get?names=' + encodeURIComponent(name));
        const rows = resp[name] || [];
        let bestLoss = null;
        const epochs = rows.map(r => {
            if (r.val_loss != null && (bestLoss === null || r.val_loss < bestLoss)) bestLoss = r.val_loss;
            return {
                epoch: r.epoch,
                total_epochs: rows.length,
                train_loss: r.train_loss,
                val_loss: r.val_loss,
                // Map action-model heads onto the existing top1/top3 lines:
                //   Top-1 -> type accuracy (universal across all runs)
                //   Top-3 -> full-action accuracy (where available)
                train_top1: r.train_type_a_acc != null ? r.train_type_a_acc * 100 : null,
                val_top1: r.val_type_a_acc != null ? r.val_type_a_acc * 100 : null,
                val_top3: r.val_full_a_acc != null ? r.val_full_a_acc * 100 : null,
                team_acc: null,
                lead_acc: null,
                lr: null,
                best_val_loss: bestLoss,
            };
        });
        data = { epochs };
    } else {
        data = await api(`/api/training/session/${sessionId}`);
        if (data.error) return;
    }

    const epochs = data.epochs || [];

    // Run name for the notes key — past runs are 'past:<name>', strip the prefix.
    const runName = sessionId.startsWith('past:') ? sessionId.slice('past:'.length) : sessionId;
    const notesHtml = trainingRenderNotes(runName);

    if (!epochs.length) {
        detail.innerHTML = notesHtml +
            '<div style="color:#484f58; padding:12px;">No epochs recorded yet.</div>';
        return;
    }

    const chartId1 = 'training-loss-chart';
    const chartId2 = 'training-acc-chart';

    detail.innerHTML = notesHtml + `
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

// ── per-run research notes (Why / Diff / Result / freeform) ──────────────

function trainingRenderNotes(runName) {
    const n = trainingNotes[runName] || {};
    const updated = n.updated
        ? new Date(n.updated * 1000).toLocaleString()
        : null;
    const safe = (s) => (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const ta = (label, key, placeholder, rows) => `
        <div style="margin-bottom:8px;">
            <div style="font-size:10px; color:#8b949e; margin-bottom:2px; text-transform:uppercase; letter-spacing:0.5px;">${label}</div>
            <textarea id="notes-${key}" rows="${rows}" placeholder="${placeholder}"
                style="width:100%; box-sizing:border-box; background:#0d1117; color:#c9d1d9;
                       border:1px solid #30363d; border-radius:4px; padding:6px 8px;
                       font-family:inherit; font-size:12px; resize:vertical;">${safe(n[key])}</textarea>
        </div>`;
    return `
        <div class="card" style="padding:12px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <div style="font-size:13px; font-weight:600; color:#c9d1d9;">${safe(runName)}</div>
                <div style="display:flex; gap:8px; align-items:center;">
                    ${updated ? `<span style="font-size:10px; color:#484f58;">notes updated ${updated}</span>` : ''}
                    <button class="btn" onclick="trainingSaveNotes('${runName.replace(/'/g, "\\'")}')">Save notes</button>
                    <span id="notes-status" style="font-size:11px; color:#3fb950;"></span>
                </div>
            </div>
            ${ta('Hypothesis (why this run)', 'hypothesis', 'What we expected to learn from this run.', 2)}
            ${ta('Config delta (what changed vs prior best)', 'changes', 'e.g. +species/move features, d=192/l=6, --use-features', 2)}
            ${ta('Result (what we learned)', 'result', 'Filled in after the run completes — verdict + numbers.', 2)}
            ${ta('Freeform notes', 'freeform', 'Anything else — links, plans, follow-ups.', 3)}
        </div>`;
}

async function trainingSaveNotes(runName) {
    const fields = ['hypothesis', 'changes', 'result', 'freeform'];
    const body = { name: runName };
    for (const f of fields) {
        const el = document.getElementById('notes-' + f);
        if (el) body[f] = el.value;
    }
    const status = document.getElementById('notes-status');
    if (status) status.textContent = 'Saving...';
    try {
        const resp = await fetch(`${API}/api/runs/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).then(r => r.json());
        if (resp.ok) {
            trainingNotes[runName] = resp.notes;
            if (status) status.textContent = 'Saved';
            setTimeout(() => { if (status) status.textContent = ''; }, 1500);
        } else {
            if (status) { status.textContent = 'Error: ' + (resp.error || 'unknown'); status.style.color = '#f85149'; }
        }
    } catch (e) {
        if (status) { status.textContent = 'Error: ' + e; status.style.color = '#f85149'; }
    }
}
