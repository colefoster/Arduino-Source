// ═══════════════════════════════════════════════════════════════
// Sprite Recognition
// ═══════════════════════════════════════════════════════════════
let spritesInited = false;
let spritesAllNames = [];

async function spritesInit() {
    if (spritesInited) return;
    spritesInited = true;

    try {
        const list = await api('/api/sprites/list');
        spritesAllNames = list.names || [];
    } catch (e) { spritesAllNames = []; }

    try {
        const bh = await api('/api/sprites/battlehud_examples?aggregate=true&limit=80');
        renderBattleHudRows(bh.rows || []);
    } catch (e) {
        document.getElementById('bh-examples').innerHTML =
            '<div style="color:#f85149;">Failed to load BattleHUD examples</div>';
    }
}

function bhStripShiny(slug) {
    return slug && slug.endsWith('-shiny') ? slug.slice(0, -'-shiny'.length) : (slug || '');
}

function renderBattleHudRows(rows) {
    const root = document.getElementById('bh-examples');
    const summary = document.getElementById('bh-summary');
    if (!rows.length) {
        root.innerHTML = '<div style="color:#484f58; font-size:12px;">No labeled action_menu frames with own_species labels</div>';
        return;
    }

    const stats = { 0: { ok: 0, n: 0 }, 1: { ok: 0, n: 0 } };
    rows.forEach(r => {
        if (!r.ground_truth) return;
        const s = stats[r.slot]; if (!s) return;
        s.n++; if (r.top_correct) s.ok++;
    });
    summary.textContent =
        `(slot 0: ${stats[0].ok}/${stats[0].n} top-1, slot 1: ${stats[1].ok}/${stats[1].n} top-1; one row per unique species)`;

    const optionsHtml = (selected) => {
        const list = spritesAllNames.length ? spritesAllNames : (selected ? [selected] : []);
        const has = list.includes(selected);
        const opts = (has ? '' : `<option value="${selected}" selected>${selected}</option>`) +
            list.map(n => `<option value="${n}"${n===selected?' selected':''}>${n}</option>`).join('');
        return `<option value="">(none)</option>${opts}`;
    };

    root.innerHTML = `
        <div style="display:grid; grid-template-columns:50px 100px 100px 100px 1fr; gap:8px; align-items:center; padding:6px 8px; font-size:10px; color:#8b949e; text-transform:uppercase; border-bottom:1px solid #30363d; margin-bottom:4px;">
            <div>slot</div>
            <div>crop</div>
            <div>after auto-crop</div>
            <div>atlas ref (truth)</div>
            <div>top-3 matches</div>
        </div>
        ${rows.map((r, idx) => {
            const matches = (r.matches || []).slice(0, 3);
            const matchHtml = matches.length
                ? matches.map((m, i) => {
                    const ok = bhStripShiny(m.slug) === r.ground_truth &&
                              (m.slug.endsWith('-shiny') === !!r.ground_truth_shiny);
                    return `<span style="display:inline-flex; gap:4px; align-items:center; margin-right:10px; font-size:11px;">
                        <img src="${API}/api/teampreview/sprite/${encodeURIComponent(m.slug)}" style="width:24px; height:24px; image-rendering:pixelated; background:#0d1117; border:1px solid #30363d; border-radius:2px;">
                        <span style="color:${ok ? '#3fb950' : '#8b949e'}; font-weight:${i===0?'bold':'normal'};">${m.slug}</span>
                        <span style="color:#6e7681; font-family:monospace;">${m.alpha.toFixed(3)}</span>
                    </span>`;
                }).join('')
                : '<span style="color:#f85149; font-size:11px;">no matches</span>';
            const truthColor = r.top_correct ? '#3fb950' : '#f85149';
            const truthSlug = r.ground_truth_shiny ? `${r.ground_truth}-shiny` : r.ground_truth;
            const refId = `bh-ref-${idx}`;
            const selId = `bh-sel-${idx}`;
            const autoCropImg = r.auto_crop
                ? `<img src="${r.auto_crop}" style="width:96px; image-rendering:pixelated; border:1px solid #30363d; border-radius:3px; background:#0d1117;">`
                : `<div style="width:96px; height:60px; background:#21262d; border:1px dashed #30363d; border-radius:3px; display:flex; align-items:center; justify-content:center; color:#484f58; font-size:10px;">n/a</div>`;
            return `<div style="display:grid; grid-template-columns:50px 100px 100px 100px 1fr; gap:8px; align-items:center; padding:6px 8px; border-bottom:1px solid #21262d;">
                <div style="font-size:11px; color:${truthColor};">${r.slot}${r.ground_truth_shiny?' &#10024;':''}</div>
                <img src="${r.crop}" style="width:96px; image-rendering:pixelated; border:1px solid #30363d; border-radius:3px;">
                ${autoCropImg}
                <div style="display:flex; flex-direction:column; gap:3px;">
                    <img id="${refId}" src="${API}/api/teampreview/sprite/${encodeURIComponent(truthSlug)}" style="width:96px; height:96px; image-rendering:pixelated; background:#0d1117; border:1px solid #30363d; border-radius:3px; object-fit:contain;">
                    <select id="${selId}" data-ref="${refId}" class="bh-ref-select"
                            style="width:96px; background:#0d1117; border:1px solid #30363d; color:#c9d1d9; padding:2px 4px; border-radius:3px; font-family:inherit; font-size:10px;">
                        ${optionsHtml(truthSlug)}
                    </select>
                </div>
                <div>
                    <div style="font-size:11px; color:${truthColor}; margin-bottom:4px;">truth: <b>${truthSlug}</b></div>
                    <div>${matchHtml}</div>
                </div>
            </div>`;
        }).join('')}
    `;

    root.querySelectorAll('.bh-ref-select').forEach(sel => {
        sel.addEventListener('change', e => {
            const slug = e.target.value;
            const img = document.getElementById(e.target.dataset.ref);
            if (!img) return;
            if (slug) {
                img.src = `${API}/api/teampreview/sprite/${encodeURIComponent(slug)}`;
                img.style.display = 'block';
            } else {
                img.removeAttribute('src');
                img.style.display = 'none';
            }
        });
    });
}

