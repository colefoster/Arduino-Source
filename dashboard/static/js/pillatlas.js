// HUD Pill Atlas view
let pillAtlasInited = false;
let pillAtlasSpeciesByside = { opp: [], own: [] };
let pillAtlasAllSpecies = [];

async function pillAtlasInit() {
    const grid = document.getElementById('pa-grid');
    const status = document.getElementById('pa-status');
    grid.innerHTML = '';
    status.textContent = 'Loading atlas...';
    try {
        const data = await api('/api/hud-pill-atlas');
        if (data.error) {
            status.textContent = 'Error: ' + data.error;
            return;
        }
        const sides = data.sides || {};
        const sideNames = ['opp', 'own'];
        let totalSpecies = 0, totalRefs = 0;
        pillAtlasSpeciesByside = {
            opp: Object.keys(sides.opp || {}).sort(),
            own: Object.keys(sides.own || {}).sort(),
        };
        pillAtlasAllSpecies = Array.from(new Set([...pillAtlasSpeciesByside.opp, ...pillAtlasSpeciesByside.own])).sort();
        for (const side of sideNames) {
            const species = sides[side] || {};
            const sortedNames = Object.keys(species).sort();
            if (!sortedNames.length) continue;
            const sect = document.createElement('div');
            sect.className = 'pa-side-section';
            const head = document.createElement('div');
            head.className = 'pa-side-header';
            const totalSideRefs = sortedNames.reduce((acc, n) => acc + species[n].count, 0);
            head.textContent = `${side.toUpperCase()} side — ${sortedNames.length} species, ${totalSideRefs} reference crops`;
            totalSpecies += sortedNames.length;
            totalRefs += totalSideRefs;
            sect.appendChild(head);
            const gridEl = document.createElement('div');
            gridEl.className = 'pa-species-grid';
            for (const name of sortedNames) {
                const info = species[name];
                const card = document.createElement('div');
                card.className = 'pa-species-card';
                if (info.count < 3) card.classList.add('pa-thin');
                card.dataset.species = name;
                card.dataset.side = side;
                const meanHtml = info.mean_thumb
                    ? `<img class="mean-thumb" src="${info.mean_thumb}" alt="${name}">`
                    : '<div class="mean-thumb"></div>';
                card.innerHTML = `
                    ${meanHtml}
                    <div class="name">${name}</div>
                    <div class="count">${info.count} ref${info.count === 1 ? '' : 's'}</div>
                `;
                card.addEventListener('click', (ev) => {
                    if (ev.target.closest('.pa-bulk-toolbar')) return;
                    if (ev.target.closest('.refs')) return;
                    if (ev.target.matches('input,label,datalist,option')) return;
                    paToggleExpand(card, info);
                });
                gridEl.appendChild(card);
            }
            sect.appendChild(gridEl);
            grid.appendChild(sect);
        }
        status.textContent = `Atlas: ${totalSpecies} entries across both sides, ${totalRefs} reference crops total. Yellow border = thin (<3 refs).`;
        pillAtlasInited = true;
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    }
}

