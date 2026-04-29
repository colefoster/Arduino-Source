// ═══════════════════════════════════════════════════════════════
// Recognition Results
// ═══════════════════════════════════════════════════════════════

let recogInited = false;
let recogData = null;
let recogSelectedReader = null;
let recogPage = 0;
const RECOG_PAGE_SIZE = 20;
let recogSorted = [];
let recogBoxOverrides = {}; // reader -> [{name, box: [x,y,w,h]}, ...]

// Recognition readers (non-bool readers that return values)
const RECOG_READERS = [
    'SpeciesReader_Doubles', 'SpeciesReader', 'MoveNameReader',
    'TeamSelectReader', 'TeamSummaryReader', 'TeamPreviewReader',
    'OpponentHPReader_Doubles', 'OpponentHPReader',
];

async function recognitionInit() {
    if (recogInited) return;
    recogInited = true;
    await loadRecogResults();
}

async function loadRecogResults() {
    const status = document.getElementById('recog-status');
    status.textContent = 'Loading regression results...';
    try {
        recogData = await api('/api/regression/summary');
        if (!recogData.timestamp) {
            status.innerHTML = 'No regression results found. Run <code>python3 tools/retest.py</code> locally, commit and push <code>tools/regression_results.json</code>.';
            return;
        }
        status.textContent = `Last run: ${recogData.timestamp}`;
        renderRecogReaderBar();
        if (RECOG_READERS.length > 0) {
            const first = RECOG_READERS.find(r => recogData.readers[r]);
            if (first) selectRecogReader(first);
        }
    } catch (e) {
        status.textContent = 'Error loading results: ' + e.message;
    }
}

function renderRecogReaderBar() {
    const bar = document.getElementById('recog-reader-bar');
    bar.innerHTML = '';
    RECOG_READERS.forEach(name => {
        const r = recogData.readers[name];
        const btn = document.createElement('button');
        btn.className = 'btn' + (name === recogSelectedReader ? ' btn-primary' : '');
        btn.style.fontSize = '11px';
        btn.style.padding = '4px 10px';
        if (r) {
            const total = r.passed + r.failed;
            const label = r.failed > 0 ? `${r.passed}/${total}` : `${total}`;
            btn.textContent = `${name} (${label})`;
            if (r.failed > 0) btn.style.borderColor = '#f85149';
        } else {
            btn.textContent = `${name} (0)`;
            btn.style.opacity = '0.4';
        }
        btn.onclick = () => selectRecogReader(name);
        bar.appendChild(btn);
    });

    // Also show all other readers
    Object.keys(recogData.readers).forEach(name => {
        if (RECOG_READERS.includes(name)) return;
        const r = recogData.readers[name];
        const btn = document.createElement('button');
        btn.className = 'btn' + (name === recogSelectedReader ? ' btn-primary' : '');
        btn.style.fontSize = '11px';
        btn.style.padding = '4px 10px';
        const total = r.passed + r.failed;
        const label = r.failed > 0 ? `${r.passed}/${total}` : `✓ ${total}`;
        btn.textContent = `${name} (${label})`;
        if (r.failed > 0) btn.style.borderColor = '#f85149';
        btn.onclick = () => selectRecogReader(name);
        bar.appendChild(btn);
    });
}

async function selectRecogReader(name) {
    recogSelectedReader = name;
    recogPage = 0;
    renderRecogReaderBar();
    const content = document.getElementById('recog-content');
    const r = recogData.readers[name];
    if (!r) {
        content.innerHTML = '<div style="color:#8b949e; padding:20px;">No results for this reader.</div>';
        return;
    }

    content.innerHTML = '<div style="color:#8b949e;">Loading frames...</div>';

    // Load full results + reader image list + crop defs
    const [full, readerData, cropDefs] = await Promise.all([
        api('/api/regression/results'),
        api(`/api/gallery/reader/${encodeURIComponent(name)}`).catch(() => null),
        api(`/api/gallery/crop_defs/${encodeURIComponent(name)}`).catch(() => null),
    ]);

    // Cache crop defs locally
    if (cropDefs && cropDefs.crops) {
        CROP_DEFS_LOCAL[name] = cropDefs.crops;
    }
    _recogResults = full.results || {};

    const results = _recogResults;
    const images = readerData ? readerData.images || [] : [];

    // Sort: failures first, then passes
    recogSorted = images.slice().sort((a, b) => {
        const ra = results[a.filename], rb = results[b.filename];
        const fa = ra && !ra.passed ? 0 : 1;
        const fb = rb && !rb.passed ? 0 : 1;
        return fa - fb;
    });

    recogRenderPage(name, r, results);
}

