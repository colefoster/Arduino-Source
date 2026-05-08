let tpcursorInited = false;

async function tpcursorInit() {
    if (tpcursorInited) return;
    tpcursorInited = true;
    document.getElementById('tpc-run').addEventListener('click', tpcursorRun);
    document.getElementById('tpc-file').addEventListener('change', tpcursorRun);
    try {
        const r = await fetch('/api/tp-cursor/list');
        const d = await r.json();
        const sel = document.getElementById('tpc-file');
        sel.innerHTML = '';
        (d.files || []).forEach(f => {
            const o = document.createElement('option');
            o.value = f; o.textContent = f;
            sel.appendChild(o);
        });
        if ((d.files || []).length) tpcursorRun();
    } catch (e) {
        document.getElementById('tpc-status').textContent = 'list err: ' + e.message;
    }
}

async function tpcursorRun() {
    const fname = document.getElementById('tpc-file').value;
    if (!fname) return;
    const status = document.getElementById('tpc-status');
    status.textContent = 'reading...';
    try {
        const r = await fetch('/api/tp-cursor/read?filename=' + encodeURIComponent(fname));
        const d = await r.json();
        if (d.error) throw new Error(d.error);
        document.getElementById('tpc-img').src = d.image;

        const sel = document.getElementById('tpc-selected');
        if (d.selected_slot >= 0) {
            sel.className = 'tpc-selected has';
            sel.textContent = '▶ slot ' + d.selected_slot;
        } else {
            sel.className = 'tpc-selected none';
            sel.textContent = 'no slot above floor (' + d.floor + ')';
        }

        const root = document.getElementById('tpc-slots');
        root.innerHTML = '';
        (d.slots || []).forEach(s => {
            const card = document.createElement('div');
            const isWin = s.slot === d.selected_slot;
            const below = s.stats && s.stats.score < d.floor;
            card.className = 'tpc-card' + (isWin ? ' win' : '') + (!isWin && below ? ' below' : '');
            const st = s.stats || {};
            card.innerHTML =
                `<img src="${s.crop || ''}">` +
                `<div class="label">${s.name}<br>slot ${s.slot}${isWin ? ' ← cursor' : ''}</div>` +
                `<div class="stats">` +
                  `score=<span class="score">${st.score ?? '—'}</span>` +
                  ` &nbsp; r=${st.r ?? '—'} g=${st.g ?? '—'} b=${st.b ?? '—'}` +
                `</div>`;
            root.appendChild(card);
        });
        status.textContent = 'ok';
    } catch (e) {
        status.textContent = 'err: ' + e.message;
    }
}
