// ═══════════════════════════════════════════════════════════════
// Mismatches — label-vs-reader disagreement triage
// ═══════════════════════════════════════════════════════════════
let mismatchesInited = false;
let mismatchesRows = [];

async function mismatchesInit() {
    if (mismatchesInited) return;
    mismatchesInited = true;

    //  Populate screen filter from gallery's known screens.
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
}

async function mismatchesScan() {
    const screen = document.getElementById('mismatches-screen').value;
    const reader = document.getElementById('mismatches-reader').value;
    const status = document.getElementById('mismatches-status');
    const content = document.getElementById('mismatches-content');
    const btn = document.getElementById('mismatches-scan');

    btn.disabled = true;
    btn.textContent = 'Scanning...';
    status.textContent = 'Running readers across labeled images (cached after first run)...';
    content.innerHTML = '';

    const params = new URLSearchParams();
    if (screen) params.set('screen', screen);
    if (reader) params.set('reader', reader);

    try {
        const data = await api(`/api/mismatches?${params}`);
        mismatchesRows = data.rows || [];
        status.textContent = `${mismatchesRows.length} mismatches across ${data.scanned} labeled (reader, image) pairs`;
        renderMismatchesTable();
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
    html += '<th style="text-align:left; padding:6px;">Screen / file</th>';
    html += '<th style="text-align:left; padding:6px;">Reader.field[slot]</th>';
    html += '<th style="text-align:left; padding:6px;">Expected</th>';
    html += '<th style="text-align:left; padding:6px;">Got</th>';
    html += '<th style="text-align:left; padding:6px;">Actions</th>';
    html += '</tr></thead><tbody>';

    mismatchesRows.forEach((r, idx) => {
        const slotStr = r.slot != null ? `[${r.slot}]` : '';
        const fieldKey = `${r.reader}.${r.field}${slotStr}`;
        const filePath = `${r.screen}/${r.filename}`;
        const exp = r.expected === '' ? '∅' : String(r.expected);
        const got = r.got === '' ? '∅' : String(r.got);
        const thumbUrl = `${API}/api/gallery/thumb/${encodeURIComponent(r.screen)}/${encodeURIComponent(r.filename)}`;
        const fullUrl = `${API}/api/gallery/image/${encodeURIComponent(r.screen)}/${encodeURIComponent(r.filename)}`;
        html += `<tr data-idx="${idx}" style="border-bottom:1px solid #21262d;">`;
        html += `<td style="padding:6px;"><img src="${thumbUrl}" data-full="${fullUrl}" class="mismatch-thumb" style="width:128px; height:auto; border:1px solid #30363d; border-radius:3px; cursor:zoom-in; display:block;" loading="lazy"></td>`;
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

    //  Click thumb -> full-size overlay.
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
        btn.addEventListener('click', () => {
            const r = mismatchesRows[parseInt(btn.dataset.idx)];
            //  Inspector source path is "test_images/<screen>" for screen dirs;
            //  overlays are already prefixed with "_overlays/" by the API.
            const source = r.screen.startsWith('_overlays/')
                ? `test_images/${r.screen}`
                : `test_images/${r.screen}`;
            location.hash = `#/inspector?source=${encodeURIComponent(source)}&filename=${encodeURIComponent(r.filename)}`;
        });
    });
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
            //  Mark every row matching the same screen/file/reader as resolved —
            //  the next scan will recompute, but for now they're stale.
            mismatchesRows.forEach((row, i) => {
                if (row && row.screen === r.screen && row.filename === r.filename && row.reader === r.reader) {
                    const tr = document.querySelector(`tr[data-idx="${i}"]`);
                    if (tr) {
                        tr.style.opacity = '0.4';
                        tr.querySelectorAll('button').forEach(b => b.disabled = true);
                        const lastCell = tr.lastElementChild;
                        if (lastCell) lastCell.innerHTML = '<span style="color:#3fb950; font-size:10px;">swapped — re-scan</span>';
                    }
                    mismatchesRows[i] = null;
                }
            });
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
    const row = document.querySelector(`tr[data-idx="${idx}"]`);
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
            //  Remove the row from the list and DOM.
            mismatchesRows[idx] = null;
            if (row) {
                row.style.opacity = '0.4';
                row.querySelectorAll('button').forEach(b => b.disabled = true);
                row.querySelectorAll('td').forEach(td => td.style.color = '#8b949e');
                const lastCell = row.lastElementChild;
                if (lastCell) lastCell.innerHTML = '<span style="color:#3fb950; font-size:10px;">accepted</span>';
            }
        } else {
            alert('Accept failed: ' + (resp.error || 'unknown'));
        }
    } catch (e) {
        alert('Accept failed: ' + e);
    }
}
