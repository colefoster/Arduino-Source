// HUD Pill Atlas view
let pillAtlasInited = false;

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
                card.addEventListener('click', () => paToggleExpand(card, info));
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
        return;
    }
    card.classList.add('expanded');
    const refsDiv = document.createElement('div');
    refsDiv.className = 'refs';
    for (const r of (info.refs || [])) {
        const cell = document.createElement('div');
        cell.className = 'ref-cell';
        cell.innerHTML = `
            <img src="/api/hud-pill-atlas/ref/${encodeURIComponent(r.ref)}" alt="${r.ref}">
            <div class="ref-name">${r.source_frame.replace('.png','')}<br>slot ${r.slot}</div>
        `;
        refsDiv.appendChild(cell);
    }
    card.appendChild(refsDiv);
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
        status.textContent = `${suspects.length} suspect crop${suspects.length === 1 ? '' : 's'} found`;
        results.innerHTML = '';
        results.style.display = '';
        if (!suspects.length) {
            results.innerHTML = '<div style="color:#3fb950; padding:8px;">No mislabel suspects — every crop matches its labeled species best.</div>';
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

document.addEventListener('click', async (e) => {
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
