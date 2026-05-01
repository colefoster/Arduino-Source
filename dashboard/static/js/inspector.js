// ═══════════════════════════════════════════════════════════════
// Inspector
// ═══════════════════════════════════════════════════════════════
let inspectorInited = false;
let inspectorState = {
    image: null,        // HTMLImageElement
    scale: 1,
    panX: 0,
    panY: 0,
    dragging: false,
    dragStart: null,
    selecting: false,
    selStart: null,
    selEnd: null,
    selection: null,    // {x, y, w, h} in image normalized coords
    lastAnalysis: null, // last server analysis result
    boxes: {},          // reader -> [{name, x, y, w, h}]
    selectedBoxReader: '',
    showOverlays: true,
    isPanning: false,
};

async function inspectorInit() {
    if (inspectorInited) return;
    inspectorInited = true;

    // Load sources
    try {
        const sources = await api('/api/labeler/sources');
        const sel = document.getElementById('inspector-source-select');
        sel.innerHTML = '<option value="">Select source...</option>' +
            sources.map(s => {
                // Strip a leading "test_images/" prefix from the parent label
                // so the dropdown reads "move_select" instead of "test_images/move_select".
                const parent = (s.parent || '').replace(/^test_images\/?/, '');
                const label = parent ? `${parent}/${s.name}` : s.name;
                return `<option value="${s.path}">${label} (${s.count})</option>`;
            }).join('');
    } catch {}

    // Load boxes
    try {
        const boxes = await api('/api/inspector/boxes');
        inspectorState.boxes = boxes;
        const sel = document.getElementById('inspector-boxes-select');
        sel.innerHTML = '<option value="">None</option>' +
            Object.keys(boxes).map(r => `<option value="${r}">${r}</option>`).join('');
    } catch {}

    // Source change -> populate thumbnail ribbon (paginated, 10 per page)
    document.getElementById('inspector-source-select').addEventListener('change', async e => {
        const source = e.target.value;
        const ribbon = document.getElementById('inspector-ribbon');
        ribbon.innerHTML = '';
        if (!source) return;
        try {
            const data = await api(`/api/labeler/images?source=${encodeURIComponent(source)}&reader=_`);
            const images = data.images || [];
            const sel = document.getElementById('inspector-image-select');
            sel.innerHTML = images.map(i => `<option value="${i.filename}">${i.filename}</option>`).join('');
            inspectorState._ribbonSource = source;
            inspectorState._ribbonImages = images;
            inspectorState._ribbonPage = 0;
            inspectorState._ribbonAutoLoaded = false;
            inspectorRenderRibbon();
        } catch(e) { console.error(e); }
    });

    // Keep hidden load button for compat
    document.getElementById('inspector-load-btn').addEventListener('click', () => {
        const source = document.getElementById('inspector-source-select').value;
        const filename = document.getElementById('inspector-image-select').value;
        if (source && filename) {
            inspectorLoadImage(`${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(filename)}`);
        }
    });

    document.getElementById('inspector-upload').addEventListener('change', e => {
        const file = e.target.files[0];
        if (!file) return;
        const url = URL.createObjectURL(file);
        inspectorLoadImage(url);
    });

    // Sub-select for picking which box of the chosen reader to load into x/y/w/h.
    // Built lazily next to the overlays select.
    const overlaysSel = document.getElementById('inspector-boxes-select');
    let boxIndexSel = document.getElementById('inspector-box-index');
    if (!boxIndexSel) {
        boxIndexSel = document.createElement('select');
        boxIndexSel.id = 'inspector-box-index';
        boxIndexSel.style.cssText = 'width:100%;margin-top:4px;display:none;';
        overlaysSel.parentElement.insertBefore(boxIndexSel, overlaysSel.nextSibling);
    }

    function applyBoxToInputs(box) {
        if (!box) return;
        const arr = Array.isArray(box.box) ? box.box : [box.x, box.y, box.w, box.h];
        const [x, y, w, h] = arr;
        document.getElementById('inspector-box-x').value = (+x).toFixed(4);
        document.getElementById('inspector-box-y').value = (+y).toFixed(4);
        document.getElementById('inspector-box-w').value = (+w).toFixed(4);
        document.getElementById('inspector-box-h').value = (+h).toFixed(4);
        inspectorOnBoxInput();
    }

    overlaysSel.addEventListener('change', e => {
        inspectorState.selectedBoxReader = e.target.value;
        const reader = e.target.value;
        const boxes = (reader && inspectorState.boxes[reader]) || [];

        // Rebuild box-index sub-select.
        if (boxes.length > 0) {
            boxIndexSel.innerHTML = boxes.map((b, i) =>
                `<option value="${i}">${b.name || 'box ' + i}</option>`
            ).join('');
            boxIndexSel.style.display = boxes.length > 1 ? 'block' : 'none';
            applyBoxToInputs(boxes[0]);
        } else {
            boxIndexSel.innerHTML = '';
            boxIndexSel.style.display = 'none';
        }
        inspectorRender();
    });

    boxIndexSel.addEventListener('change', e => {
        const idx = parseInt(e.target.value, 10);
        const boxes = inspectorState.boxes[inspectorState.selectedBoxReader] || [];
        if (boxes[idx]) applyBoxToInputs(boxes[idx]);
    });

    // Prev/next image buttons
    document.getElementById('inspector-prev-btn').addEventListener('click', () => inspectorNavImage(-1));
    document.getElementById('inspector-next-btn').addEventListener('click', () => inspectorNavImage(1));

    // Editable box coordinate inputs
    inspectorAttachBoxInputs();

    // Test OCR buttons
    document.getElementById('inspector-ocr-btn').addEventListener('click', inspectorTestOcr);
    document.getElementById('inspector-ocr-sweep-btn').addEventListener('click', inspectorOcrSweep);

    // Retest button (hits Mac-local dev runner directly)
    const retestBtn = document.getElementById('inspector-retest-btn');
    if (retestBtn) retestBtn.addEventListener('click', inspectorRetest);

    // Canvas setup
    const canvasWrap = document.getElementById('inspector-canvas-wrap');
    const canvas = document.getElementById('inspector-canvas');
    const ctx = canvas.getContext('2d');

    function resizeCanvas() {
        canvas.width = canvasWrap.clientWidth;
        canvas.height = canvasWrap.clientHeight;
        inspectorRender();
    }
    new ResizeObserver(resizeCanvas).observe(canvasWrap);

    // Right-click to clear selection
    canvas.addEventListener('contextmenu', e => e.preventDefault());

    // Mouse events
    canvas.addEventListener('mousedown', e => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;

        if (e.button === 2) {
            // Right-click: clear selection
            inspectorState.selection = null;
            inspectorState.selecting = false;
            inspectorState.lastAnalysis = null;
            ['inspector-box-x','inspector-box-y','inspector-box-w','inspector-box-h'].forEach(id =>
                document.getElementById(id).value = '0');
            document.getElementById('inspector-selection-info').textContent = 'Click and drag to select. Right-click to clear.';
            ['inspector-results','inspector-crop-section','inspector-solid-section','inspector-cpp-section','inspector-save-section','inspector-ocr-section'].forEach(id =>
                document.getElementById(id).style.display = 'none');
            inspectorRender();
            return;
        }

        if (e.button === 1 || (e.button === 0 && e.altKey)) {
            // Pan
            inspectorState.isPanning = true;
            inspectorState.dragStart = { x: cx, y: cy, panX: inspectorState.panX, panY: inspectorState.panY };
        } else if (e.button === 0) {
            // Selection
            inspectorState.selecting = true;
            inspectorState.selStart = { x: cx, y: cy };
            inspectorState.selEnd = { x: cx, y: cy };
            inspectorState.selection = null;
        }
    });

    canvas.addEventListener('mousemove', e => {
        const rect = canvas.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;

        if (inspectorState.isPanning && inspectorState.dragStart) {
            inspectorState.panX = inspectorState.dragStart.panX + (cx - inspectorState.dragStart.x);
            inspectorState.panY = inspectorState.dragStart.panY + (cy - inspectorState.dragStart.y);
            inspectorRender();
        } else if (inspectorState.selecting) {
            inspectorState.selEnd = { x: cx, y: cy };
            inspectorRender();
        }

        inspectorUpdatePixelReadout(cx, cy);
    });

    canvas.addEventListener('mouseleave', () => {
        document.getElementById('inspector-pixel-readout').innerHTML = '&nbsp;';
    });

    canvas.addEventListener('mouseup', e => {
        if (inspectorState.isPanning) {
            inspectorState.isPanning = false;
            inspectorState.dragStart = null;
            return;
        }
        if (inspectorState.selecting) {
            inspectorState.selecting = false;
            const rect = canvas.getBoundingClientRect();
            const cx = e.clientX - rect.left;
            const cy = e.clientY - rect.top;
            inspectorState.selEnd = { x: cx, y: cy };
            inspectorFinalizeSelection();
            inspectorRender();
        }
    });

    // Zoom
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(0.1, Math.min(20, inspectorState.scale * delta));

        // Zoom around mouse
        inspectorState.panX = mx - (mx - inspectorState.panX) * (newScale / inspectorState.scale);
        inspectorState.panY = my - (my - inspectorState.panY) * (newScale / inspectorState.scale);
        inspectorState.scale = newScale;
        document.getElementById('inspector-zoom-label').textContent = Math.round(newScale * 100) + '%';
        inspectorRender();
    }, { passive: false });

    // Prevent context menu on canvas
    canvas.addEventListener('contextmenu', e => e.preventDefault());
}