function recogRenderPage(name, r, results) {
    const content = document.getElementById('recog-content');
    const totalPages = Math.ceil(recogSorted.length / RECOG_PAGE_SIZE);
    const pageItems = recogSorted.slice(recogPage * RECOG_PAGE_SIZE, (recogPage + 1) * RECOG_PAGE_SIZE);

    // Box editor panel
    const crops = recogBoxOverrides[name] || CROP_DEFS_LOCAL[name] || [];
    let boxHtml = '';
    if (crops.length > 0) {
        boxHtml = `<div style="background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px 12px; margin-bottom:12px;">
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:8px;">
                <span style="font-size:11px; color:#58a6ff; font-weight:bold;">Crop Boxes</span>
                <button class="btn" style="font-size:10px; padding:2px 8px;" onclick="recogResetBoxes('${name}')">Reset</button>
                <button class="btn btn-primary" style="font-size:10px; padding:2px 8px;" onclick="recogRefreshCrops('${name}')">Refresh Crops</button>
                <span style="font-size:10px; color:#8b949e;" id="recog-box-status"></span>
            </div>
            <div style="display:flex; gap:12px; flex-wrap:wrap;">`;
        crops.forEach((c, idx) => {
            boxHtml += `<div style="background:#0d1117; border:1px solid #21262d; border-radius:4px; padding:6px 8px;">
                <div style="font-size:10px; color:#8b949e; margin-bottom:4px;">${c.name}</div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:3px;">
                    <label style="font-size:9px; color:#484f58;">x <input type="number" step="0.001" min="0" max="1" value="${c.box[0].toFixed(4)}" style="width:62px; font-size:10px; background:#161b22; border:1px solid #30363d; color:#c9d1d9; border-radius:3px; padding:1px 4px;" data-reader="${name}" data-idx="${idx}" data-dim="0" onchange="recogBoxChanged(this)"></label>
                    <label style="font-size:9px; color:#484f58;">y <input type="number" step="0.001" min="0" max="1" value="${c.box[1].toFixed(4)}" style="width:62px; font-size:10px; background:#161b22; border:1px solid #30363d; color:#c9d1d9; border-radius:3px; padding:1px 4px;" data-reader="${name}" data-idx="${idx}" data-dim="1" onchange="recogBoxChanged(this)"></label>
                    <label style="font-size:9px; color:#484f58;">w <input type="number" step="0.001" min="0" max="1" value="${c.box[2].toFixed(4)}" style="width:62px; font-size:10px; background:#161b22; border:1px solid #30363d; color:#c9d1d9; border-radius:3px; padding:1px 4px;" data-reader="${name}" data-idx="${idx}" data-dim="2" onchange="recogBoxChanged(this)"></label>
                    <label style="font-size:9px; color:#484f58;">h <input type="number" step="0.001" min="0" max="1" value="${c.box[3].toFixed(4)}" style="width:62px; font-size:10px; background:#161b22; border:1px solid #30363d; color:#c9d1d9; border-radius:3px; padding:1px 4px;" data-reader="${name}" data-idx="${idx}" data-dim="3" onchange="recogBoxChanged(this)"></label>
                </div>
            </div>`;
        });
        boxHtml += `</div>
            <div style="margin-top:8px; font-size:10px; color:#484f58;">C++ code: <code id="recog-cpp-snippet" style="color:#c9d1d9; user-select:all;"></code></div>
        </div>`;
    }

    // Summary + pagination header
    let html = `${boxHtml}
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <div style="font-size:12px; color:#8b949e;">
            <span style="color:#3fb950; font-weight:bold;">${r.passed}</span> passed,
            <span style="color:#f85149; font-weight:bold;">${r.failed}</span> failed,
            ${r.passed + r.failed} total
        </div>
        <div style="display:flex; gap:6px; align-items:center;">
            <button class="btn" style="font-size:11px; padding:3px 8px;" onclick="recogPageNav(-1)" ${recogPage === 0 ? 'disabled style="opacity:0.3;font-size:11px;padding:3px 8px;"' : ''}>Prev</button>
            <span style="font-size:11px; color:#8b949e;">Page ${recogPage + 1}/${totalPages}</span>
            <button class="btn" style="font-size:11px; padding:3px 8px;" onclick="recogPageNav(1)" ${recogPage >= totalPages - 1 ? 'disabled style="opacity:0.3;font-size:11px;padding:3px 8px;"' : ''}>Next</button>
        </div>
    </div>`;

    // Frame cards
    pageItems.forEach(img => {
        const res = results[img.filename];
        const passed = res ? res.passed : null;
        const borderColor = passed === false ? '#f85149' : passed === true ? '#238636' : '#30363d';
        const badge = passed === true ? '<span style="color:#3fb950;font-weight:bold;">PASS</span>'
                     : passed === false ? '<span style="color:#f85149;font-weight:bold;">FAIL</span>'
                     : '<span style="color:#484f58;">—</span>';

        const gt = img.ground_truth || {};
        const expected = (gt.values || []).filter(v => v !== null).join(', ');
        const actual = res ? (res.actual || '(empty)') : '—';

        html += `<div style="background:#161b22; border:1px solid ${borderColor}; border-radius:8px; padding:10px 12px; margin-bottom:6px;">
            <div style="display:flex; gap:12px; align-items:flex-start;">
                <img src="/api/gallery/thumb/${encodeURIComponent(name)}/${encodeURIComponent(img.filename)}"
                     style="width:220px; height:auto; border-radius:4px; border:1px solid #30363d; cursor:pointer; flex-shrink:0;"
                     onclick="this.style.width=this.style.width==='220px'?'500px':'220px'"
                     onerror="this.style.display='none'">
                <div style="flex:1; min-width:0;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="color:#58a6ff; font-size:11px; font-weight:bold;">${img.filename}</span>
                        ${badge}
                    </div>
                    <div style="font-size:12px; margin-bottom:8px;">
                        <span style="color:#8b949e;">Expected:</span> <b>${expected}</b>
                        <span style="color:#8b949e; margin-left:12px;">Got:</span>
                        <b style="color:${passed === false ? '#f85149' : '#3fb950'};">${actual}</b>
                    </div>
                    <div style="display:flex; gap:6px; flex-wrap:wrap;" id="recog-crops-${img.filename.replace(/[^a-zA-Z0-9]/g, '_')}">
                    </div>
                </div>
            </div>
        </div>`;
    });

    content.innerHTML = html;

    // Update C++ snippet
    recogUpdateSnippet(name);

    // Load crops for visible page items
    recogLoadPageCrops(name, pageItems);
}

