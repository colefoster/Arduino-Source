// ===============================================================
// Pokeball Alive Detector
// ===============================================================
let pokeballsInited = false;
let pbOffset = 0;
const PB_PAGE = 50;

async function pokeballsInit() {
    if (pokeballsInited) return;
    pokeballsInited = true;
    document.getElementById('pb-prev').addEventListener('click', () => pbGo(-PB_PAGE));
    document.getElementById('pb-next').addEventListener('click', () => pbGo(+PB_PAGE));
    document.getElementById('pb-rerun').addEventListener('click', () => pbLoad());
    pbLoad();
}

function pbGo(delta) {
    pbOffset = Math.max(0, pbOffset + delta);
    pbLoad();
}

async function pbLoad() {
    document.getElementById('pb-summary').textContent = `Loading offset=${pbOffset}...`;
    document.getElementById('pb-rows').innerHTML = '';
    let d;
    try {
        const resp = await fetch(`${API}/api/pokeballs/scan?offset=${pbOffset}&limit=${PB_PAGE}`);
        const text = await resp.text();
        try { d = JSON.parse(text); }
        catch (e) {
            document.getElementById('pb-summary').innerHTML =
                `<span style="color:#f85149;">Bad JSON from /api/pokeballs/scan: ${e}</span><br><pre style="color:#8b949e; font-size:11px; max-height:200px; overflow:auto;">${text.slice(0, 800)}</pre>`;
            return;
        }
    } catch (e) {
        document.getElementById('pb-summary').innerHTML =
            `<span style="color:#f85149;">Fetch failed: ${e}</span>`;
        return;
    }
    renderPokeballs(d);
}

function pbDot(state) {
    if (state === 'alive') {
        return '<span title="alive" style="display:inline-block; width:18px; height:18px; background:#4ade80; border:2px solid #166534; border-radius:50%; margin:0 1px;"></span>';
    }
    if (state === 'fainted') {
        return '<span title="fainted" style="display:inline-block; width:18px; height:18px; background:#6b7280; border:2px solid #374151; border-radius:50%; margin:0 1px;"></span>';
    }
    if (state === 'empty') {
        return '<span title="empty" style="display:inline-block; width:6px; height:6px; background:#4b5563; border-radius:50%; margin:0 7px; vertical-align:middle;"></span>';
    }
    return '<span title="?" style="display:inline-block; width:18px; height:18px; background:#7f1d1d; border:2px solid #450a0a; border-radius:50%; margin:0 1px;"></span>';
}

function pbRow(states) {
    if (!states || states.length === 0) return '<span style="color:#f85149; font-size:11px;">no result</span>';
    return states.map(pbDot).join('');
}

function renderPokeballs(d) {
    const root = document.getElementById('pb-rows');
    const summary = document.getElementById('pb-summary');
    const frames = d.frames || [];
    const total = d.total || 0;
    const offset = d.offset || 0;
    const pageEnd = offset + frames.length;

    document.getElementById('pb-prev').disabled = (offset === 0);
    document.getElementById('pb-next').disabled = (pageEnd >= total);

    if (!frames.length) {
        summary.textContent = `Empty page (offset=${offset}, total=${total})`;
        return;
    }
    let errs = 0;
    frames.forEach(f => { if (f.error) errs++; });
    summary.textContent =
        `${offset+1}-${pageEnd} of ${total}` + (errs ? `  (${errs} error${errs!==1?'s':''})` : '');

    root.innerHTML = `
        <div style="display:grid; grid-template-columns:200px 80px 1fr 60px 1fr; gap:10px; align-items:center; padding:6px 8px; font-size:10px; color:#8b949e; text-transform:uppercase; border-bottom:1px solid #30363d; margin-bottom:4px;">
            <div>frame</div>
            <div>own count</div>
            <div>own 0..5</div>
            <div>opp count</div>
            <div>opp 0..5</div>
        </div>
        ${frames.map(f => {
            const errBadge = f.error ? `<span style="color:#f85149; font-size:11px;">err: ${String(f.error).slice(0,80)}</span>` : '';
            const thumb = `${API}/api/gallery/thumb/${encodeURIComponent(f.screen)}/${encodeURIComponent(f.filename)}`;
            return `<div style="display:grid; grid-template-columns:200px 80px 1fr 60px 1fr; gap:10px; align-items:center; padding:6px 8px; border-bottom:1px solid #21262d;">
                <div>
                    <a href="#/inspector?source=${encodeURIComponent('__test__/' + f.screen)}&filename=${encodeURIComponent(f.filename)}" title="${f.filename}">
                        <img src="${thumb}" style="width:200px; border:1px solid #30363d; border-radius:3px; display:block;">
                    </a>
                    <div style="font-size:9px; color:#8b949e; margin-top:2px;">${f.screen}/${f.filename.slice(0, 24)}</div>
                </div>
                <div style="font-size:14px; color:#c9d1d9; text-align:center;">${f.own_alive ?? '-'}</div>
                <div>${pbRow(f.own)} ${errBadge}</div>
                <div style="font-size:14px; color:#c9d1d9; text-align:center;">${f.opp_alive ?? '-'}</div>
                <div>${pbRow(f.opp)}</div>
            </div>`;
        }).join('')}
    `;
}