const INSPECTOR_RIBBON_PAGE_SIZE = 10;

function inspectorRenderRibbon() {
    const ribbon = document.getElementById('inspector-ribbon');
    const source = inspectorState._ribbonSource || '';
    const images = inspectorState._ribbonImages || [];
    const page = inspectorState._ribbonPage || 0;
    const pageSize = INSPECTOR_RIBBON_PAGE_SIZE;
    const totalPages = Math.max(1, Math.ceil(images.length / pageSize));
    const clampedPage = Math.min(Math.max(0, page), totalPages - 1);
    inspectorState._ribbonPage = clampedPage;

    ribbon.innerHTML = '';
    if (!images.length) return;

    const start = clampedPage * pageSize;
    const slice = images.slice(start, start + pageSize);

    const mkPagerBtn = (label, disabled, onClick) => {
        const b = document.createElement('button');
        b.textContent = label;
        b.disabled = disabled;
        b.style.cssText = 'flex-shrink:0; height:56px; min-width:32px; padding:0 8px; background:#161b22; color:#c9d1d9; border:1px solid #30363d; border-radius:3px; cursor:pointer; font-family:inherit; font-size:11px;' + (disabled ? 'opacity:0.4; cursor:not-allowed;' : '');
        b.addEventListener('click', onClick);
        return b;
    };

    ribbon.appendChild(mkPagerBtn('\u25C0', clampedPage === 0, () => {
        inspectorState._ribbonPage = clampedPage - 1;
        inspectorRenderRibbon();
    }));

    slice.forEach((img, sliceIdx) => {
        const idx = start + sliceIdx;
        const thumb = document.createElement('img');
        thumb.src = `${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(img.filename)}?thumb=1`;
        thumb.title = img.filename;
        thumb.dataset.idx = idx;
        thumb.style.cssText = 'height:56px; width:auto; border-radius:3px; border:2px solid #30363d; cursor:pointer; flex-shrink:0; transition:border-color 0.15s;';
        thumb.addEventListener('click', () => {
            ribbon.querySelectorAll('img').forEach(t => t.style.borderColor = '#30363d');
            thumb.style.borderColor = '#1f6feb';
            inspectorState._ribbonIdx = idx;
            inspectorLoadImage(`${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(img.filename)}`);
        });
        ribbon.appendChild(thumb);
    });

    const pageInfo = document.createElement('span');
    pageInfo.textContent = `${start + 1}\u2013${Math.min(start + pageSize, images.length)} of ${images.length}`;
    pageInfo.style.cssText = 'flex-shrink:0; align-self:center; color:#8b949e; font-size:11px; padding:0 6px;';
    ribbon.appendChild(pageInfo);

    ribbon.appendChild(mkPagerBtn('\u25B6', clampedPage >= totalPages - 1, () => {
        inspectorState._ribbonPage = clampedPage + 1;
        inspectorRenderRibbon();
    }));

    // Auto-load the first image of the current page on initial render only.
    if (!inspectorState._ribbonAutoLoaded) {
        inspectorState._ribbonAutoLoaded = true;
        const firstThumb = ribbon.querySelector('img');
        if (firstThumb) firstThumb.click();
    }
}

