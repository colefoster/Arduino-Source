// ===============================================================
// Pokemon Switch Detector Probe
// ===============================================================
let switchProbeInited = false;

async function switchProbeInit() {
    if (switchProbeInited) return;
    switchProbeInited = true;
    document.getElementById('sp-rerun').addEventListener('click', spLoad);
    spLoad();
}

function spStateBadge(state) {
    const colors = {
        'active':   { bg: '#1a4d1a', fg: '#4ade80', label: 'ACTIVE' },
        'inactive': { bg: '#1e2d4d', fg: '#60a5fa', label: 'INACTIVE' },
        'neither':  { bg: '#4d2a1a', fg: '#fbbf24', label: 'NEITHER' },
    };
    const c = colors[state] || colors['neither'];
    return `<span style="background:${c.bg}; color:${c.fg}; padding:2px 6px; border-radius:3px; font-size:10px; font-weight:bold;">${c.label}</span>`;
}

function spReaderBlock(f) {
    if (f.reader_error) {
        return `<div style="color:#f85149; font-size:11px;">Reader error: ${f.reader_error}</div>`;
    }
    const r = f.reader;
    if (!r) {
        return `<div style="color:#8b949e; font-size:11px;">No reader output.</div>`;
    }
    const sel = (typeof r.selected_own_slot === 'number') ? r.selected_own_slot : -1;
    const ownRows = (r.own || []).map((s, i) => {
        const isSel = (i === sel);
        const fainted = (s.hp_max > 0 && s.hp_current === 0);
        const hp = (s.hp_max < 0) ? '—' : `${s.hp_current}/${s.hp_max}`;
        const sp = s.species || '<span style="color:#6e7681;">—</span>';
        const bg = isSel ? 'background:#3a3a1a;' : '';
        const hpColor = fainted ? '#f85149' : '#c9d1d9';
        return `<tr style="${bg}">
            <td style="padding:2px 6px; font-family:monospace; font-size:11px; color:#8b949e;">${i}${isSel ? ' ▸' : ''}</td>
            <td style="padding:2px 6px; font-size:11px;">${sp}</td>
            <td style="padding:2px 6px; font-family:monospace; font-size:11px; color:${hpColor};">${hp}</td>
        </tr>`;
    }).join('');
    const oppRows = (r.opp || []).map((s, i) => {
        const pct = (s.hp_pct < 0) ? '—' : `${s.hp_pct}%`;
        return `<tr>
            <td style="padding:2px 6px; font-family:monospace; font-size:11px; color:#8b949e;">${i}</td>
            <td style="padding:2px 6px; font-family:monospace; font-size:11px; color:#c9d1d9;">${pct}</td>
        </tr>`;
    }).join('');
    return `
        <div style="font-size:10px; color:#6e7681; text-transform:uppercase; margin-bottom:4px;">PokemonSwitchReader</div>
        <div style="font-size:11px; color:#c9d1d9; margin-bottom:6px;">selected_own_slot: <b>${sel}</b>${sel < 0 ? ' <span style="color:#f85149;">(no highlight)</span>' : ''}</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
            <table style="width:100%; border-collapse:collapse;">
                <thead><tr style="border-bottom:1px solid #30363d;">
                    <th colspan="3" style="padding:2px 6px; text-align:left; font-size:10px; color:#6e7681; text-transform:uppercase;">own</th>
                </tr></thead>
                <tbody>${ownRows}</tbody>
            </table>
            <table style="width:100%; border-collapse:collapse;">
                <thead><tr style="border-bottom:1px solid #30363d;">
                    <th colspan="2" style="padding:2px 6px; text-align:left; font-size:10px; color:#6e7681; text-transform:uppercase;">opp hp%</th>
                </tr></thead>
                <tbody>${oppRows}</tbody>
            </table>
        </div>
    `;
}

function spRgbCell(avg) {
    const [r, g, b] = avg;
    const swatch = `rgb(${Math.min(255, r)|0}, ${Math.min(255, g)|0}, ${Math.min(255, b)|0})`;
    return `<span style="display:inline-block; width:12px; height:12px; background:${swatch}; border:1px solid #30363d; vertical-align:middle; margin-right:4px;"></span>` +
           `<span style="font-family:monospace; font-size:11px; color:#c9d1d9;">${r.toFixed(1)}, ${g.toFixed(1)}, ${b.toFixed(1)}</span>`;
}