async function recogLoadPageCrops(name, pageItems) {
    const boxes = recogBoxOverrides[name] || CROP_DEFS_LOCAL[name] || null;
    for (const img of pageItems) {
        const cropId = 'recog-crops-' + img.filename.replace(/[^a-zA-Z0-9]/g, '_');
        const el = document.getElementById(cropId);
        if (!el) continue;
        try {
            let crops;
            if (boxes) {
                const resp = await fetch(`${API}/api/gallery/crops_custom/${encodeURIComponent(name)}/${encodeURIComponent(img.filename)}`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({boxes})
                });
                crops = await resp.json();
            } else {
                crops = await fetch(`${API}/api/gallery/crops/${encodeURIComponent(name)}/${encodeURIComponent(img.filename)}`).then(r => r.json());
            }
            if (!Array.isArray(crops)) continue;
            el.innerHTML = '';
            crops.forEach(crop => {
                const cell = document.createElement('div');
                cell.style.cssText = 'text-align:center; background:#0d1117; border:1px solid #21262d; border-radius:4px; padding:4px;';
                cell.innerHTML = `<img src="${crop.data}" style="max-height:60px; image-rendering:pixelated; border:1px solid #30363d; border-radius:3px; display:block; margin:0 auto 3px;">
                    <div style="font-size:9px; color:#8b949e;">${crop.name}</div>`;
                el.appendChild(cell);
            });
        } catch {}
    }
}

// Page navigation
let _recogResults = null;
async function recogPageNav(delta) {
    recogPage += delta;
    if (recogPage < 0) recogPage = 0;
    const totalPages = Math.ceil(recogSorted.length / RECOG_PAGE_SIZE);
    if (recogPage >= totalPages) recogPage = totalPages - 1;
    // Re-fetch results if needed
    if (!_recogResults) _recogResults = (await api('/api/regression/results')).results || {};
    const r = recogData.readers[recogSelectedReader];
    recogRenderPage(recogSelectedReader, r, _recogResults);
}

// Box editing
const CROP_DEFS_LOCAL = {};
function recogBoxChanged(input) {
    const reader = input.dataset.reader;
    const idx = parseInt(input.dataset.idx);
    const dim = parseInt(input.dataset.dim);
    const val = parseFloat(input.value);
    if (isNaN(val)) return;

    if (!recogBoxOverrides[reader]) {
        const orig = CROP_DEFS_LOCAL[reader] || [];
        recogBoxOverrides[reader] = orig.map(c => ({name: c.name, box: [...c.box]}));
    }
    recogBoxOverrides[reader][idx].box[dim] = val;
    recogUpdateSnippet(reader);
    document.getElementById('recog-box-status').textContent = 'Modified (click Refresh Crops to preview)';
}

function recogResetBoxes(reader) {
    delete recogBoxOverrides[reader];
    document.getElementById('recog-box-status').textContent = '';
    // Re-render
    recogPageNav(0);
}

async function recogRefreshCrops(reader) {
    document.getElementById('recog-box-status').textContent = 'Refreshing...';
    const pageItems = recogSorted.slice(recogPage * RECOG_PAGE_SIZE, (recogPage + 1) * RECOG_PAGE_SIZE);
    await recogLoadPageCrops(reader, pageItems);
    document.getElementById('recog-box-status').textContent = 'Updated';
}

function recogUpdateSnippet(reader) {
    const el = document.getElementById('recog-cpp-snippet');
    if (!el) return;
    const boxes = recogBoxOverrides[reader] || CROP_DEFS_LOCAL[reader] || [];
    const code = boxes.map(c =>
        `ImageFloatBox(${c.box[0].toFixed(4)}, ${c.box[1].toFixed(4)}, ${c.box[2].toFixed(4)}, ${c.box[3].toFixed(4)})`
    ).join(', ');
    el.textContent = code;
}