// Cached pixel data for the loaded image — populated on load so the
// per-pixel readout doesn't have to draw the image to a canvas on every
// mousemove. Cleared whenever a new image loads.
let _inspectorPixelCache = null;

function _buildPixelCache(img) {
    try {
        const c = document.createElement('canvas');
        c.width = img.naturalWidth || img.width;
        c.height = img.naturalHeight || img.height;
        c.getContext('2d').drawImage(img, 0, 0);
        const data = c.getContext('2d').getImageData(0, 0, c.width, c.height);
        return { width: c.width, height: c.height, data: data.data };
    } catch (e) {
        // Tainted canvas (CORS) — skip; readout will be coords-only.
        return null;
    }
}

function inspectorUpdatePixelReadout(canvasX, canvasY) {
    const el = document.getElementById('inspector-pixel-readout');
    if (!el) return;
    const s = inspectorState;
    if (!s.image) { el.innerHTML = '&nbsp;'; return; }
    // Convert canvas coords -> image coords using current scale/pan.
    const ix = Math.floor((canvasX - s.panX) / s.scale);
    const iy = Math.floor((canvasY - s.panY) / s.scale);
    const W = s.image.naturalWidth || s.image.width;
    const H = s.image.naturalHeight || s.image.height;
    if (ix < 0 || iy < 0 || ix >= W || iy >= H) { el.innerHTML = '&nbsp;'; return; }

    const nx = (ix / W).toFixed(4);
    const ny = (iy / H).toFixed(4);

    let rgbStr = '';
    let swatch = '';
    if (_inspectorPixelCache) {
        const idx = (iy * _inspectorPixelCache.width + ix) * 4;
        const d = _inspectorPixelCache.data;
        const r = d[idx], g = d[idx+1], b = d[idx+2];
        const sum = r + g + b;
        const ratio = sum > 0
            ? `(${(r/sum).toFixed(3)}, ${(g/sum).toFixed(3)}, ${(b/sum).toFixed(3)})`
            : '(0, 0, 0)';
        rgbStr = ` &middot; rgb(${r},${g},${b}) &middot; ratio ${ratio}`;
        swatch = `<span style="display:inline-block;width:10px;height:10px;background:rgb(${r},${g},${b});border:1px solid #30363d;vertical-align:middle;margin-right:6px;"></span>`;
    }
    el.innerHTML = `${swatch}px(${ix}, ${iy}) &middot; norm(${nx}, ${ny})${rgbStr}`;
}

