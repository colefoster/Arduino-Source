// HP Crops gallery: action_menu + move_select frames, 4 HP crops + reads.
let hpGalleryInited = false;

function _hpFieldsExpected(screen) {
    // Both action_menu and move_select show the HUD with all 4 HP cells.
    // We treat all 4 as "expected" for labeling.
    return ['opponent_hp_pct[0]', 'opponent_hp_pct[1]', 'own_hp_current[0]', 'own_hp_current[1]'];
}

function _hpLabelStatus(img) {
    // Count how many of the expected manifest fields are filled.
    const opp = img.manifest_opp_hp_pct;
    const ownC = img.manifest_own_hp_current;
    const probes = [
        Array.isArray(opp)  && opp[0]  != null && opp[0]  !== -1,
        Array.isArray(opp)  && opp[1]  != null && opp[1]  !== -1,
        Array.isArray(ownC) && ownC[0] != null && ownC[0] !== -1,
        Array.isArray(ownC) && ownC[1] != null && ownC[1] !== -1,
    ];
    const filled = probes.filter(Boolean).length;
    if (filled === 0) return 'unlabeled';
    if (filled === 4) return 'labeled';
    return 'partial';
}

function _hpRenderRow(grid, img) {
    const row = document.createElement('div');
    row.className = 'hpg-row';
    const cellByName = Object.fromEntries((img.crops || []).map(c => [c.name, c]));
    const opp = img.opp_hp_pct || [-1, -1];
    const ownC = img.own_hp_current || [-1, -1];
    const ownM = img.own_hp_max || [-1, -1];
    const ownCR = img.own_hp_current_raw || [-1, -1];
    const ownMR = img.own_hp_max_raw || [-1, -1];
    const fmtPct = v => (v === -1 || v == null) ? '-' : `${v}%`;
    const fmtFrac = (cur, max) => (cur === -1 || cur == null) ? '-' : `${cur}/${max}`;
    const cells = [
        { name: 'opp0_hp_pct',  label: 'opp 0 (HP%)',
          reading: fmtPct(opp[0]), raw: '',
          present: opp[0] !== -1 && opp[0] != null },
        { name: 'opp1_hp_pct',  label: 'opp 1 (HP%)',
          reading: fmtPct(opp[1]), raw: '',
          present: opp[1] !== -1 && opp[1] != null },
        { name: 'own0_hp',      label: 'own 0 (cur/max)',
          reading: fmtFrac(ownC[0], ownM[0]),
          raw: (ownCR[0] !== ownC[0] || ownMR[0] !== ownM[0])
               ? `<div class="raw" title="raw OCR before digit-fixup">raw: ${ownCR[0]}/${ownMR[0]}</div>` : '',
          present: ownC[0] !== -1 && ownC[0] != null },
        { name: 'own1_hp',      label: 'own 1 (cur/max)',
          reading: fmtFrac(ownC[1], ownM[1]),
          raw: (ownCR[1] !== ownC[1] || ownMR[1] !== ownM[1])
               ? `<div class="raw" title="raw OCR before digit-fixup">raw: ${ownCR[1]}/${ownMR[1]}</div>` : '',
          present: ownC[1] !== -1 && ownC[1] != null },
    ];
    const cellHtml = cells.map(c => {
        const crop = cellByName[c.name];
        return `
            <div class="hp-cell ${c.present ? 'present' : 'absent'}">
                <div class="slot-label">${c.label}</div>
                ${crop && crop.data ? `<img src="${crop.data}" alt="${c.name}">` : '<div style="font-size:10px;color:#f85149;">no crop</div>'}
                <div class="reading">${c.reading}</div>
                ${c.raw}
            </div>
        `;
    }).join('');
    const insUrl = `#/inspector?source=__test__/${img.screen}&filename=${encodeURIComponent(img.filename)}`;
    row.innerHTML = `
        <div class="thumb-cell">
            <img src="${img.thumb}" alt="${img.filename}">
            <div><span class="scene-tag">${img.screen}</span></div>
            <div>${img.filename}</div>
            <a class="ins-link" href="${insUrl}">open in inspector →</a>
        </div>
        ${cellHtml}
    `;
    grid.appendChild(row);
}

async function hpGalleryInit() {
    const grid = document.getElementById('hpg-grid');
    const status = document.getElementById('hpg-status');
    grid.innerHTML = '';
    status.textContent = 'Scanning frames + reading HP via BattleHUDReader (may take a couple minutes)...';
    try {
        const data = await api('/api/hp-gallery');
        const images = data.images || [];
        if (!images.length) {
            status.textContent = 'No frames found.';
            return;
        }
        const totalReads = images.length * 4;
        let presentReads = 0;
        for (const img of images) {
            const opp = img.opp_hp_pct || [];
            const ownC = img.own_hp_current || [];
            for (const v of [opp[0], opp[1], ownC[0], ownC[1]]) if (v !== -1 && v != null) presentReads++;
        }
        const buckets = { unlabeled: [], partial: [], labeled: [] };
        for (const img of images) buckets[_hpLabelStatus(img)].push(img);
        status.textContent = `${images.length} frames - ${presentReads}/${totalReads} HP slots read - unlabeled:${buckets.unlabeled.length} / partial:${buckets.partial.length} / labeled:${buckets.labeled.length}`;

        const sectionOrder = [
            { key: 'unlabeled', title: 'Unlabeled', color: '#f85149' },
            { key: 'partial',   title: 'Partial',   color: '#d29922' },
            { key: 'labeled',   title: 'Labeled',   color: '#3fb950' },
        ];
        for (const sec of sectionOrder) {
            const list = buckets[sec.key];
            if (!list.length) continue;
            const header = document.createElement('div');
            header.style.cssText = `margin: 16px 0 8px 0; font-size: 13px; font-weight: 600; color: ${sec.color}; border-bottom: 1px solid ${sec.color}33; padding-bottom: 4px;`;
            header.textContent = `${sec.title} (${list.length})`;
            grid.appendChild(header);
            for (const img of list) _hpRenderRow(grid, img);
        }
        hpGalleryInited = true;
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    }
}
