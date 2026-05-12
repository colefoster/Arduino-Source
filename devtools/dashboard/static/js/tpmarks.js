let tpmarksInited = false;

async function tpmarksInit() {
    if (tpmarksInited) return;
    tpmarksInited = true;

    const select = document.getElementById('tpm-file');
    const runBtn = document.getElementById('tpm-run');
    const status = document.getElementById('tpm-status');
    const slotsEl = document.getElementById('tpm-slots');
    const imgEl = document.getElementById('tpm-img');

    async function loadFiles() {
        const r = await fetch('/api/tp-marks/list').then(r => r.json());
        select.innerHTML = (r.files || []).map(f => `<option value="${f}">${f}</option>`).join('');
        if (r.files && r.files.length) await run();
    }

    async function run() {
        const fn = select.value;
        if (!fn) return;
        status.textContent = 'reading...';
        slotsEl.innerHTML = '';
        imgEl.src = `/test_images/team_preview_selecting/${fn}`;
        const r = await fetch(`/api/tp-marks/read?filename=${encodeURIComponent(fn)}`).then(r => r.json());
        if (r.error) { status.textContent = r.error; return; }
        slotsEl.innerHTML = r.slots.map(s => {
            const o = s.ocr || {};
            const raw = o.raw_text || o.raw || '';
            const err = o.error || '';
            return `<div class="tpm-card">
                <div style="display:flex; flex-direction:column; gap:4px; align-items:center;">
                    <div class="label">${s.name}</div>
                    ${s.crop ? `<img src="${s.crop}" title="raw crop">` : '<div style="color:#6e7681; font-size:10px;">no crop</div>'}
                    ${s.binarized ? `<img src="${s.binarized}" title="white-only binarize" style="border-color:#d29922;">` : ''}
                    ${s.yellow_paint ? `<img src="${s.yellow_paint}" title="yellow-paint (outline)" style="border-color:#3fb950;">` : ''}
                    ${s.yellow_filled ? `<img src="${s.yellow_filled}" title="yellow + flood-fill" style="border-color:#a371f7;">` : ''}
                    ${s.yellow_inner ? `<img src="${s.yellow_inner}" title="invert + eat outside -> inner" style="border-color:#f85149;">` : ''}
                </div>
                <div class="matches">
                    <div class="match"><span class="slug">C++ raw</span><span class="score">${raw || '(empty)'}</span></div>
                    <div class="match"><span class="slug" style="color:#3fb950;">yellow-paint OCR</span><span class="score">${s.yellow_paint_ocr || '(empty)'}</span></div>
                    <div class="match"><span class="slug" style="color:#a371f7;">filled OCR</span><span class="score">${s.yellow_filled_ocr || '(empty)'}</span></div>
                    <div class="match"><span class="slug" style="color:#f85149;">inner OCR</span><span class="score">${s.yellow_inner_ocr || '(empty)'}</span></div>
                    <div class="match top"><span class="slug" style="color:#3fb950;">→ lead</span><span class="score" style="font-weight:700;">${s.lead_digit || '(unmarked)'}</span></div>
                    ${err ? `<div class="match"><span class="slug" style="color:#f85149;">err</span><span class="score">${err}</span></div>` : ''}
                </div>
            </div>`;
        }).join('');
        status.textContent = `${r.slots.length} slots`;
    }

    runBtn.addEventListener('click', run);
    select.addEventListener('change', run);
    await loadFiles();
}