function inspectorLoadImage(url) {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
        inspectorState.image = img;
        _inspectorPixelCache = _buildPixelCache(img);
        inspectorState.scale = 1;
        inspectorState.panX = 0;
        inspectorState.panY = 0;
        inspectorState.selection = null;
        inspectorState.selecting = false;

        // Fit image
        const canvas = document.getElementById('inspector-canvas');
        const fitScale = Math.min(canvas.width / img.width, canvas.height / img.height) * 0.95;
        inspectorState.scale = fitScale;
        inspectorState.panX = (canvas.width - img.width * fitScale) / 2;
        inspectorState.panY = (canvas.height - img.height * fitScale) / 2;

        document.getElementById('inspector-results').style.display = 'none';
        document.getElementById('inspector-selection-info').textContent = 'Click and drag on the image to select a region.';
        inspectorRender();
    };
    img.src = url;
}

function inspectorRender() {
    const canvas = document.getElementById('inspector-canvas');
    const ctx = canvas.getContext('2d');
    const s = inspectorState;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!s.image) {
        ctx.fillStyle = '#484f58';
        ctx.font = '14px SF Mono, Fira Code, Consolas, monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Load or upload an image to begin', canvas.width / 2, canvas.height / 2);
        return;
    }

    ctx.save();
    ctx.translate(s.panX, s.panY);
    ctx.scale(s.scale, s.scale);

    // Draw image
    ctx.drawImage(s.image, 0, 0);

    // Draw detector overlays
    if (s.showOverlays && s.selectedBoxReader && s.boxes[s.selectedBoxReader]) {
        const readerBoxes = s.boxes[s.selectedBoxReader];
        readerBoxes.forEach((box, i) => {
            // Server returns { name, box: [x, y, w, h] }. Tolerate both shapes.
            const arr = Array.isArray(box.box) ? box.box : [box.x, box.y, box.w, box.h];
            const [nx, ny, nw, nh] = arr;
            const color = OVERLAY_COLORS[i % OVERLAY_COLORS.length];
            const bx = nx * s.image.width;
            const by = ny * s.image.height;
            const bw = nw * s.image.width;
            const bh = nh * s.image.height;

            ctx.strokeStyle = color;
            ctx.lineWidth = 2 / s.scale;
            ctx.strokeRect(bx, by, bw, bh);

            ctx.fillStyle = color;
            ctx.font = `${Math.max(10, 12 / s.scale)}px SF Mono, Fira Code, Consolas, monospace`;
            ctx.fillText(box.name || `box${i}`, bx, by - 3 / s.scale);
        });
    }

    // Draw current selection in image space
    if (s.selection) {
        const sx = s.selection.x * s.image.width;
        const sy = s.selection.y * s.image.height;
        const sw = s.selection.w * s.image.width;
        const sh = s.selection.h * s.image.height;
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 2 / s.scale;
        ctx.setLineDash([6 / s.scale, 4 / s.scale]);
        ctx.strokeRect(sx, sy, sw, sh);
        ctx.setLineDash([]);
    }

    ctx.restore();

    // Draw selection rectangle while dragging (in canvas space)
    if (s.selecting && s.selStart && s.selEnd) {
        const x = Math.min(s.selStart.x, s.selEnd.x);
        const y = Math.min(s.selStart.y, s.selEnd.y);
        const w = Math.abs(s.selEnd.x - s.selStart.x);
        const h = Math.abs(s.selEnd.y - s.selStart.y);
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]);
        ctx.strokeRect(x, y, w, h);
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(88, 166, 255, 0.1)';
        ctx.fillRect(x, y, w, h);
    }
}

