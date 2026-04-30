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

    // Source change -> populate thumbnail ribbon
    document.getElementById('inspector-source-select').addEventListener('change', async e => {
        const source = e.target.value;
        const ribbon = document.getElementById('inspector-ribbon');
        ribbon.innerHTML = '';
        if (!source) return;
        try {
            const data = await api(`/api/labeler/images?source=${encodeURIComponent(source)}&reader=_`);
            const images = data.images || [];
            // Also populate hidden select for nav compat
            const sel = document.getElementById('inspector-image-select');
            sel.innerHTML = images.map(i => `<option value="${i.filename}">${i.filename}</option>`).join('');
            inspectorState._ribbonSource = source;
            inspectorState._ribbonImages = images;

            images.forEach((img, idx) => {
                const thumb = document.createElement('img');
                thumb.src = `${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(img.filename)}?thumb=1`;
                thumb.title = img.filename;
                thumb.dataset.idx = idx;
                thumb.style.cssText = 'height:56px; width:auto; border-radius:3px; border:2px solid #30363d; cursor:pointer; flex-shrink:0; transition:border-color 0.15s;';
                thumb.addEventListener('click', () => {
                    // Highlight selected
                    ribbon.querySelectorAll('img').forEach(t => t.style.borderColor = '#30363d');
                    thumb.style.borderColor = '#1f6feb';
                    inspectorState._ribbonIdx = idx;
                    inspectorLoadImage(`${API}/api/labeler/frame/${encodeURIComponent(source)}/${encodeURIComponent(img.filename)}`);
                });
                ribbon.appendChild(thumb);
            });
            // Auto-load first image
            if (images.length > 0) {
                ribbon.querySelector('img').click();
            }
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

    document.getElementById('inspector-boxes-select').addEventListener('change', e => {
        inspectorState.selectedBoxReader = e.target.value;
        inspectorRender();
    });

    // Prev/next image buttons
    document.getElementById('inspector-prev-btn').addEventListener('click', () => inspectorNavImage(-1));
    document.getElementById('inspector-next-btn').addEventListener('click', () => inspectorNavImage(1));

    // Editable box coordinate inputs
    inspectorAttachBoxInputs();

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
            ['inspector-results','inspector-crop-section','inspector-solid-section','inspector-cpp-section','inspector-save-section'].forEach(id =>
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

function inspectorLoadImage(url) {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
        inspectorState.image = img;
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

    } catch (e) {
        console.error('inspectorAnalyze:', e);
    }
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
        const data = await resp.json();
        if (data.ok) {
            const st = document.getElementById('inspector-save-status');
            st.textContent = 'Saved!';
            setTimeout(() => st.textContent = '', 2000);
        }
    } catch (e) { console.error(e); }
}

function inspectorNavImage(delta) {
    const ribbon = document.getElementById('inspector-ribbon');
    const thumbs = ribbon.querySelectorAll('img');
    if (!thumbs.length) return;
    const curIdx = inspectorState._ribbonIdx || 0;
    const newIdx = curIdx + delta;
    if (newIdx >= 0 && newIdx < thumbs.length) {
        thumbs[newIdx].click();
        thumbs[newIdx].scrollIntoView({ behavior: 'smooth', inline: 'center' });
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

