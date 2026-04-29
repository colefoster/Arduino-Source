// ═══════════════════════════════════════════════════════════════
// Team Preview
// ═══════════════════════════════════════════════════════════════

let tpInited = false;
let tpImages = [];
let tpIndex = 0;
let tpSource = '';
let tpSpeciesList = [];
let tpLabels = {}; // filename -> {own: [6], opp: [6]}

const TP_OWN_BOXES = Array.from({length:6}, (_, i) => ({
    name: `own_${i}`,
    box: [0.0760 + (i/5)*(0.0724-0.0760), 0.1565 + (i/5)*(0.7389-0.1565), 0.0969, 0.0389]
}));
const TP_OPP_BOXES = Array.from({length:6}, (_, i) => ({
    name: `opp_sprite_${i}`,
    box: [0.8380, 0.1509 + i*((0.7407-0.1509)/5), 0.0583, 0.0917]
}));

async function teamPreviewInit() {
    if (tpInited) return;
    tpInited = true;

    // Load species completions
    try { tpSpeciesList = await api('/api/labeler/completions/species'); } catch {}

    // Load sources
    const sources = await api('/api/labeler/sources');
    const sel = document.getElementById('tp-source');
    let html = '<option value="">-- Pick source with team preview frames --</option>';
    sources.forEach(s => {
        html += `<option value="${s.path}">${s.parent}/${s.name} (${s.count})</option>`;
    });
    sel.innerHTML = html;
    sel.addEventListener('change', tpLoadSource);

    document.getElementById('tp-save-btn').addEventListener('click', tpSave);
    document.getElementById('tp-export-btn').addEventListener('click', tpExport);

    // Keyboard nav
    document.addEventListener('keydown', e => {
        if (currentView !== 'teampreview') return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
        if (e.key === 'ArrowLeft') { tpNav(-1); e.preventDefault(); }
        else if (e.key === 'ArrowRight') { tpNav(1); e.preventDefault(); }
        else if (e.key === 'Enter') { tpSave(); e.preventDefault(); }
    });
}

async function tpLoadSource() {
    const source = document.getElementById('tp-source').value;
    if (!source) return;
    tpSource = source;

    const resp = await api(`/api/labeler/images?source=${encodeURIComponent(source)}&reader=TeamPreviewReader`);
    tpImages = resp.images || resp;
    tpIndex = 0;
    document.getElementById('tp-count').textContent = `${tpImages.length} frames`;

    // Build ribbon
    const ribbon = document.getElementById('tp-ribbon');
    ribbon.innerHTML = '';
    tpImages.forEach((img, idx) => {
        const thumb = document.createElement('img');
        thumb.src = `${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(img.filename)}?thumb=1`;
        thumb.style.cssText = 'height:60px; border-radius:3px; cursor:pointer; border:2px solid transparent; flex-shrink:0;';
        thumb.dataset.idx = idx;
        thumb.onclick = () => { tpIndex = idx; tpShowFrame(); };
        ribbon.appendChild(thumb);
    });

    if (tpImages.length > 0) tpShowFrame();
}

function tpNav(delta) {
    const newIdx = tpIndex + delta;
    if (newIdx < 0 || newIdx >= tpImages.length) return;
    tpIndex = newIdx;
    tpShowFrame();
}

async function tpShowFrame() {
    const img = tpImages[tpIndex];
    if (!img) return;

    document.getElementById('tp-content').style.display = '';
    document.getElementById('tp-filename').textContent = `${img.filename} [${tpIndex+1}/${tpImages.length}]`;

    // Highlight ribbon
    document.querySelectorAll('#tp-ribbon img').forEach((el, i) => {
        el.style.borderColor = i === tpIndex ? '#58a6ff' : 'transparent';
        if (i === tpIndex) el.scrollIntoView({behavior:'smooth', block:'nearest', inline:'center'});
    });

    // Load full image
    const imgEl = document.getElementById('tp-image');
    imgEl.src = `${API}/api/labeler/frame/${encodeURIComponent(tpSource)}/${encodeURIComponent(img.filename)}`;
    imgEl.onload = () => tpDrawOverlays();

    // Load crops from labeler source
    const allBoxes = [...TP_OWN_BOXES, ...TP_OPP_BOXES];
    try {
        const cropsData = await fetch(`${API}/api/teampreview/crops`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({source: tpSource, filename: img.filename, boxes: allBoxes})
        }).then(r => r.json());

        if (Array.isArray(cropsData)) {
            tpRenderCrops(cropsData, img.filename);
        }
    } catch (e) {
        console.error('crops failed', e);
    }
}