function inspectorFinalizeSelection() {
    const s = inspectorState;
    if (!s.image || !s.selStart || !s.selEnd) return;

    // Convert canvas coords to image coords
    const x1 = (Math.min(s.selStart.x, s.selEnd.x) - s.panX) / s.scale;
    const y1 = (Math.min(s.selStart.y, s.selEnd.y) - s.panY) / s.scale;
    const x2 = (Math.max(s.selStart.x, s.selEnd.x) - s.panX) / s.scale;
    const y2 = (Math.max(s.selStart.y, s.selEnd.y) - s.panY) / s.scale;

    // Clamp to image
    const ix = Math.max(0, x1) / s.image.width;
    const iy = Math.max(0, y1) / s.image.height;
    const iw = Math.min(x2, s.image.width) / s.image.width - ix;
    const ih = Math.min(y2, s.image.height) / s.image.height - iy;

    if (iw < 0.001 || ih < 0.001) return;

    s.selection = { x: ix, y: iy, w: iw, h: ih };
    inspectorUpdateBoxInputs();
    inspectorAnalyze(s.selection);
}

function inspectorUpdateBoxInputs() {
    const s = inspectorState.selection;
    if (!s) return;
    document.getElementById('inspector-box-x').value = s.x.toFixed(4);
    document.getElementById('inspector-box-y').value = s.y.toFixed(4);
    document.getElementById('inspector-box-w').value = s.w.toFixed(4);
    document.getElementById('inspector-box-h').value = s.h.toFixed(4);
}

function inspectorOnBoxInput() {
    const x = parseFloat(document.getElementById('inspector-box-x').value) || 0;
    const y = parseFloat(document.getElementById('inspector-box-y').value) || 0;
    const w = parseFloat(document.getElementById('inspector-box-w').value) || 0;
    const h = parseFloat(document.getElementById('inspector-box-h').value) || 0;
    if (w > 0.001 && h > 0.001) {
        inspectorState.selection = { x, y, w, h };
        inspectorRender();
        // Show Test OCR as soon as there's a valid selection — the button
        // itself handles "no image loaded" with an error message.
        document.getElementById('inspector-ocr-section').style.display = '';
        document.getElementById('inspector-ocr-result').style.display = 'none';
        inspectorAnalyze(inspectorState.selection);
    }
}

// Debounced box input handler
let _inspectorBoxInputTimer = null;
document.querySelectorAll('#inspector-box-x, #inspector-box-y, #inspector-box-w, #inspector-box-h').forEach(el => {
    // Wait for DOM - attach in inspectorInit instead
});

function inspectorAttachBoxInputs() {
    ['inspector-box-x','inspector-box-y','inspector-box-w','inspector-box-h'].forEach(id => {
        document.getElementById(id).addEventListener('input', () => {
            clearTimeout(_inspectorBoxInputTimer);
            _inspectorBoxInputTimer = setTimeout(inspectorOnBoxInput, 300);
        });
    });
}

async function inspectorAnalyze(box) {
    if (!inspectorState.image) return;
    try {
        const source = document.getElementById('inspector-source-select').value;
        const filename = document.getElementById('inspector-image-select').value;

        const result = await apiPost('/api/inspector/analyze', {
            source: source || '',
            filename: filename || '',
            x: box.x.toString(),
            y: box.y.toString(),
            w: box.w.toString(),
            h: box.h.toString(),
        });

        if (result.error) { console.error(result.error); return; }
        inspectorState.lastAnalysis = result;

        // Update selection info
        const px = result.pixels;
        document.getElementById('inspector-selection-info').innerHTML =
            `<span style="color:#c9d1d9;">${px.w}×${px.h}px</span> · ${px.count} pixels`;

        // Crop previews
        const cropSection = document.getElementById('inspector-crop-section');
        cropSection.style.display = '';
        document.getElementById('inspector-crop-img').src = 'data:image/png;base64,' + result.crop_b64;
        document.getElementById('inspector-bw-img').src = 'data:image/png;base64,' + result.bw_b64;

        // Color stats
        const resEl = document.getElementById('inspector-results');
        resEl.style.display = '';
        const body = document.getElementById('inspector-results-body');
        const [ar, ag, ab] = result.avg_rgb;
        const [sr, sg, sb] = result.stddev_rgb;
        const [rr, rg, rb] = result.color_ratio;
        body.innerHTML = `
            <div class="result-row">
                <span class="rl">Avg RGB</span>
                <span class="rv"><span class="color-swatch" style="background:rgb(${Math.round(ar)},${Math.round(ag)},${Math.round(ab)})"></span>(${ar}, ${ag}, ${ab})</span>
            </div>
            <div class="result-row">
                <span class="rl">Stddev</span>
                <span class="rv">(${sr}, ${sg}, ${sb})</span>
            </div>
            <div class="result-row">
                <span class="rl">Stddev sum</span>
                <span class="rv">${result.stddev_sum}</span>
            </div>
            <div class="result-row">
                <span class="rl">Color ratio</span>
                <span class="rv">(${rr}, ${rg}, ${rb})</span>
            </div>
            <div class="result-row">
                <span class="rl">Brightness</span>
                <span class="rv">${result.brightness}</span>
            </div>
        `;

        // is_solid tests
        const solidSection = document.getElementById('inspector-solid-section');
        solidSection.style.display = '';
        const solidBody = document.getElementById('inspector-solid-body');
        solidBody.innerHTML = result.solid_tests.map(t => `
            <div class="result-row">
                <span class="rl" style="font-size:11px;">dist=${t.max_dist}, sdsum=${t.max_stddev}</span>
                <span class="rv" style="color:${t.passes ? '#3fb950' : '#f85149'}">${t.passes ? 'PASS' : 'FAIL'}</span>
            </div>
        `).join('');

        // C++ code
        const cppSection = document.getElementById('inspector-cpp-section');
        cppSection.style.display = '';
        document.getElementById('inspector-cpp-body').textContent =
            result.cpp_box + '\n' + result.cpp_color;

        // Show save section
        document.getElementById('inspector-save-section').style.display = '';

        // Show OCR section (button-driven, doesn't auto-run).
        document.getElementById('inspector-ocr-section').style.display = '';
        document.getElementById('inspector-ocr-result').style.display = 'none';

    } catch (e) {
        console.error('inspectorAnalyze:', e);
    }
}

