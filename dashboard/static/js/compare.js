// ===============================================================
// Compare Runs - overlay past training runs from unraid jsonl logs
// ===============================================================

let compareInited = false;
let compareRuns = [];           // listing from /api/runs/list
let compareSelected = new Set();
let compareData = {};           // name -> rows
let compareChart = null;

// Distinct, color-blind-friendly palette for line overlays.
const COMPARE_PALETTE = [
    '#58a6ff', '#f85149', '#3fb950', '#d29922', '#bc8cff',
    '#ff7b72', '#79c0ff', '#a5d6ff', '#ffa657', '#7ee787',
    '#f0883e', '#d2a8ff',
];

// Metrics we know are "lower is better"; everything else assumed accuracy.
const COMPARE_LOWER_BETTER = new Set(['train_loss', 'val_loss', 'best_val_loss']);

async function compareInit() {
    if (compareInited) { compareRefresh(); return; }
    compareInited = true;
    document.getElementById('compare-metric').addEventListener('change', compareRender);
    document.getElementById('compare-xaxis').addEventListener('change', compareRender);
    await compareRefresh();
}

async function compareRefresh() {
    const runsEl = document.getElementById('compare-runs');
    if (runsEl && !compareRuns.length) {
        // First load: skeleton placeholders so the sidebar isn't blank.
        runsEl.innerHTML = Array.from({length: 6}).map(() =>
            '<div class="skeleton" style="height:54px; border:1px solid #21262d; border-radius:6px;"></div>'
        ).join('');
    }
    setStatus('<span class="spinner"></span> Loading runs...');
    try {
        compareRuns = await api('/api/runs/list');
    } catch (e) {
        setStatus('Failed to load runs: ' + e);
        return;
    }
    if (!compareRuns.length) {
        if (runsEl) runsEl.innerHTML =
            '<div style="color:#484f58; padding:12px;">No runs found.</div>';
        setStatus('');
        return;
    }
    if (!compareSelected.size) compareSelected.add(compareRuns[0].name);

    populateMetricDropdown();
    renderRunList();
    setStatus('<span class="spinner"></span> Loading run data...');
    await loadSelected();
    compareRender();
    setStatus('');
}

function populateMetricDropdown() {
    const sel = document.getElementById('compare-metric');
    const prev = sel.value;
    const keys = new Set();
    for (const r of compareRuns) {
        for (const row of [r.first_epoch, r.last_epoch]) {
            for (const [k, v] of Object.entries(row || {})) {
                if (typeof v === 'number' && k !== 'epoch' && k !== 'samples') keys.add(k);
            }
        }
    }
    // Order: losses first, then accuracies
    const order = [
        'val_loss', 'train_loss', 'best_val_loss',
        'val_full_a_acc', 'val_full_b_acc',
        'val_type_a_acc', 'train_type_a_acc',
        'val_move_a_acc', 'val_target_a_acc', 'val_switch_a_acc',
        'val_top1', 'val_top3', 'train_top1', 'train_top3',
        'team_acc', 'lead_acc', 'lr',
    ];
    const sorted = [...keys].sort((a, b) => {
        const ai = order.indexOf(a), bi = order.indexOf(b);
        if (ai === -1 && bi === -1) return a.localeCompare(b);
        if (ai === -1) return 1;
        if (bi === -1) return -1;
        return ai - bi;
    });
    sel.innerHTML = sorted.map(k => `<option value="${k}">${k}</option>`).join('');
    if (sorted.includes(prev)) sel.value = prev;
    else if (sorted.includes('val_loss')) sel.value = 'val_loss';
}

function renderRunList() {
    const metric = document.getElementById('compare-metric').value;
    const html = compareRuns.map(r => {
        const last = r.last_epoch || {};
        const checked = compareSelected.has(r.name) ? 'checked' : '';
        const date = new Date(r.mtime * 1000).toLocaleString();
        const metricVal = (metric in last) ? formatNum(last[metric]) : '--';
        return `<label class="card" style="display:flex; gap:8px; align-items:flex-start; cursor:pointer; padding:8px;">
            <input type="checkbox" ${checked} onchange="compareToggle('${r.name}', this.checked)" style="margin-top:3px;">
            <div style="flex:1; min-width:0;">
                <div style="font-size:12px; color:#c9d1d9; font-weight:600; word-break:break-all;">${r.name}</div>
                <div style="font-size:10px; color:#8b949e;">${date} - ${r.num_epochs} ep</div>
                <div style="font-size:10px; color:#58a6ff; margin-top:2px;">${metric}: ${metricVal}</div>
            </div>
        </label>`;
    }).join('');
    document.getElementById('compare-runs').innerHTML = html;
}

async function compareToggle(name, on) {
    if (on) compareSelected.add(name);
    else compareSelected.delete(name);
    if (on && !(name in compareData)) setStatus('<span class="spinner"></span> Loading ' + name + '...');
    await loadSelected();
    compareRender();
    setStatus('');
}

function compareSelectAll(on) {
    compareSelected = new Set(on ? compareRuns.map(r => r.name) : []);
    renderRunList();
    loadSelected().then(compareRender);
}

async function loadSelected() {
    const need = [...compareSelected].filter(n => !(n in compareData));
    if (!need.length) return;
    setStatus('<span class="spinner"></span> Loading ' + need.length + ' run' + (need.length === 1 ? '' : 's') + '...');
    const data = await api('/api/runs/get?names=' + encodeURIComponent(need.join(',')));
    Object.assign(compareData, data);
    setStatus('');
}