function paToggleExpand(card, info) {
    if (card.classList.contains('expanded')) {
        card.classList.remove('expanded');
        const refsDiv = card.querySelector('.refs');
        if (refsDiv) refsDiv.remove();
        const tb = card.querySelector('.pa-bulk-toolbar');
        if (tb) tb.remove();
        const dl = card.querySelector('datalist');
        if (dl) dl.remove();
        return;
    }
    card.classList.add('expanded');
    const side = card.dataset.side;
    const sideSpecies = pillAtlasSpeciesByside[side] || [];
    const dlId = `pa-species-dl-${side}-${info && info.refs && info.refs[0] ? info.refs[0].slot : 'x'}-${Math.random().toString(36).slice(2,7)}`;
    const datalist = document.createElement('datalist');
    datalist.id = dlId;
    for (const sp of sideSpecies) {
        const opt = document.createElement('option');
        opt.value = sp;
        datalist.appendChild(opt);
    }
    card.appendChild(datalist);

    const toolbar = document.createElement('div');
    toolbar.className = 'pa-bulk-toolbar';
    toolbar.innerHTML = `
        <label style="display:flex; align-items:center; gap:4px; font-size:11px; color:#8b949e; cursor:pointer;">
            <input type="checkbox" class="pa-select-all"> select all
        </label>
        <span class="pa-selected-count" style="font-size:11px; color:#8b949e;">0 selected</span>
        <span style="flex:1"></span>
        <input type="text" class="pa-move-target" list="${dlId}" placeholder="target species (e.g. charizard-mega)" style="background:#0d1117; border:1px solid #30363d; color:#c9d1d9; font-family:ui-monospace,monospace; font-size:11px; padding:3px 6px; border-radius:4px; min-width:220px;">
        <button class="btn pa-move-btn" style="font-size:11px; padding:3px 10px; border-color:#3fb950; color:#3fb950;" disabled>Move selected</button>
        <span class="pa-move-status" style="font-size:11px; color:#8b949e; min-width:120px;"></span>
    `;
    card.appendChild(toolbar);

    const refsDiv = document.createElement('div');
    refsDiv.className = 'refs';
    for (const r of (info.refs || [])) {
        const cell = document.createElement('div');
        cell.className = 'ref-cell';
        cell.dataset.ref = r.ref;
        cell.innerHTML = `
            <label style="position:relative; cursor:pointer; display:block; width:100%;">
                <input type="checkbox" class="pa-ref-check" style="position:absolute; top:2px; left:2px; z-index:1; cursor:pointer;">
                <img src="/api/hud-pill-atlas/ref/${encodeURIComponent(r.ref)}" alt="${r.ref}">
            </label>
            <div class="ref-name">${r.source_frame.replace('.png','')}<br>slot ${r.slot}</div>
        `;
        refsDiv.appendChild(cell);
    }
    card.appendChild(refsDiv);
}

function paUpdateBulkUI(card) {
    const checks = card.querySelectorAll('.pa-ref-check');
    const checked = Array.from(checks).filter(c => c.checked);
    const countEl = card.querySelector('.pa-selected-count');
    const btn = card.querySelector('.pa-move-btn');
    const target = card.querySelector('.pa-move-target');
    const sa = card.querySelector('.pa-select-all');
    if (countEl) countEl.textContent = `${checked.length} selected`;
    if (btn) btn.disabled = !checked.length || !(target && target.value.trim());
    if (sa) sa.checked = checks.length > 0 && checked.length === checks.length;
}

async function paBulkMove(card) {
    const target = card.querySelector('.pa-move-target').value.trim();
    if (!target) return;
    const checks = Array.from(card.querySelectorAll('.pa-ref-check')).filter(c => c.checked);
    if (!checks.length) return;
    const sourceSp = card.dataset.species;
    if (target === sourceSp) {
        alert('Target species is the same as current. Pick a different one.');
        return;
    }
    if (!/^[a-z0-9-]+$/.test(target)) {
        if (!confirm(`Target "${target}" is not lowercase-slug format. Continue anyway?`)) return;
    }
    if (!confirm(`Move ${checks.length} crop${checks.length === 1 ? '' : 's'} from ${sourceSp} to ${target}?`)) return;
    const btn = card.querySelector('.pa-move-btn');
    const status = card.querySelector('.pa-move-status');
    const targetInput = card.querySelector('.pa-move-target');
    btn.disabled = true; targetInput.disabled = true;
    let ok = 0, fail = 0;
    for (let i = 0; i < checks.length; i++) {
        const cell = checks[i].closest('.ref-cell');
        const ref = cell.dataset.ref;
        status.textContent = `Updating ${i + 1}/${checks.length} (ok: ${ok}, fail: ${fail})`;
        try {
            const r = await fetch('/api/hud-pill-atlas/relabel', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ref, new_species: target})
            }).then(r => r.json());
            if (r.ok) {
                ok++;
                cell.style.transition = 'opacity 0.2s';
                cell.style.opacity = '0.3';
                checks[i].checked = false;
                checks[i].disabled = true;
            } else {
                fail++;
                cell.style.outline = '2px solid #f85149';
            }
        } catch (e) {
            fail++;
            cell.style.outline = '2px solid #f85149';
        }
    }
    status.textContent = `Done — ${ok} moved to ${target}, ${fail} failed. Rebuild atlas to refresh card counts.`;
    status.style.color = fail ? '#d29922' : '#3fb950';
    targetInput.disabled = false;
    paUpdateBulkUI(card);
}