async function inspectorTestOcr() {
    const sel = inspectorState.selection;
    const img = inspectorState.image;
    const status = document.getElementById('inspector-ocr-status');
    const resultEl = document.getElementById('inspector-ocr-result');
    const btn = document.getElementById('inspector-ocr-btn');
    if (!sel || !img) { status.textContent = 'No selection'; return; }

    btn.disabled = true; status.textContent = 'Running...'; resultEl.style.display = 'none';

    // Extract image to base64 from a temporary canvas (works for any source).
    let imageBase64;
    try {
        const tmp = document.createElement('canvas');
        tmp.width = img.width; tmp.height = img.height;
        tmp.getContext('2d').drawImage(img, 0, 0);
        imageBase64 = tmp.toDataURL('image/png').split(',')[1];
    } catch (e) {
        status.textContent = 'Canvas tainted (CORS) — reload image';
        btn.disabled = false;
        return;
    }

    try {
        const resp = await fetch(`${API}/api/inspector/ocr-crop`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                image_base64: imageBase64,
                x: sel.x, y: sel.y, w: sel.w, h: sel.h,
            }),
        }).then(r => r.json());

        if (!resp.ok) {
            status.textContent = resp.error || 'OCR error';
        } else {
            status.textContent = '';
            const r = resp.result || {};
            const cur = r.current, max = r.max;
            const parsed = (cur != null && cur >= 0)
                ? (max >= 0 ? `${cur}/${max}` : `${cur}`)
                : '<failed to parse>';
            resultEl.innerHTML =
                `<div><span style="color:#8b949e;">raw:</span> <code>${(r.raw || '').replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]))}</code></div>` +
                `<div style="margin-top:4px;"><span style="color:#8b949e;">parsed:</span> <code>${parsed}</code></div>`;
            resultEl.style.display = '';
        }
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    }
    btn.disabled = false;
}

