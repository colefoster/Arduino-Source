// ═══════════════════════════════════════════════════════════════
// Mismatches — label-vs-reader disagreement triage
// ═══════════════════════════════════════════════════════════════
let mismatchesInited = false;
let mismatchesRows = [];
let mismatchesFocusIdx = -1;

async function mismatchesInit() {
    if (mismatchesInited) return;
    mismatchesInited = true;

    try {
        const screens = await api('/api/gallery/screens');
        const sel = document.getElementById('mismatches-screen');
        const opts = screens
            .filter(s => s.count > 0)
            .map(s => `<option value="${s.name}">${s.name} (${s.count})</option>`)
            .join('');
        sel.insertAdjacentHTML('beforeend', opts);
    } catch (e) { console.error(e); }

    document.getElementById('mismatches-scan').addEventListener('click', mismatchesScan);
    document.getElementById('mismatches-accept-all').addEventListener('click', acceptAllVisible);

    //  Keyboard navigation — only fires while the Mismatches view is active
    //  and no input/select has focus.
    document.addEventListener('keydown', e => {
        if (currentView !== 'mismatches') return;
        const tag = (e.target && e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        const live = liveRowIndices();
        if (!live.length) return;
        const cur = live.indexOf(mismatchesFocusIdx);
        if (e.key === 'j') { e.preventDefault(); focusRow(live[Math.min(live.length - 1, cur + 1)] ?? live[0]); }
        else if (e.key === 'k') { e.preventDefault(); focusRow(live[Math.max(0, cur - 1)] ?? live[0]); }
        else if (e.key === 'a' && mismatchesFocusIdx >= 0) { e.preventDefault(); acceptMismatch(mismatchesFocusIdx); }
        else if (e.key === 's' && mismatchesFocusIdx >= 0) { e.preventDefault(); swapMismatchSlots(mismatchesFocusIdx); }
        else if (e.key === 'i' && mismatchesFocusIdx >= 0) { e.preventDefault(); openInspectorFor(mismatchesFocusIdx); }
    });
}

function liveRowIndices() {
    const out = [];
    mismatchesRows.forEach((r, i) => { if (r) out.push(i); });
    return out;
}

function focusRow(idx) {
    document.querySelectorAll('tr.mismatch-row').forEach(tr => tr.classList.remove('focused'));
    const tr = document.querySelector(`tr[data-idx="${idx}"]`);
    if (tr) {
        tr.classList.add('focused');
        tr.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    mismatchesFocusIdx = idx;
}

async function mismatchesScan() {
    const screen = document.getElementById('mismatches-screen').value;
    const reader = document.getElementById('mismatches-reader').value;
    const status = document.getElementById('mismatches-status');
    const content = document.getElementById('mismatches-content');
    const btn = document.getElementById('mismatches-scan');
    const acceptAllBtn = document.getElementById('mismatches-accept-all');

    btn.disabled = true;
    btn.textContent = 'Scanning...';
    status.textContent = 'Running readers across labeled images (cached after first run)...';
    content.innerHTML = '';
    acceptAllBtn.style.display = 'none';

    const params = new URLSearchParams();
    if (screen) params.set('screen', screen);
    if (reader) params.set('reader', reader);

    try {
        const data = await api(`/api/mismatches?${params}`);
        mismatchesRows = data.rows || [];
        status.textContent = `${mismatchesRows.length} mismatches across ${data.scanned} labeled (reader, image) pairs`;
        renderMismatchesTable();
        if (mismatchesRows.length) {
            acceptAllBtn.style.display = '';
            acceptAllBtn.textContent = `Accept all visible (${mismatchesRows.length})`;
            focusRow(0);
        }
    } catch (e) {
        status.textContent = 'Scan failed: ' + e;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Scan';
    }
}

function renderMismatchesTable() {
    const content = document.getElementById('mismatches-content');
    if (!mismatchesRows.length) {
        content.innerHTML = '<div style="color:#3fb950; font-size:12px;">No mismatches.</div>';
        return;
    }

    let html = '<table style="width:100%; border-collapse:collapse; font-size:12px;">';
    html += '<thead><tr style="border-bottom:1px solid #30363d; color:#8b949e;">';
    html += '<th style="text-align:left; padding:6px; width:140px;">Frame</th>';
    html += '<th style="text-align:left; padding:6px; width:120px;">Field crop</th>';
    html += '<th style="text-align:left; padding:6px;">Screen / file</th>';
    html += '<th style="text-align:left; padding:6px;">Reader.field[slot]</th>';
    html += '<th style="text-align:left; padding:6px;">Expected</th>';
    html += '<th style="text-align:left; padding:6px;">Got</th>';
    html += '<th style="text-align:left; padding:6px;">Actions</th>';
    html += '</tr></thead><tbody>';

    const ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth'];
    const displayField = (f) => f.startsWith('own_') ? 'my_' + f.slice(4) : f;
    mismatchesRows.forEach((r, idx) => {
        const slotStr = r.slot != null ? ` (${ORDINALS[r.slot] || (r.slot + 1)})` : '';
        const fieldKey = `${r.reader}.${displayField(r.field)}${slotStr}`;
        const filePath = `${r.screen}/${r.filename}`;
        const exp = r.expected === '' ? '∅' : String(r.expected);
        const got = r.got === '' ? '∅' : String(r.got);
        const thumbUrl = `${API}/api/gallery/thumb/${encodeURIComponent(r.screen)}/${encodeURIComponent(r.filename)}`;
        const fullUrl = `${API}/api/gallery/image/${encodeURIComponent(r.screen)}/${encodeURIComponent(r.filename)}`;
        const cropCell = r.crop
            ? `<img src="${r.crop}" style="max-width:120px; max-height:80px; image-rendering:pixelated; border:1px solid #30363d; border-radius:3px; background:#0d1117;">`
            : '<span style="color:#484f58; font-size:10px;">—</span>';
        html += `<tr class="mismatch-row" data-idx="${idx}" style="border-bottom:1px solid #21262d;">`;
        html += `<td style="padding:6px;"><img src="${thumbUrl}" data-full="${fullUrl}" class="mismatch-thumb" style="width:128px; height:auto; border:1px solid #30363d; border-radius:3px; cursor:zoom-in; display:block;" loading="lazy"></td>`;
        html += `<td style="padding:6px;">${cropCell}</td>`;
        html += `<td style="padding:6px; color:#c9d1d9; word-break:break-all;">${filePath}</td>`;
        html += `<td style="padding:6px; color:#8b949e;">${fieldKey}</td>`;
        html += `<td style="padding:6px; color:#f85149; font-family:monospace;">${exp}</td>`;
        html += `<td style="padding:6px; color:#3fb950; font-family:monospace;">${got}</td>`;
        html += `<td style="padding:6px; white-space:nowrap;">`;
        html += `<button class="btn mismatch-accept-btn" data-idx="${idx}" style="font-size:10px; padding:2px 8px; margin-right:4px;">Accept got</button>`;
        const showSwap = r.slot != null;
        if (showSwap) html += `<button class="btn mismatch-swap-btn" data-idx="${idx}" style="font-size:10px; padding:2px 8px; margin-right:4px;">Swap 0↔1</button>`;
        html += `<button class="btn mismatch-inspector-btn" data-idx="${idx}" style="font-size:10px; padding:2px 8px;">Inspector</button>`;
        html += `</td></tr>`;
    });
    html += '</tbody></table>';
    content.innerHTML = html;

    content.querySelectorAll('tr.mismatch-row').forEach(tr => {
        tr.addEventListener('click', e => {
            //  Don't focus when clicking buttons / images.
            if (e.target.closest('button') || e.target.closest('img.mismatch-thumb')) return;
            focusRow(parseInt(tr.dataset.idx));
        });
    });
    content.querySelectorAll('.mismatch-thumb').forEach(img => {
        img.addEventListener('click', () => {
            const overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:9999; display:flex; align-items:center; justify-content:center; cursor:zoom-out;';
            overlay.innerHTML = `<img src="${img.dataset.full}" style="max-width:95vw; max-height:95vh;">`;
            overlay.addEventListener('click', () => overlay.remove());
            document.body.appendChild(overlay);
        });
    });
    content.querySelectorAll('.mismatch-accept-btn').forEach(btn => {
        btn.addEventListener('click', () => acceptMismatch(parseInt(btn.dataset.idx)));
    });
    content.querySelectorAll('.mismatch-swap-btn').forEach(btn => {
        btn.addEventListener('click', () => swapMismatchSlots(parseInt(btn.dataset.idx)));
    });
    content.querySelectorAll('.mismatch-inspector-btn').forEach(btn => {
        btn.addEventListener('click', () => openInspectorFor(parseInt(btn.dataset.idx)));
    });
}

function openInspectorFor(idx) {
    const r = mismatchesRows[idx];
    if (!r) return;
    const source = `__test__/${r.screen}`;
    location.hash = `#/inspector?source=${encodeURIComponent(source)}&filename=${encodeURIComponent(r.filename)}`;
}

function advanceFocusAfter(idx) {
    const live = liveRowIndices();
    if (!live.length) {
        mismatchesFocusIdx = -1;
        return;
    }
    //  Pick the next live row after `idx`, wrapping if necessary.
    const next = live.find(i => i > idx) ?? live[0];
    focusRow(next);
}

function markRowDone(idx, label) {
    const tr = document.querySelector(`tr[data-idx="${idx}"]`);
    if (!tr) return;
    tr.style.opacity = '0.4';
    tr.querySelectorAll('button').forEach(b => b.disabled = true);
    tr.querySelectorAll('td').forEach(td => td.style.color = '#8b949e');
    const lastCell = tr.lastElementChild;
    if (lastCell) lastCell.innerHTML = `<span style="color:#3fb950; font-size:10px;">${label}</span>`;
    mismatchesRows[idx] = null;
}

async function swapMismatchSlots(idx) {
    const r = mismatchesRows[idx];
    if (!r) return;
    if (!confirm(`Swap slot 0 ↔ 1 for ${r.reader} on ${r.filename}?\nAll length-2 array fields on this image will be reversed.`)) return;
    try {
        const resp = await fetch(`${API}/api/mismatches/swap-slots`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({screen: r.screen, filename: r.filename, reader: r.reader}),
        }).then(r => r.json());
        if (resp.ok) {
            //  Mark every row matching the same screen/file/reader as resolved.
            mismatchesRows.forEach((row, i) => {
                if (row && row.screen === r.screen && row.filename === r.filename && row.reader === r.reader) {
                    markRowDone(i, 'swapped — re-scan');
                }
            });
            advanceFocusAfter(idx);
        } else {
            alert('Swap failed: ' + (resp.error || 'unknown'));
        }
    } catch (e) {
        alert('Swap failed: ' + e);
    }
}

async function acceptMismatch(idx) {
    const r = mismatchesRows[idx];
    if (!r) return;
    try {
        const resp = await fetch(`${API}/api/mismatches/accept`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                screen: r.screen,
                filename: r.filename,
                reader: r.reader,
                field: r.field,
                slot: r.slot,
                value: r.got,
            }),
        }).then(r => r.json());
        if (resp.ok) {
            markRowDone(idx, 'accepted');
            advanceFocusAfter(idx);
        } else {
            alert('Accept failed: ' + (resp.error || 'unknown'));
        }
    } catch (e) {
        alert('Accept failed: ' + e);
    }
}

async function acceptAllVisible() {
    const live = liveRowIndices();
    if (!live.length) return;
    if (!confirm(`Accept "got" value on ${live.length} rows?\nThis writes each reader output back to manifest as the new ground truth.`)) return;
    const btn = document.getElementById('mismatches-accept-all');
    btn.disabled = true;
    let done = 0;
    for (const idx of live) {
        const r = mismatchesRows[idx];
        if (!r) continue;
        try {
            const resp = await fetch(`${API}/api/mismatches/accept`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    screen: r.screen, filename: r.filename, reader: r.reader,
                    field: r.field, slot: r.slot, value: r.got,
                }),
            }).then(r => r.json());
            if (resp.ok) {
                markRowDone(idx, 'accepted');
                done++;
                btn.textContent = `Accepting... ${done}/${live.length}`;
            }
        } catch (e) { console.error(e); }
    }
    btn.textContent = `Accepted ${done}`;
    btn.disabled = false;
    setTimeout(() => { btn.style.display = 'none'; }, 1500);
}