async function paRunAudit() {
    const btn = document.getElementById('pa-audit-btn');
    const status = document.getElementById('pa-audit-status');
    const results = document.getElementById('pa-audit-results');
    btn.disabled = true; status.textContent = 'Auditing...';
    try {
        const data = await api('/api/hud-pill-atlas/audit');
        if (data.error) { status.textContent = 'Error: ' + data.error; return; }
        const suspects = data.suspects || [];
        const unknowns = data.unknowns || [];
        const thr = data.unknown_threshold;
        status.textContent = `${suspects.length} mislabel suspect${suspects.length === 1 ? '' : 's'}, ${unknowns.length} out-of-atlas (RMSD ≥ ${thr})`;
        results.innerHTML = '';
        results.style.display = '';
        if (unknowns.length) {
            const uHeader = document.createElement('div');
            uHeader.style.cssText = 'font-size: 13px; font-weight: 600; color: #d29922; margin-bottom: 8px;';
            uHeader.textContent = `${unknowns.length} crops where even the best atlas match is poor (RMSD ≥ ${thr}). Likely new species, new variants, or thin atlas coverage. Sorted by best-match RMSD desc.`;
            results.appendChild(uHeader);
            for (const u of unknowns) {
                const card = document.createElement('div');
                card.className = 'pa-suspect-card';
                card.style.borderColor = '#d29922';
                const refUrl = `/api/hud-pill-atlas/ref/${encodeURIComponent(u.ref)}`;
                card.innerHTML = `
                    <div class="col">
                        <div class="label">crop (${u.side} ${u.slot})</div>
                        <img src="${refUrl}" alt="">
                    </div>
                    <div class="col labeled">
                        <div class="label">labeled</div>
                        <div class="name">${u.labeled_species}</div>
                        <div class="rmsd">RMSD ${u.rmsd_labeled ?? '-'}</div>
                    </div>
                    <div class="col" style="background:#2d2210; border:1px solid #d29922;">
                        <div class="label">closest match</div>
                        <div class="name">${u.best_match}</div>
                        <div class="rmsd">RMSD ${u.rmsd_best}</div>
                    </div>
                    <div class="head" style="grid-column:1/-1;">
                        <span style="color:#6e7681;">source:</span> <span>${u.source_frame}</span>
                    </div>
                `;
                results.appendChild(card);
            }
            const sep = document.createElement('div');
            sep.style.cssText = 'border-top: 1px solid #30363d; margin: 16px 0;';
            results.appendChild(sep);
        }
        if (!suspects.length) {
            const msg = document.createElement('div');
            msg.style.cssText = 'color:#3fb950; padding:8px;';
            msg.textContent = unknowns.length
                ? 'No mislabel suspects (predicted = labeled for all known species).'
                : 'No mislabel suspects and nothing out-of-atlas — atlas is clean.';
            results.appendChild(msg);
            return;
        }
        const header = document.createElement('div');
        header.style.cssText = 'font-size: 13px; font-weight: 600; color: #f85149; margin-bottom: 8px;';
        header.textContent = `${suspects.length} crops where the closest atlas mean is NOT the labeled species. Sorted by confidence (predicted's RMSD - labeled's RMSD).`;
        results.appendChild(header);
        for (const s of suspects) {
            const card = document.createElement('div');
            card.className = 'pa-suspect-card';
            const refUrl = `/api/hud-pill-atlas/ref/${encodeURIComponent(s.ref)}`;
            const insUrl = `#/inspector?source=__test__/action_menu&filename=${encodeURIComponent(s.source_frame)}`;
            card.dataset.ref = s.ref;
            card.dataset.predicted = s.predicted_species;
            card.innerHTML = `
                <div class="col">
                    <div class="label">crop (${s.side} ${s.slot})</div>
                    <img src="${refUrl}" alt="">
                </div>
                <div class="col labeled">
                    <div class="label">labeled</div>
                    <div class="name">${s.labeled_species}</div>
                    <div class="rmsd">RMSD ${s.rmsd_labeled ?? '-'}</div>
                </div>
                <div class="col predicted">
                    <div class="label">predicted</div>
                    <div class="name">${s.predicted_species}</div>
                    <div class="rmsd">RMSD ${s.rmsd_predicted}</div>
                </div>
                <div class="head" style="grid-column:1/-1; display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                    <span style="color:#6e7681;">source:</span> <span>${s.source_frame}</span>
                    <span style="color:#6e7681;">Δ RMSD:</span> <span class="conf">${s.confidence ?? '-'}</span>
                    <span style="flex:1"></span>
                    <button class="btn btn-primary pa-accept-btn" style="font-size:11px; padding:3px 10px;">✓ Accept (relabel as ${s.predicted_species})</button>
                    <span class="pa-accept-status" style="font-size:11px; color:#8b949e;"></span>
                </div>
            `;
            results.appendChild(card);
        }
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    } finally {
        btn.disabled = false;
    }
}