async function inspectorOcrSweep() {
    const sel = inspectorState.selection;
    const source = inspectorState._ribbonSource;
    const images = inspectorState._ribbonImages || [];
    const status = document.getElementById('inspector-ocr-status');
    const sweepEl = document.getElementById('inspector-ocr-sweep');
    const btn = document.getElementById('inspector-ocr-sweep-btn');

    if (!sel) { status.textContent = 'No selection — draw a box first'; return; }
    if (!source || !images.length) { status.textContent = 'No source loaded'; return; }

    btn.disabled = true;
    sweepEl.style.display = '';
    sweepEl.innerHTML = '<div style="color:#8b949e;font-size:11px;padding:6px;">Running OCR on ' + images.length + ' images...</div>';

    // Pool with limited concurrency to avoid hammering ColePC.
    const CONCURRENCY = 6;
    const results = new Array(images.length);
    let completed = 0;

    async function runOne(i) {
        const fn = images[i].filename;
        try {
            const resp = await fetch(`${API}/api/inspector/ocr-crop`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    source, filename: fn,
                    x: sel.x, y: sel.y, w: sel.w, h: sel.h,
                }),
            }).then(r => r.json());
            results[i] = resp.ok ? resp.result : { raw: '', error: resp.error || 'failed' };
        } catch (e) {
            results[i] = { raw: '', error: e.message };
        }
        completed++;
        status.textContent = `${completed}/${images.length}`;
    }

    // Simple worker pool.
    let next = 0;
    async function worker() {
        while (next < images.length) {
            const i = next++;
            await runOne(i);
        }
    }
    await Promise.all(Array.from({length: CONCURRENCY}, worker));

    // Aggregate counts.
    const tally = {};
    for (const r of results) {
        const key = (r && (r.current >= 0 ? `${r.current}` : (r.raw || '<empty>'))) || '<error>';
        tally[key] = (tally[key] || 0) + 1;
    }
    const tallyEntries = Object.entries(tally).sort((a, b) => b[1] - a[1]);

    // Render table.
    const escape = s => String(s).replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]));
    let html = '<div style="font-size:11px;color:#8b949e;margin-bottom:6px;">Tally: '
        + tallyEntries.map(([v, n]) => `<code>${escape(v)}</code>×${n}`).join(' &middot; ')
        + '</div>';
    html += '<table style="width:100%;font-size:11px;border-collapse:collapse;">';
    html += '<thead><tr style="color:#8b949e;border-bottom:1px solid #30363d;">'
        + '<th style="text-align:left;padding:3px 4px;">image</th>'
        + '<th style="text-align:left;padding:3px 4px;">raw</th>'
        + '<th style="text-align:left;padding:3px 4px;">parsed</th>'
        + '</tr></thead><tbody>';
    images.forEach((img, i) => {
        const r = results[i] || {};
        const raw = r.raw != null ? r.raw : '';
        const parsed = (r.current != null && r.current >= 0)
            ? (r.max >= 0 ? `${r.current}/${r.max}` : `${r.current}`)
            : '';
        const isErr = r.error;
        html += `<tr data-fname="${img.filename}" style="cursor:pointer;border-bottom:1px solid #21262d;${isErr?'color:#f85149;':''}">`
            + `<td style="padding:3px 4px;color:#58a6ff;">${img.filename.length > 30 ? img.filename.slice(0,30) + '…' : img.filename}</td>`
            + `<td style="padding:3px 4px;"><code>${escape(raw)}</code></td>`
            + `<td style="padding:3px 4px;"><code>${escape(parsed)}</code></td>`
            + `</tr>`;
    });
    html += '</tbody></table>';
    sweepEl.innerHTML = html;

    // Click row to load that image (so user can compare visually + tweak).
    sweepEl.querySelectorAll('tr[data-fname]').forEach(tr => {
        tr.addEventListener('click', () => {
            const fn = tr.dataset.fname;
            inspectorLoadImage(`${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(fn)}`);
        });
    });

    status.textContent = `Done. ${completed}/${images.length}`;
    btn.disabled = false;
}

async function inspectorRetest() {
    const btn = document.getElementById('inspector-retest-btn');
    const status = document.getElementById('inspector-retest-status');
    const result = document.getElementById('inspector-retest-result');
    btn.disabled = true; status.textContent = 'Building + running regression...'; result.style.display = 'none';

    let resp;
    try {
        const r = await fetch('http://localhost:9876/retest', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: '{}',
        });
        resp = await r.json();
    } catch (e) {
        status.innerHTML = '<span style="color:#f85149;">runner not reachable — start: <code>python3 tools/mac_dev_runner.py</code></span>';
        btn.disabled = false;
        return;
    }

    if (!resp.ok) {
        status.innerHTML = `<span style="color:#f85149;">${resp.stage} failed</span>`;
        result.style.display = '';
        result.innerHTML = `<pre style="background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:8px;font-size:10px;color:#f85149;white-space:pre-wrap;max-height:400px;overflow-y:auto;">${(resp.log || '').replace(/[<&]/g, c => ({'<':'&lt;','&':'&amp;'}[c]))}</pre>`;
        btn.disabled = false;
        return;
    }

    const r = resp.result || {};
    const overall = r.overall;
    let html = '';
    if (overall) {
        const pct = (100 * overall.passed / overall.total).toFixed(1);
        html += `<div style="margin-bottom:6px;font-size:12px;"><strong>Overall:</strong> ${overall.passed}/${overall.total} (${pct}%)</div>`;
    }
    html += '<table style="width:100%;font-size:11px;border-collapse:collapse;margin-bottom:8px;">';
    html += '<thead><tr style="color:#8b949e;border-bottom:1px solid #30363d;">'
        + '<th style="text-align:left;padding:3px 4px;">detector</th>'
        + '<th style="text-align:right;padding:3px 4px;">pass/total</th>'
        + '<th style="text-align:right;padding:3px 4px;">%</th>'
        + '</tr></thead><tbody>';
    for (const d of (r.detectors || [])) {
        const color = d.pct >= 99 ? '#3fb950' : d.pct >= 90 ? '#d29922' : '#f85149';
        html += `<tr style="border-bottom:1px solid #21262d;">`
            + `<td style="padding:3px 4px;">${d.name}</td>`
            + `<td style="padding:3px 4px;text-align:right;">${d.passed}/${d.total}</td>`
            + `<td style="padding:3px 4px;text-align:right;color:${color};">${d.pct.toFixed(1)}%</td>`
            + `</tr>`;
    }
    html += '</tbody></table>';

    if ((r.failures || []).length) {
        html += '<details><summary style="cursor:pointer;color:#8b949e;font-size:11px;">'
            + `Failures (${r.failures.length})</summary>`;
        html += '<div style="font-size:10px;font-family:SF Mono,monospace;background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:6px;max-height:300px;overflow-y:auto;margin-top:4px;">';
        for (const f of r.failures) {
            html += `<div style="color:#f85149;">FAIL ${f.detector} <span style="color:#8b949e;">←</span> ${f.image}</div>`;
        }
        html += '</div></details>';
    }

    result.style.display = '';
    result.innerHTML = html;
    status.innerHTML = '<span style="color:#3fb950;">Done</span>';
    btn.disabled = false;
}

