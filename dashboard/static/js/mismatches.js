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
    content.innerHTML = '';
    mismatchesRows = [];
    acceptAllBtn.style.display = 'none';
    mismatchesFocusIdx = -1;

    //  Progress shell with a live bar; rows append as they stream in.
    content.innerHTML = `
        <div style="margin-bottom:10px;">
            <div style="height:6px; background:#21262d; border-radius:3px; overflow:hidden;">
                <div id="mismatches-progress-bar" style="height:100%; width:0%; background:#58a6ff; transition:width 0.15s;"></div>
            </div>
        </div>
        <table style="width:100%; border-collapse:collapse; font-size:12px;">
            <thead><tr style="border-bottom:1px solid #30363d; color:#8b949e;">
                <th style="text-align:left; padding:6px; width:140px;">Frame</th>
                <th style="text-align:left; padding:6px; width:120px;">Field crop</th>
                <th style="text-align:left; padding:6px;">Screen / file</th>
                <th style="text-align:left; padding:6px;">Reader.field[slot]</th>
                <th style="text-align:left; padding:6px;">Expected</th>
                <th style="text-align:left; padding:6px;">Got</th>
                <th style="text-align:left; padding:6px;">Actions</th>
            </tr></thead>
            <tbody id="mismatches-tbody"></tbody>
        </table>
    `;
    const tbody = document.getElementById('mismatches-tbody');
    const bar = document.getElementById('mismatches-progress-bar');

    const params = new URLSearchParams();
    if (screen) params.set('screen', screen);
    if (reader) params.set('reader', reader);

    try {
        const resp = await fetch(`${API}/api/mismatches/stream?${params}`);
        if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
        const reader_ = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        let total = 0;
        while (true) {
            const { value, done } = await reader_.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            let nl;
            while ((nl = buf.indexOf('\n')) >= 0) {
                const line = buf.slice(0, nl).trim();
                buf = buf.slice(nl + 1);
                if (!line) continue;
                let msg;
                try { msg = JSON.parse(line); } catch { continue; }
                if (msg.type === 'start') {
                    total = msg.total;
                    status.textContent = `Scanning ${total} (reader, image) pairs...`;
                } else if (msg.type === 'progress') {
                    const pct = total ? Math.round(100 * msg.done / total) : 0;
                    if (bar) bar.style.width = pct + '%';
                    status.textContent = `${msg.done}/${total} scanned · ${mismatchesRows.length} mismatches`;
                } else if (msg.type === 'row') {
                    delete msg.type;
                    const idx = mismatchesRows.length;
                    mismatchesRows.push(msg);
                    appendMismatchRow(tbody, msg, idx);
                    if (mismatchesFocusIdx < 0) focusRow(idx);
                } else if (msg.type === 'done') {
                    if (bar) bar.style.width = '100%';
                    status.textContent = `${mismatchesRows.length} mismatches across ${msg.scanned} labeled (reader, image) pairs`;
                    if (mismatchesRows.length) {
                        acceptAllBtn.style.display = '';
                        acceptAllBtn.textContent = `Accept all visible (${mismatchesRows.length})`;
                    }
                }
            }
        }
        if (!mismatchesRows.length) {
            tbody.parentElement.style.display = 'none';
            content.insertAdjacentHTML('beforeend', '<div style="color:#3fb950; font-size:12px;">No mismatches.</div>');
        }
    } catch (e) {
        status.textContent = 'Scan failed: ' + e;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Scan';
    }
}

function appendMismatchRow(tbody, r, idx) {
    const ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth'];
    const displayField = (f) => f.startsWith('own_') ? 'my_' + f.slice(4) : f;
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
    const tr = document.createElement('tr');
    tr.className = 'mismatch-row';
    tr.dataset.idx = idx;
    tr.style.borderBottom = '1px solid #21262d';
    const showSwap = r.slot != null;
    tr.innerHTML = `
        <td style="padding:6px;"><img src="${thumbUrl}" data-full="${fullUrl}" class="mismatch-thumb" style="width:128px; height:auto; border:1px solid #30363d; border-radius:3px; cursor:zoom-in; display:block;" loading="lazy"></td>
        <td style="padding:6px;">${cropCell}</td>
        <td style="padding:6px; color:#c9d1d9; word-break:break-all;">${filePath}</td>
        <td style="padding:6px; color:#8b949e;">${fieldKey}</td>
        <td style="padding:6px; color:#f85149; font-family:monospace;">${exp}</td>
        <td style="padding:6px; color:#3fb950; font-family:monospace;">${got}</td>
        <td style="padding:6px; white-space:nowrap;">
            <button class="btn mismatch-accept-btn" data-idx="${idx}" style="font-size:10px; padding:2px 8px; margin-right:4px;">Accept got</button>
            ${showSwap ? `<button class="btn mismatch-swap-btn" data-idx="${idx}" style="font-size:10px; padding:2px 8px; margin-right:4px;">Swap 0↔1</button>` : ''}
            <button class="btn mismatch-inspector-btn" data-idx="${idx}" style="font-size:10px; padding:2px 8px;">Inspector</button>
        </td>
    `;
    tbody.appendChild(tr);
    tr.addEventListener('click', e => {
        if (e.target.closest('button') || e.target.closest('img.mismatch-thumb')) return;
        focusRow(idx);
    });
    tr.querySelector('.mismatch-thumb').addEventListener('click', () => {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:9999; display:flex; align-items:center; justify-content:center; cursor:zoom-out;';
        overlay.innerHTML = `<img src="${fullUrl}" style="max-width:95vw; max-height:95vh;">`;
        overlay.addEventListener('click', () => overlay.remove());
        document.body.appendChild(overlay);
    });
    tr.querySelector('.mismatch-accept-btn').addEventListener('click', () => acceptMismatch(idx));
    const swapBtn = tr.querySelector('.mismatch-swap-btn');
    if (swapBtn) swapBtn.addEventListener('click', () => swapMismatchSlots(idx));
    tr.querySelector('.mismatch-inspector-btn').addEventListener('click', () => openInspectorFor(idx));
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