function tpDrawOverlays() {
    const container = document.getElementById('tp-overlays');
    container.innerHTML = '';
    const imgEl = document.getElementById('tp-image');
    const w = imgEl.clientWidth, h = imgEl.clientHeight;
    if (!w || !h) return;

    const colors = {own: '#58a6ff', opp: '#d2a8ff'};
    TP_OWN_BOXES.forEach((box, i) => {
        const div = document.createElement('div');
        div.style.cssText = `position:absolute; border:1.5px solid ${colors.own}; border-radius:2px;`;
        div.style.left = (box.box[0]*w)+'px'; div.style.top = (box.box[1]*h)+'px';
        div.style.width = (box.box[2]*w)+'px'; div.style.height = (box.box[3]*h)+'px';
        container.appendChild(div);
    });
    TP_OPP_BOXES.forEach((box, i) => {
        const div = document.createElement('div');
        div.style.cssText = `position:absolute; border:1.5px solid ${colors.opp}; border-radius:2px;`;
        div.style.left = (box.box[0]*w)+'px'; div.style.top = (box.box[1]*h)+'px';
        div.style.width = (box.box[2]*w)+'px'; div.style.height = (box.box[3]*h)+'px';
        container.appendChild(div);
    });
}

function tpRenderCrops(crops, filename) {
    const ownEl = document.getElementById('tp-own-crops');
    const oppEl = document.getElementById('tp-opp-crops');
    const existing = tpLabels[filename] || {own: Array(6).fill(''), opp: Array(6).fill('')};
    tpLabels[filename] = existing;

    // Own crops (first 6)
    ownEl.innerHTML = '';
    for (let i = 0; i < 6; i++) {
        const crop = crops[i];
        const div = document.createElement('div');
        div.style.cssText = 'background:#0d1117; border:1px solid #21262d; border-radius:4px; padding:4px; text-align:center;';
        div.innerHTML = `
            ${crop ? `<img src="${crop.data}" style="max-height:28px; image-rendering:pixelated; display:block; margin:0 auto 3px; border:1px solid #30363d; border-radius:2px;">` : ''}
            <input type="text" value="${existing.own[i]}" data-side="own" data-idx="${i}"
                style="width:100%; font-size:10px; padding:2px 4px; background:#161b22; border:1px solid #30363d; color:#c9d1d9; border-radius:3px;"
                placeholder="species..." list="tp-species-list">
        `;
        ownEl.appendChild(div);
    }

    // Opp crops (last 6)
    oppEl.innerHTML = '';
    for (let i = 0; i < 6; i++) {
        const crop = crops[6 + i];
        const div = document.createElement('div');
        div.style.cssText = 'background:#0d1117; border:1px solid #21262d; border-radius:4px; padding:4px; text-align:center;';
        div.innerHTML = `
            ${crop ? `<img src="${crop.data}" style="max-height:50px; image-rendering:pixelated; display:block; margin:0 auto 3px; border:1px solid #30363d; border-radius:2px;">` : ''}
            <input type="text" value="${existing.opp[i]}" data-side="opp" data-idx="${i}"
                style="width:100%; font-size:10px; padding:2px 4px; background:#161b22; border:1px solid #30363d; color:#c9d1d9; border-radius:3px;"
                placeholder="species..." list="tp-species-list">
        `;
        oppEl.appendChild(div);
    }

    // Wire up inputs
    document.querySelectorAll('#tp-own-crops input, #tp-opp-crops input').forEach(inp => {
        inp.addEventListener('change', () => {
            const side = inp.dataset.side;
            const idx = parseInt(inp.dataset.idx);
            tpLabels[filename][side][idx] = inp.value;
        });
    });

    // Add datalist if not present
    if (!document.getElementById('tp-species-list')) {
        const dl = document.createElement('datalist');
        dl.id = 'tp-species-list';
        tpSpeciesList.forEach(s => { const o = document.createElement('option'); o.value = s; dl.appendChild(o); });
        document.body.appendChild(dl);
    }
}

async function tpSave() {
    const img = tpImages[tpIndex];
    if (!img) return;
    const filename = img.filename;

    // Read current input values
    document.querySelectorAll('#tp-own-crops input, #tp-opp-crops input').forEach(inp => {
        const side = inp.dataset.side;
        const idx = parseInt(inp.dataset.idx);
        if (!tpLabels[filename]) tpLabels[filename] = {own: Array(6).fill(''), opp: Array(6).fill('')};
        tpLabels[filename][side][idx] = inp.value;
    });

    const labels = tpLabels[filename];
    // Save as multi_text:12 - own[0-5] then opp[0-5]
    const values = [...labels.own, ...labels.opp];
    try {
        await fetch(`${API}/api/labeler/label_batch`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({
                source: tpSource,
                filename,
                labels: { TeamPreviewReader: values }
            })
        });
        document.getElementById('tp-status').textContent = `Saved labels for ${filename}`;
        // Advance
        if (tpIndex < tpImages.length - 1) { tpIndex++; tpShowFrame(); }
    } catch (e) {
        document.getElementById('tp-status').textContent = 'Save failed: ' + e.message;
    }
}

async function tpExport() {
    try {
        const result = await apiPost('/api/labeler/export', { source: tpSource, reader: 'TeamPreviewReader' });
        document.getElementById('tp-status').textContent = `Exported ${result.exported || 0} frames`;
    } catch (e) {
        document.getElementById('tp-status').textContent = 'Export failed: ' + e.message;
    }
}