async function spLoad() {
    document.getElementById('sp-summary').textContent = 'Loading...';
    document.getElementById('sp-rows').innerHTML = '';
    let d;
    try {
        const resp = await fetch(`${API}/api/switchprobe/scan`);
        const text = await resp.text();
        try { d = JSON.parse(text); }
        catch (e) {
            document.getElementById('sp-summary').innerHTML =
                `<span style="color:#f85149;">Bad JSON: ${e}</span><br><pre style="color:#8b949e; font-size:11px; max-height:200px; overflow:auto;">${text.slice(0, 800)}</pre>`;
            return;
        }
    } catch (e) {
        document.getElementById('sp-summary').innerHTML =
            `<span style="color:#f85149;">Fetch failed: ${e}</span>`;
        return;
    }
    spRender(d);
}

function spRender(d) {
    const root = document.getElementById('sp-rows');
    const summary = document.getElementById('sp-summary');
    const frames = d.frames || [];
    const passed = frames.filter(f => f.verdict).length;
    const failed = frames.length - passed;
    summary.innerHTML =
        `${frames.length} image${frames.length!==1?'s':''} · ` +
        `<span style="color:#4ade80;">${passed} pass</span> · ` +
        `<span style="color:#f85149;">${failed} fail</span> · ` +
        `thresholds: active=<code>${d.thresholds.active}</code>, inactive=<code>${d.thresholds.inactive}</code>`;

    if (!frames.length) {
        root.innerHTML = '<div style="color:#8b949e;">No images in test_images/pokemon_switch/.</div>';
        return;
    }

    root.innerHTML = frames.map(f => {
        if (f.error) {
            return `<div style="padding:10px; border:1px solid #30363d; margin-bottom:8px;">
                <b>${f.filename}</b> <span style="color:#f85149;">error: ${f.error}</span>
            </div>`;
        }
        const verdictBadge = f.verdict
            ? '<span style="background:#1a4d1a; color:#4ade80; padding:4px 10px; border-radius:4px; font-weight:bold;">PASS</span>'
            : '<span style="background:#4d1a1a; color:#f85149; padding:4px 10px; border-radius:4px; font-weight:bold;">FAIL</span>';
        const thumb = `${API}/api/gallery/thumb/${encodeURIComponent('pokemon_switch')}/${encodeURIComponent(f.filename)}`;
        const rows = (f.boxes || []).map(b =>
            `<tr>
                <td style="padding:4px 8px; font-family:monospace; font-size:11px; color:#8b949e;">${b.name}</td>
                <td style="padding:4px 8px;">${spStateBadge(b.state)}</td>
                <td style="padding:4px 8px;">${spRgbCell(b.avg)}</td>
                <td style="padding:4px 8px; font-family:monospace; font-size:10px; color:#6e7681;">${b.box.map(v => v.toFixed(4)).join(', ')}</td>
            </tr>`
        ).join('');
        return `<div style="display:grid; grid-template-columns:300px 1fr 1fr; gap:16px; padding:12px; border:1px solid #30363d; border-radius:6px; margin-bottom:10px; background:#0d1117;">
            <div>
                <a href="#/inspector?source=${encodeURIComponent('__test__/pokemon_switch')}&filename=${encodeURIComponent(f.filename)}">
                    <img src="${thumb}" style="width:300px; border:1px solid #30363d; border-radius:3px; display:block;">
                </a>
                <div style="font-size:10px; color:#8b949e; margin-top:4px; word-break:break-all;">${f.filename}</div>
            </div>
            <div>
                <div style="margin-bottom:8px;">${verdictBadge} <span style="color:#8b949e; margin-left:8px; font-size:12px;">${f.explanation}</span></div>
                <table style="width:100%; border-collapse:collapse;">
                    <thead><tr style="border-bottom:1px solid #30363d;">
                        <th style="padding:4px 8px; text-align:left; font-size:10px; color:#6e7681; text-transform:uppercase;">box</th>
                        <th style="padding:4px 8px; text-align:left; font-size:10px; color:#6e7681; text-transform:uppercase;">state</th>
                        <th style="padding:4px 8px; text-align:left; font-size:10px; color:#6e7681; text-transform:uppercase;">avg rgb</th>
                        <th style="padding:4px 8px; text-align:left; font-size:10px; color:#6e7681; text-transform:uppercase;">x, y, w, h</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <div>${spReaderBlock(f)}</div>
        </div>`;
    }).join('');
}
