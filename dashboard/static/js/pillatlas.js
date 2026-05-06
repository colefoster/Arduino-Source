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

document.addEventListener('click', async (e) => {
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
