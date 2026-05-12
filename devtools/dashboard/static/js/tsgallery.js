// Target Select Crops gallery: target_select frames with crops + raw/parsed OCR.
let tsGalleryInited = false;

function _tsLabelStatus(img) {
    // Treat per-side effectiveness arrays + own_moves as the labeled fields.
    const fields = [
        img.manifest_own_moves,
        img.manifest_opp_effectiveness,
        img.manifest_own_effectiveness,
    ];
    let total = 0, filled = 0;
    for (const f of fields) {
        if (!Array.isArray(f)) { total += 2; continue; }
        for (let i = 0; i < 2; i++) {
            total += 1;
            if (f[i] && f[i] !== '' && f[i] !== '-') filled += 1;
        }
    }
    if (filled === 0) return 'unlabeled';
    if (filled === total) return 'labeled';
    return 'partial';
}

function _tsEffClass(v) {
    if (!v) return 'eff-empty';
    if (v === 'super-effective') return 'eff-super';
    if (v === 'not-very-effective') return 'eff-not-very';
    if (v === 'no-effect') return 'eff-no-effect';
    return 'eff-neutral';
}

function _tsRenderRow(grid, img) {
    const row = document.createElement('div');
    row.className = 'tsg-row';
    const cropByName = Object.fromEntries((img.crops || []).map(c => [c.name, c]));

    // Build cells: [own_0_move, own_1_move, opp_0, opp_1, own_0, own_1]
    const moveCell = (i) => {
        const slug = (img.own_moves || [])[i] || '';
        const raw  = (img.own_moves_raw || [])[i] || '';
        const crop = cropByName[`own_${i}_move_name`];
        return `
            <div class="cell move">
                <div class="label">own ${i} move</div>
                ${crop && crop.data ? `<img src="${crop.data}">` : ''}
                <div class="parsed">${slug || '<span style="color:#f85149;">-</span>'}</div>
                ${raw ? `<div class="raw">raw: ${_tsEsc(raw)}</div>` : ''}
            </div>
        `;
    };

    const targetCell = (side, i) => {
        const targetedArr = side === 'opp' ? (img.opp_targeted || []) : (img.own_targeted || []);
        const effArr      = side === 'opp' ? (img.opp_effectiveness || []) : (img.own_effectiveness || []);
        const effRawArr   = side === 'opp' ? (img.opp_effectiveness_raw || []) : (img.own_effectiveness_raw || []);
        const targeted = !!targetedArr[i];
        const eff = effArr[i] || '';
        const effRaw = effRawArr[i] || '';
        const tCrop = cropByName[`${side}_${i}_is_targeted`];
        const eCrop = cropByName[`${side}_${i}_effectiveness`];
        // Mismatch flag: raw text contains "not very" but classified super-effective (or vice versa)
        const lower = (effRaw || '').toLowerCase();
        let mismatch = '';
        if (lower.includes('not very') && eff === 'super-effective') mismatch = '<div class="mismatch-flag">⚠ raw says "not very" but classified super</div>';
        else if (lower.includes('no effect') && eff !== 'no-effect') mismatch = '<div class="mismatch-flag">⚠ raw says "no effect"</div>';
        return `
            <div class="cell ${targeted ? 'targeted' : 'untargeted'}">
                <div class="label">${side} ${i}</div>
                <span class="targeted-tag">${targeted ? 'TARGETED' : 'not targeted'}</span>
                ${tCrop && tCrop.data ? `<img src="${tCrop.data}" style="max-height:50px;">` : ''}
                ${eCrop && eCrop.data ? `<img src="${eCrop.data}">` : ''}
                <div class="parsed ${_tsEffClass(eff)}">${eff || '(empty)'}</div>
                ${effRaw ? `<div class="raw">raw: ${_tsEsc(effRaw)}</div>` : ''}
                ${mismatch}
            </div>
        `;
    };

    const cellsHtml = [
        moveCell(0), moveCell(1),
        targetCell('opp', 0), targetCell('opp', 1),
        targetCell('own', 0), targetCell('own', 1),
    ].join('');

    const insUrl = `#/inspector?source=__test__/target_select&filename=${encodeURIComponent(img.filename)}`;
    row.innerHTML = `
        <div class="thumb-cell">
            <img src="${img.thumb}" alt="${img.filename}">
            <div>${img.filename}</div>
            <a class="ins-link" href="${insUrl}">open in inspector →</a>
        </div>
        <div class="cells">${cellsHtml}</div>
    `;
    grid.appendChild(row);
}

function _tsEsc(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

async function tsGalleryInit() {
    const grid = document.getElementById('tsg-grid');
    const status = document.getElementById('tsg-status');
    grid.innerHTML = '';
    status.textContent = 'Scanning target_select frames + reading via TargetSelectReader...';
    try {
        const data = await api('/api/targetselect-gallery');
        const images = data.images || [];
        if (!images.length) {
            status.textContent = 'No target_select frames found.';
            return;
        }
        const buckets = { unlabeled: [], partial: [], labeled: [] };
        for (const img of images) buckets[_tsLabelStatus(img)].push(img);
        status.textContent = `${images.length} frames - unlabeled:${buckets.unlabeled.length} / partial:${buckets.partial.length} / labeled:${buckets.labeled.length}`;
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
            for (const img of list) _tsRenderRow(grid, img);
        }
        tsGalleryInited = true;
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    }
}