function compareRender() {
    const metric = document.getElementById('compare-metric').value;
    const xaxis = document.getElementById('compare-xaxis').value;
    if (!metric) return;

    renderRunList(); // refresh per-row metric value

    const datasets = [];
    let i = 0;
    for (const name of compareSelected) {
        const rows = compareData[name];
        if (!rows || !rows.length) continue;
        const points = rowsToPoints(rows, metric, xaxis);
        if (!points.length) continue;
        datasets.push({
            label: name,
            data: points,
            borderColor: COMPARE_PALETTE[i % COMPARE_PALETTE.length],
            backgroundColor: COMPARE_PALETTE[i % COMPARE_PALETTE.length],
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.0,
            fill: false,
        });
        i++;
    }

    document.getElementById('compare-chart-title').textContent =
        `${metric} vs. ${xaxis === 'epoch' ? 'epoch' : xaxis === 'samples' ? 'samples seen' : 'wall-clock (min)'}`;

    const axisOpts = { ticks: { color: '#484f58', font: { size: 10 } }, grid: { color: '#21262d' } };
    if (compareChart) compareChart.destroy();
    compareChart = new Chart(document.getElementById('compare-chart'), {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: { legend: { labels: { color: '#8b949e', font: { size: 10 } } } },
            scales: {
                x: { type: 'linear', ...axisOpts, title: { display: true, text: xaxis, color: '#484f58', font: { size: 10 } } },
                y: { ...axisOpts, title: { display: true, text: metric, color: '#484f58', font: { size: 10 } } },
            },
        },
    });

    renderTable(metric);
}

function rowsToPoints(rows, metric, xaxis) {
    const pts = [];
    let cumSec = 0;
    for (const r of rows) {
        cumSec += (r.train_took_sec || 0) + (r.val_took_sec || 0);
        const y = r[metric];
        if (typeof y !== 'number') continue;
        let x;
        if (xaxis === 'epoch') x = r.epoch;
        else if (xaxis === 'samples') x = (r.samples || 0) * (r.epoch || 0);
        else x = cumSec / 60.0;
        if (typeof x !== 'number') continue;
        pts.push({ x, y });
    }
    return pts;
}

function renderTable(metric) {
    const lowerBetter = COMPARE_LOWER_BETTER.has(metric) || metric.endsWith('_loss');
    const rows = [];
    for (const name of compareSelected) {
        const data = compareData[name];
        if (!data || !data.length) continue;
        const finalRow = data[data.length - 1];
        const finalVal = finalRow[metric];
        // best
        let bestVal = null, bestEpoch = null;
        for (const r of data) {
            const v = r[metric];
            if (typeof v !== 'number') continue;
            if (bestVal === null || (lowerBetter ? v < bestVal : v > bestVal)) {
                bestVal = v; bestEpoch = r.epoch;
            }
        }
        rows.push({ name, finalVal, finalEpoch: finalRow.epoch, bestVal, bestEpoch, numEpochs: data.length });
    }
    rows.sort((a, b) => {
        if (a.bestVal === null) return 1;
        if (b.bestVal === null) return -1;
        return lowerBetter ? a.bestVal - b.bestVal : b.bestVal - a.bestVal;
    });

    if (!rows.length) {
        document.getElementById('compare-table').innerHTML = '';
        return;
    }
    const baseline = rows[0].bestVal;
    const header = `<tr style="text-align:left; color:#8b949e; font-size:11px; border-bottom:1px solid #30363d;">
        <th style="padding:6px;">Run</th>
        <th style="padding:6px;">Final ${metric}</th>
        <th style="padding:6px;">Best ${metric}</th>
        <th style="padding:6px;">Best epoch</th>
        <th style="padding:6px;">vs leader</th>
        <th style="padding:6px;">Epochs</th>
    </tr>`;
    const body = rows.map((r, i) => {
        const delta = (r.bestVal !== null && baseline !== null) ? r.bestVal - baseline : null;
        const deltaStr = delta === null ? '--' : (i === 0 ? '<span style="color:#3fb950;">leader</span>' : (lowerBetter ? '+' : '') + formatNum(delta));
        const deltaColor = (delta === null || i === 0) ? '' : (lowerBetter ? (delta > 0 ? '#f85149' : '#3fb950') : (delta < 0 ? '#f85149' : '#3fb950'));
        return `<tr style="border-bottom:1px solid #21262d;">
            <td style="padding:6px; font-size:12px; color:#c9d1d9; word-break:break-all;">${r.name}</td>
            <td style="padding:6px; font-size:12px; color:#8b949e;">${formatNum(r.finalVal)} <span style="color:#484f58; font-size:10px;">@${r.finalEpoch}</span></td>
            <td style="padding:6px; font-size:12px; color:#c9d1d9;">${formatNum(r.bestVal)}</td>
            <td style="padding:6px; font-size:12px; color:#8b949e;">${r.bestEpoch ?? '--'}</td>
            <td style="padding:6px; font-size:12px; color:${deltaColor};">${deltaStr}</td>
            <td style="padding:6px; font-size:12px; color:#8b949e;">${r.numEpochs}</td>
        </tr>`;
    }).join('');
    document.getElementById('compare-table').innerHTML =
        `<table style="width:100%; border-collapse:collapse;">${header}${body}</table>`;
}

function formatNum(v) {
    if (typeof v !== 'number' || isNaN(v)) return '--';
    if (Math.abs(v) >= 1000) return v.toFixed(0);
    if (Math.abs(v) >= 1) return v.toFixed(4);
    if (Math.abs(v) >= 0.01) return v.toFixed(4);
    return v.toExponential(2);
}

function setStatus(s) {
    const el = document.getElementById('compare-status');
    if (el) el.innerHTML = s || '';
}