async function inspectorSaveBox() {
    const a = inspectorState.lastAnalysis;
    if (!a) return;
    const name = document.getElementById('inspector-save-name').value.trim();
    if (!name) { alert('Enter a box name'); return; }
    try {
        const resp = await fetch(`${API}/api/inspector/save-box`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name,
                scene: document.getElementById('inspector-save-scene').value.trim(),
                description: document.getElementById('inspector-save-desc').value.trim(),
                screenshot: document.getElementById('inspector-source-select').value + '/' +
                            document.getElementById('inspector-image-select').value,
                box: a.box,
                avg_rgb: a.avg_rgb,
                stddev_sum: a.stddev_sum,
                color_ratio: a.color_ratio,
            }),
        });
        const st = document.getElementById('inspector-save-status');
        if (!resp.ok) {
            const text = await resp.text();
            st.style.color = '#f85149';
            st.textContent = `${resp.status} ${resp.statusText} — ${text.slice(0, 80)}`;
            console.error('save-box failed:', resp.status, text);
            return;
        }
        const data = await resp.json();
        if (data.ok) {
            st.style.color = '#3fb950';
            st.textContent = 'Saved!';
            setTimeout(() => { st.textContent = ''; st.style.color = ''; }, 2000);
        } else {
            st.style.color = '#f85149';
            st.textContent = data.error || 'Save failed';
        }
    } catch (e) {
        const st = document.getElementById('inspector-save-status');
        st.style.color = '#f85149';
        st.textContent = 'Network error: ' + e.message;
        console.error(e);
    }
}

function inspectorNavImage(delta) {
    // Walk the global image list, hopping pages if needed.
    const images = inspectorState._ribbonImages || [];
    if (!images.length) return;
    const source = inspectorState._ribbonSource || '';
    const curIdx = inspectorState._ribbonIdx ?? 0;
    const newIdx = Math.min(images.length - 1, Math.max(0, curIdx + delta));
    if (newIdx === curIdx) return;

    const targetPage = Math.floor(newIdx / INSPECTOR_RIBBON_PAGE_SIZE);
    if (targetPage !== inspectorState._ribbonPage) {
        inspectorState._ribbonPage = targetPage;
        inspectorState._ribbonAutoLoaded = true;  // suppress auto-load; we click manually below
        inspectorRenderRibbon();
    }
    inspectorState._ribbonIdx = newIdx;

    const thumbs = document.getElementById('inspector-ribbon').querySelectorAll('img');
    const sliceOffset = newIdx % INSPECTOR_RIBBON_PAGE_SIZE;
    const thumb = thumbs[sliceOffset];
    if (thumb) {
        thumbs.forEach(t => t.style.borderColor = '#30363d');
        thumb.style.borderColor = '#1f6feb';
        thumb.scrollIntoView({ behavior: 'smooth', inline: 'center' });
        const fname = images[newIdx].filename;
        inspectorLoadImage(`${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(fname)}`);
    }
}

// Inspector keyboard shortcuts
document.addEventListener('keydown', e => {
    if (currentView !== 'inspector') return;
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    if (e.key === 'a' || e.key === 'A') {
        inspectorState.showOverlays = !inspectorState.showOverlays;
        inspectorRender();
    } else if (e.key === 'r' || e.key === 'R') {
        if (inspectorState.image) {
            const canvas = document.getElementById('inspector-canvas');
            const fitScale = Math.min(canvas.width / inspectorState.image.width, canvas.height / inspectorState.image.height) * 0.95;
            inspectorState.scale = fitScale;
            inspectorState.panX = (canvas.width - inspectorState.image.width * fitScale) / 2;
            inspectorState.panY = (canvas.height - inspectorState.image.height * fitScale) / 2;
            inspectorRender();
        }
    } else if (e.key === 'ArrowLeft') {
        inspectorNavImage(-1);
    } else if (e.key === 'ArrowRight') {
        inspectorNavImage(1);
    }
});