document.addEventListener('change', (e) => {
    const card = e.target.closest('.pa-species-card.expanded');
    if (!card) return;
    if (e.target.classList.contains('pa-select-all')) {
        const checks = card.querySelectorAll('.pa-ref-check');
        checks.forEach(c => { if (!c.disabled) c.checked = e.target.checked; });
        paUpdateBulkUI(card);
        e.stopPropagation();
        return;
    }
    if (e.target.classList.contains('pa-ref-check')) {
        paUpdateBulkUI(card);
        e.stopPropagation();
        return;
    }
});

document.addEventListener('input', (e) => {
    if (e.target.classList && e.target.classList.contains('pa-move-target')) {
        const card = e.target.closest('.pa-species-card.expanded');
        if (card) paUpdateBulkUI(card);
    }
});

document.addEventListener('click', async (e) => {
    const moveBtn = e.target.closest('.pa-move-btn');
    if (moveBtn) {
        e.stopPropagation();
        const card = moveBtn.closest('.pa-species-card.expanded');
        if (card) await paBulkMove(card);
        return;
    }
    const acceptBtn = e.target.closest('.pa-accept-btn');
    if (acceptBtn) {
        const card = acceptBtn.closest('.pa-suspect-card');
        const ref = card.dataset.ref;
        const predicted = card.dataset.predicted;
        const status = card.querySelector('.pa-accept-status');
        acceptBtn.disabled = true; status.textContent = 'Updating...';
        try {
            const r = await fetch('/api/hud-pill-atlas/relabel', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ref, new_species: predicted})
            }).then(r => r.json());
            if (r.ok) {
                card.style.transition = 'opacity 0.2s';
                card.style.opacity = '0.4';
                status.textContent = `${r.field}[${r.slot}] = ${r.new}`;
                status.style.color = '#3fb950';
            } else {
                status.textContent = 'Error: ' + (r.error || 'unknown');
                status.style.color = '#f85149';
                acceptBtn.disabled = false;
            }
        } catch (err) {
            status.textContent = 'Error: ' + err.message;
            status.style.color = '#f85149';
            acceptBtn.disabled = false;
        }
        return;
    }
    if (e.target.id === 'pa-audit-btn') {
        paRunAudit();
        return;
    }
    if (e.target.id === 'pa-rebuild-btn') {
        const btn = e.target;
        const status = document.getElementById('pa-rebuild-status');
        if (!confirm('Re-extract HUD pill crops from all manifest-labeled BattleHUDReader frames? This rewrites data/hud_pill_atlas/.')) return;
        btn.disabled = true; status.textContent = 'Rebuilding...';
        try {
            const r = await fetch('/api/hud-pill-atlas/rebuild', {method:'POST'}).then(r => r.json());
            if (r.ok) {
                status.textContent = 'Rebuilt — reloading view...';
                pillAtlasInited = false;
                setTimeout(() => pillAtlasInit(), 500);
            } else {
                status.textContent = 'Rebuild failed: ' + (r.stderr || r.stdout || '?').slice(0, 200);
            }
        } catch (err) {
            status.textContent = 'Error: ' + err.message;
        } finally {
            btn.disabled = false;
        }
    }
});
