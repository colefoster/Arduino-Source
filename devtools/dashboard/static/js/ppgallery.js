// PP Crops gallery: every move_select image with its 4 PP crops + BattleHUDReader reads.
let ppGalleryInited = false;

function _ppLabelStatus(img) {
    // labeled = manifest has all 4 PP values non-null/-1
    // partial = manifest has some non-null/-1 but not all
    // unlabeled = manifest_pp_current null OR all entries -1/null
    const m = img.manifest_pp_current;
    if (!Array.isArray(m)) return 'unlabeled';
    const filled = m.filter(v => v !== -1 && v != null).length;
    if (filled === 0) return 'unlabeled';
    if (filled === 4) return 'labeled';
    return 'partial';
}

function _ppRenderRow(grid, img) {
    const row = document.createElement('div');
    row.className = 'ppg-row';
    const ppCells = (img.crops || []).map((c, i) => {
        const v = (img.pp_current || [])[i];
        const present = v !== -1 && v != null;
        return `
            <div class="pp-cell ${present ? 'present' : 'absent'}">
                <div class="slot-label">slot ${i}</div>
                ${c.data ? `<img src="${c.data}" alt="pp ${i}">` : '<div style="font-size:10px;color:#f85149;">no crop</div>'}
                <div class="reading">${present ? v : '-'}</div>
            </div>
        `;
    }).join('');
    const insUrl = `#/inspector?source=__test__/move_select&filename=${encodeURIComponent(img.filename)}`;
    row.innerHTML = `
        <div class="thumb-cell">
            <img src="${img.thumb}" alt="${img.filename}">
            <div>${img.filename}</div>
            <a class="ins-link" href="${insUrl}">open in inspector →</a>
        </div>
        ${ppCells}
    `;
    grid.appendChild(row);
}

async function ppGalleryInit() {
    const grid = document.getElementById('ppg-grid');
    const status = document.getElementById('ppg-status');
    grid.innerHTML = '';
    status.textContent = 'Scanning move_select frames + reading PP via BattleHUDReader (may take a minute)...';
    try {
        const data = await api('/api/pp-gallery');
        const images = data.images || [];
        if (!images.length) {
            status.textContent = 'No move_select frames found.';
            return;
        }
        const reads = images.flatMap(img => img.pp_current || []);
        const present = reads.filter(v => v !== -1).length;
        const buckets = { unlabeled: [], partial: [], labeled: [] };
        for (const img of images) buckets[_ppLabelStatus(img)].push(img);
        status.textContent = `${images.length} frames - ${present}/${reads.length} PP slots read - unlabeled:${buckets.unlabeled.length} / partial:${buckets.partial.length} / labeled:${buckets.labeled.length}`;

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
            for (const img of list) _ppRenderRow(grid, img);
        }
        ppGalleryInited = true;
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    }
}
