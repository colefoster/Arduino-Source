// ═══════════════════════════════════════════════════════════════
// Labeler
// ═══════════════════════════════════════════════════════════════
let labelerInited = false;
let labelerState = {
    source: null,
    sourceInfo: null,
    images: [],
    index: 0,
    frameLabels: {},    // reader -> value for current frame
};

// Completions cache
let completionsCache = { species: null, moves: null };

async function labelerInit() {
    if (labelerInited) return;
    labelerInited = true;

    try {
        const sources = await api('/api/labeler/sources');
        labelerState._sources = sources;

        // Build reader list from all known readers
        const allReaders = new Set();
        sources.forEach(s => (s.readers || []).forEach(r => allReaders.add(r)));
        Object.keys(READER_TYPES_LOCAL).forEach(r => allReaders.add(r));
        const readerSelect = document.getElementById('labeler-reader-select');
        const sorted = [...allReaders].sort();
        readerSelect.innerHTML = '<option value="">-- Select Reader --</option>' +
            sorted.map(r => `<option value="${r}">${r}</option>`).join('');

        // When reader changes, filter sources
        readerSelect.addEventListener('change', () => labelerOnReaderChange());
    } catch (e) {
        console.error('labelerInit:', e);
    }

    document.getElementById('labeler-start-btn').addEventListener('click', labelerStart);
    document.getElementById('labeler-prev-btn').addEventListener('click', () => labelerNav(-1));
    document.getElementById('labeler-next-btn').addEventListener('click', () => labelerNav(1));
    document.getElementById('labeler-skip-btn').addEventListener('click', labelerSkip);
    document.getElementById('labeler-save-btn').addEventListener('click', () => labelerSaveAll(true));
    document.getElementById('labeler-export-btn').addEventListener('click', labelerExport);
    document.getElementById('labeler-back-btn').addEventListener('click', labelerBackToSetup);
    document.getElementById('labeler-quick-true-btn').addEventListener('click', () => labelerQuickBool(true));
    document.getElementById('labeler-quick-false-btn').addEventListener('click', () => labelerQuickBool(false));
}

// Reader types (local mirror for UI logic)
const READER_TYPES_LOCAL = {
    'MoveSelectDetector': 'bool', 'ActionMenuDetector': 'bool', 'PostMatchScreenDetector': 'bool',
    'PreparingForBattleDetector': 'bool', 'TeamSelectDetector': 'bool', 'TeamPreviewDetector': 'bool',
    'MainMenuDetector': 'bool', 'MovesMoreDetector': 'bool', 'CommunicatingDetector': 'bool',
    'MoveNameReader': 'multi_text:4', 'SpeciesReader': 'text', 'SpeciesReader_Doubles': 'multi_text:2',
    'OpponentHPReader': 'int:0:100', 'OpponentHPReader_Doubles': 'int:0:100',
    'MoveSelectCursorSlot': 'int:0:3', 'BattleLogReader': 'event',
    'TeamSelectReader': 'multi_text:6', 'TeamSummaryReader': 'multi_text:6', 'TeamPreviewReader': 'multi_text:6',
};

function labelerOnReaderChange() {
    const reader = document.getElementById('labeler-reader-select').value;
    const srcSelect = document.getElementById('labeler-source-select');
    const info = document.getElementById('labeler-reader-info');

    if (!reader) {
        srcSelect.innerHTML = '<option value="">-- Select source after reader --</option>';
        info.textContent = '';
        return;
    }

    const type = READER_TYPES_LOCAL[reader] || 'unknown';
    const isBool = type === 'bool';
    info.innerHTML = `Type: <b>${type}</b>${isBool ? ' - use T/F/keyboard to label quickly' : ''}`;

    // Filter sources that have this reader, plus "all screenshots" as a universal source
    const sources = labelerState._sources || [];
    const matching = sources.filter(s => (s.readers || []).includes(reader));

    // Also show all sources (any frames might be relevant for any reader)
    const others = sources.filter(s => !(s.readers || []).includes(reader));

    let html = '<option value="">-- Select Source --</option>';
    if (matching.length) {
        html += '<optgroup label="Suggested (has this reader)">';
        html += matching.map(s => `<option value="${s.path}">${s.parent}/${s.name} (${s.count})</option>`).join('');
        html += '</optgroup>';
    }
    if (others.length) {
        html += '<optgroup label="Other sources">';
        html += others.map(s => `<option value="${s.path}">${s.parent}/${s.name} (${s.count})</option>`).join('');
        html += '</optgroup>';
    }
    srcSelect.innerHTML = html;

    // Auto-select if only one suggested source
    if (matching.length === 1) srcSelect.value = matching[0].path;
}

async function labelerStart() {
    const source = document.getElementById('labeler-source-select').value;
    if (!source) { alert('Select a source folder.'); return; }
    const selectedReader = document.getElementById('labeler-reader-select').value;
    if (!selectedReader) { alert('Select a reader first.'); return; }

    const sourceInfo = labelerState._sources.find(s => s.path === source);
    if (!sourceInfo) { alert('Source not found.'); return; }

    // Override source info to use the selected reader
    const overrideInfo = {
        ...sourceInfo,
        readers: [selectedReader],
        suggested_reader: selectedReader,
        reader_infos: {
            [selectedReader]: {
                reader: selectedReader,
                type: READER_TYPES_LOCAL[selectedReader] || 'unknown',
                is_bool: READER_TYPES_LOCAL[selectedReader] === 'bool',
                crops: CROP_DEFS_LOCAL[selectedReader] || [],
            }
        }
    };

    labelerState.source = source;
    labelerState.sourceInfo = overrideInfo;
    labelerState.selectedReader = selectedReader;
    labelerState.frameLabels = {};

    // Fetch crop defs for this reader if not cached
    if (!CROP_DEFS_LOCAL[selectedReader]) {
        try {
            const cd = await api(`/api/gallery/crop_defs/${encodeURIComponent(selectedReader)}`);
            if (cd && cd.crops) CROP_DEFS_LOCAL[selectedReader] = cd.crops;
        } catch {}
    }
    overrideInfo.reader_infos[selectedReader].crops = CROP_DEFS_LOCAL[selectedReader] || [];

    try {
        const resp = await api(`/api/labeler/images?source=${encodeURIComponent(source)}&reader=${encodeURIComponent(selectedReader)}`);
        labelerState.images = resp.images || resp;
        labelerState.index = 0;

        document.getElementById('labeler-setup').style.display = 'none';
        document.getElementById('labeler-active').style.display = '';
        document.getElementById('labeler-reader-badge').textContent = selectedReader;
        buildMultiReaderControls();
        labelerShowFrame();
    } catch (e) {
        alert('Failed to load: ' + e.message);
    }
}

function labelerBackToSetup() {
    document.getElementById('labeler-setup').style.display = '';
    document.getElementById('labeler-active').style.display = 'none';
}

function labelerNav(delta) {
    const newIdx = labelerState.index + delta;
    if (newIdx < 0 || newIdx >= labelerState.images.length) return;
    labelerState.index = newIdx;
    labelerState.frameLabels = {};
    labelerShowFrame();
}

function labelerSkip() {
    labelerNav(1);
    labelerSetStatus('Skipped');
}

async function labelerQuickBool(val) {
    const reader = labelerState.selectedReader;
    if (!reader) return;
    labelerState.frameLabels[reader] = val;
    syncBoolButtons(reader);
    await labelerSaveAll(true);
}

function labelerUpdateProgress() {
    const total = labelerState.images.length;
    document.getElementById('labeler-progress').textContent =
        `[${labelerState.index + 1}/${total}]`;
}

function labelerSetStatus(msg) {
    const el = document.getElementById('labeler-status');
    el.textContent = msg;
    setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 3000);
}

const OVERLAY_COLORS = ['#58a6ff', '#3fb950', '#f85149', '#d29922', '#d2a8ff', '#f0883e', '#79c0ff', '#56d364'];

async function labelerShowFrame() {
    const img = labelerState.images[labelerState.index];
    if (!img) return;

    labelerUpdateProgress();

    // Load image
    const imgEl = document.getElementById('labeler-image');
    imgEl.src = `${API}/api/labeler/frame/${encodeURIComponent(labelerState.source)}/${encodeURIComponent(img.filename)}`;
    imgEl.style.display = '';

    const overlayContainer = document.getElementById('labeler-overlays');
    overlayContainer.innerHTML = '';
    imgEl.onload = () => labelerDrawOverlays(imgEl, overlayContainer);

    // Load crops for the primary reader
    const primaryReader = labelerState.sourceInfo.suggested_reader || labelerState.sourceInfo.readers[0];
    loadLabelerCrops(img.filename, primaryReader);

    // Fetch existing labels for this frame
    try {
        const existing = await api(`/api/labeler/frame_labels?source=${encodeURIComponent(labelerState.source)}&filename=${encodeURIComponent(img.filename)}`);
        labelerState.frameLabels = {};
        for (const [reader, label] of Object.entries(existing)) {
            labelerState.frameLabels[reader] = label?.value !== undefined ? label.value : label;
        }
    } catch {
        labelerState.frameLabels = {};
    }
    syncAllControls();
}

function labelerDrawOverlays(imgEl, container) {
    container.innerHTML = '';
    // Collect all crop boxes from all readers
    const infos = labelerState.sourceInfo?.reader_infos || {};
    const allBoxes = [];
    for (const info of Object.values(infos)) {
        if (info.crops) allBoxes.push(...info.crops);
    }
    if (!allBoxes.length) return;

    const wrap = document.getElementById('labeler-image-wrap');
    const wrapRect = wrap.getBoundingClientRect();
    const imgRect = imgEl.getBoundingClientRect();
    const offsetX = imgRect.left - wrapRect.left;
    const offsetY = imgRect.top - wrapRect.top;
    const dispW = imgRect.width;
    const dispH = imgRect.height;

    allBoxes.forEach((box, i) => {
        const color = OVERLAY_COLORS[i % OVERLAY_COLORS.length];
        const [bx, by, bw, bh] = box.box || [box.x, box.y, box.w, box.h];
        const div = document.createElement('div');
        div.className = 'crop-overlay';
        div.style.borderColor = color;
        div.style.left = (offsetX + bx * dispW) + 'px';
        div.style.top = (offsetY + by * dispH) + 'px';
        div.style.width = (bw * dispW) + 'px';
        div.style.height = (bh * dispH) + 'px';
        div.innerHTML = `<span class="crop-tag" style="background:${color}; color:#000;">${box.name || i}</span>`;
        container.appendChild(div);
    });
}

async function loadLabelerCrops(filename, reader) {
    const el = document.getElementById('labeler-crops');
    el.innerHTML = '<div class="section-title">Crop Previews</div><div style="color:#484f58; font-size:11px;">Loading...</div>';
    try {
        const crops = await api(`/api/labeler/crops?source=${encodeURIComponent(labelerState.source)}&filename=${encodeURIComponent(filename)}&reader=${encodeURIComponent(reader)}`);
        let html = '<div class="section-title">Crop Previews</div>';
        if (Array.isArray(crops) && crops.length) {
            html += crops.map(c => `
                <div class="crop-preview">
                    <img src="${c.data || c.url || c.data_url || ''}" alt="${c.name}" style="image-rendering:pixelated;">
                    <div class="crop-name">${c.name}</div>
                </div>
            `).join('');
        } else {
            html += '<div style="color:#484f58; font-size:11px;">No crops</div>';
        }
        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = '<div class="section-title">Crop Previews</div><div style="color:#f85149; font-size:11px;">Failed</div>';
    }
}

// Build the multi-reader control panel
function buildMultiReaderControls() {
    const container = document.getElementById('labeler-multi-controls');
    const infos = labelerState.sourceInfo?.reader_infos || {};
    const readers = labelerState.sourceInfo?.readers || [];
    let html = '';

    for (const reader of readers) {
        const info = infos[reader];
        if (!info) continue;
        const type = info.type || 'unknown';
        const shortName = reader.replace('Detector', '').replace('Reader', '');

        html += `<div class="labeler-reader-section" data-reader="${reader}">`;
        html += `<div class="section-title" style="font-size:11px; margin-bottom:4px;">${shortName}</div>`;

        if (type === 'bool') {
            html += `<div style="display:flex; gap:4px;">
                <button class="btn btn-sm lbl-bool-btn" data-reader="${reader}" data-val="true"
                    style="flex:1; font-size:11px; padding:3px 6px;">T</button>
                <button class="btn btn-sm lbl-bool-btn" data-reader="${reader}" data-val="false"
                    style="flex:1; font-size:11px; padding:3px 6px;">F</button>
            </div>`;
        } else if (type === 'event') {
            const events = info.events || [];
            html += `<select class="lbl-event-sel" data-reader="${reader}" style="width:100%; font-size:11px;">
                <option value="">--</option>
                ${events.map((ev, i) => `<option value="${ev}">${i+1}. ${ev}</option>`).join('')}
            </select>`;
        } else if (type.startsWith('int:')) {
            const parts = type.split(':');
            const min = parseInt(parts[1]) || 0;
            const max = parseInt(parts[2]) || 100;
            const range = max - min;
            if (range <= 10) {
                html += '<div style="display:flex; gap:2px; flex-wrap:wrap;">';
                for (let v = min; v <= max; v++) {
                    html += `<button class="btn btn-sm lbl-int-btn" data-reader="${reader}" data-val="${v}"
                        style="min-width:24px; font-size:11px; padding:3px 4px;">${v}</button>`;
                }
                html += '</div>';
            } else {
                html += `<input type="number" class="lbl-int-input" data-reader="${reader}"
                    min="${min}" max="${max}" style="width:100%; font-size:11px;" placeholder="${min}-${max}">`;
            }
        } else if (type === 'text') {
            html += `<div class="autocomplete-wrap">
                <input type="text" class="lbl-text-input" data-reader="${reader}"
                    style="width:100%; font-size:11px;" placeholder="Type..." autocomplete="off">
                <div class="autocomplete-dropdown lbl-ac-dd" data-reader="${reader}" style="display:none;"></div>
            </div>`;
        } else if (type.startsWith('multi_text:')) {
            const n = parseInt(type.split(':')[1]) || 1;
            const cropNames = (info.crops || []).map(c => c.name);
            for (let i = 0; i < n; i++) {
                const label = cropNames[i] || `Slot ${i+1}`;
                html += `<div style="margin-bottom:4px;">
                    <div style="font-size:9px; color:#8b949e;">${label}</div>
                    <div class="autocomplete-wrap">
                        <input type="text" class="lbl-multi-input" data-reader="${reader}" data-idx="${i}"
                            style="width:100%; font-size:11px;" placeholder="Type..." autocomplete="off">
                        <div class="autocomplete-dropdown lbl-multi-ac" data-reader="${reader}" data-idx="${i}" style="display:none;"></div>
                    </div>
                </div>`;
            }
        }

        html += '</div>';
    }

    container.innerHTML = html;

    // Wire up bool buttons
    container.querySelectorAll('.lbl-bool-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const reader = btn.dataset.reader;
            const val = btn.dataset.val === 'true';
            labelerState.frameLabels[reader] = val;
            syncBoolButtons(reader);
        });
    });

    // Wire up int buttons
    container.querySelectorAll('.lbl-int-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const reader = btn.dataset.reader;
            labelerState.frameLabels[reader] = parseInt(btn.dataset.val);
            syncIntButtons(reader);
        });
    });

    // Wire up int inputs
    container.querySelectorAll('.lbl-int-input').forEach(inp => {
        inp.addEventListener('change', () => {
            labelerState.frameLabels[inp.dataset.reader] = parseInt(inp.value);
        });
    });

    // Wire up event selects
    container.querySelectorAll('.lbl-event-sel').forEach(sel => {
        sel.addEventListener('change', () => {
            if (sel.value) labelerState.frameLabels[sel.dataset.reader] = sel.value;
        });
    });

    // Wire up text autocomplete
    container.querySelectorAll('.lbl-text-input').forEach(inp => {
        const reader = inp.dataset.reader;
        const dd = container.querySelector(`.lbl-ac-dd[data-reader="${reader}"]`);
        if (dd) setupAutocompleteEl(inp, dd, 'species', val => {
            labelerState.frameLabels[reader] = val;
        });
    });

    // Wire up multi-text autocomplete
    container.querySelectorAll('.lbl-multi-input').forEach(inp => {
        const reader = inp.dataset.reader;
        const idx = inp.dataset.idx;
        const dd = container.querySelector(`.lbl-multi-ac[data-reader="${reader}"][data-idx="${idx}"]`);
        const acType = reader.includes('Move') ? 'moves' : 'species';
        if (dd) setupAutocompleteEl(inp, dd, acType, () => {
            const vals = [];
            container.querySelectorAll(`.lbl-multi-input[data-reader="${reader}"]`).forEach(el => vals.push(el.value));
            labelerState.frameLabels[reader] = vals;
        });
    });
}

function syncBoolButtons(reader) {
    const val = labelerState.frameLabels[reader];
    document.querySelectorAll(`.lbl-bool-btn[data-reader="${reader}"]`).forEach(btn => {
        const isTrue = btn.dataset.val === 'true';
        btn.style.background = (val === true && isTrue) ? '#238636' : (val === false && !isTrue) ? '#da3633' : '';
        btn.style.color = (val === isTrue && val !== undefined) ? '#fff' : '';
    });
}

function syncIntButtons(reader) {
    const val = labelerState.frameLabels[reader];
    document.querySelectorAll(`.lbl-int-btn[data-reader="${reader}"]`).forEach(btn => {
        const active = parseInt(btn.dataset.val) === val;
        btn.style.background = active ? '#58a6ff' : '';
        btn.style.color = active ? '#000' : '';
    });
}

function syncAllControls() {
    const infos = labelerState.sourceInfo?.reader_infos || {};
    for (const [reader, info] of Object.entries(infos)) {
        const type = info.type || 'unknown';
        const val = labelerState.frameLabels[reader];

        if (type === 'bool') {
            syncBoolButtons(reader);
        } else if (type === 'event') {
            const sel = document.querySelector(`.lbl-event-sel[data-reader="${reader}"]`);
            if (sel) sel.value = val || '';
        } else if (type.startsWith('int:')) {
            const parts = type.split(':');
            const range = (parseInt(parts[2]) || 100) - (parseInt(parts[1]) || 0);
            if (range <= 10) {
                syncIntButtons(reader);
            } else {
                const inp = document.querySelector(`.lbl-int-input[data-reader="${reader}"]`);
                if (inp) inp.value = val !== undefined ? val : '';
            }
        } else if (type === 'text') {
            const inp = document.querySelector(`.lbl-text-input[data-reader="${reader}"]`);
            if (inp) inp.value = val || '';
        } else if (type.startsWith('multi_text:')) {
            const vals = Array.isArray(val) ? val : [];
            document.querySelectorAll(`.lbl-multi-input[data-reader="${reader}"]`).forEach((inp, i) => {
                inp.value = vals[i] || '';
            });
        }
    }
}

async function labelerSaveAll(autoAdvance = false) {
    const img = labelerState.images[labelerState.index];
    if (!img) return;

    // Collect all set labels
    const labels = {};
    for (const [reader, val] of Object.entries(labelerState.frameLabels)) {
        if (val === undefined || val === null || val === '') continue;
        labels[reader] = val;
    }

    if (!Object.keys(labels).length) {
        labelerSetStatus('No labels set');
        return;
    }

    try {
        await fetch(`${API}/api/labeler/label_batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source: labelerState.source,
                filename: img.filename,
                labels,
            }),
        }).then(r => r.json());
        labelerSetStatus(`Saved ${Object.keys(labels).length} labels`);
        if (autoAdvance) labelerNav(1);
    } catch (e) {
        labelerSetStatus('Save failed: ' + e.message);
    }
}

async function labelerExport() {
    const reader = labelerState.selectedReader || (labelerState.sourceInfo?.readers || [])[0];
    if (!reader) { labelerSetStatus('No reader selected'); return; }
    try {
        const result = await apiPost('/api/labeler/export', { source: labelerState.source, reader });
        labelerSetStatus(`Exported ${result.exported || 0} files to test_images/${reader}/`);
    } catch (e) {
        labelerSetStatus('Export failed: ' + e.message);
    }
}

// Autocomplete helper
async function loadCompletions(type) {
    if (completionsCache[type]) return completionsCache[type];
    try {
        const data = await api(`/api/labeler/completions/${type}`);
        completionsCache[type] = Array.isArray(data) ? data : [];
        return completionsCache[type];
    } catch {
        return [];
    }
}

function setupAutocompleteEl(input, dropdown, completionType, onChange) {
    let items = [];
    let highlightIdx = 0;

    loadCompletions(completionType).then(data => { items = data; });

    function render(filtered) {
        if (!filtered.length) { dropdown.style.display = 'none'; return; }
        dropdown.style.display = '';
        dropdown.innerHTML = filtered.slice(0, 50).map((item, i) =>
            `<div class="ac-item${i === highlightIdx ? ' highlighted' : ''}" data-val="${item}">${item}</div>`
        ).join('');
        dropdown.querySelectorAll('.ac-item').forEach(el => {
            el.addEventListener('mousedown', e => {
                e.preventDefault();
                input.value = el.dataset.val;
                dropdown.style.display = 'none';
                onChange(el.dataset.val);
            });
        });
    }

    input.addEventListener('input', () => {
        const q = input.value.toLowerCase();
        if (!q) { dropdown.style.display = 'none'; return; }
        const filtered = items.filter(i => i.toLowerCase().includes(q));
        highlightIdx = 0;
        render(filtered);
        onChange(input.value);
    });

    input.addEventListener('keydown', e => {
        const visible = dropdown.style.display !== 'none';
        const acItems = dropdown.querySelectorAll('.ac-item');
        if (e.key === 'ArrowDown' && visible) {
            e.preventDefault();
            highlightIdx = Math.min(highlightIdx + 1, acItems.length - 1);
            acItems.forEach((el, i) => el.classList.toggle('highlighted', i === highlightIdx));
        } else if (e.key === 'ArrowUp' && visible) {
            e.preventDefault();
            highlightIdx = Math.max(highlightIdx - 1, 0);
            acItems.forEach((el, i) => el.classList.toggle('highlighted', i === highlightIdx));
        } else if ((e.key === 'Tab' || e.key === 'Enter') && visible && acItems.length) {
            e.preventDefault();
            const sel = acItems[highlightIdx];
            if (sel) {
                input.value = sel.dataset.val;
                dropdown.style.display = 'none';
                onChange(sel.dataset.val);
            }
        }
    });

    input.addEventListener('blur', () => {
        setTimeout(() => { dropdown.style.display = 'none'; }, 150);
    });
}

// Keep old function name for gallery compatibility
function setupAutocomplete(inputId, dropdownId, completionType, onChange) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (input && dropdown) setupAutocompleteEl(input, dropdown, completionType, onChange);
}

// Labeler keyboard shortcuts
document.addEventListener('keydown', e => {
    if (currentView !== 'labeler') return;
    if (document.getElementById('labeler-active').style.display === 'none') return;

    const tag = e.target.tagName;
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

    if (e.key === 'Escape') { labelerBackToSetup(); return; }
    if (isInput) return;

    if (e.key === 'ArrowLeft') { e.preventDefault(); labelerNav(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); labelerNav(1); }
    else if (e.key === 'Enter') { e.preventDefault(); labelerSaveAll(true); }
    else if (e.key === 's' || e.key === 'S') { e.preventDefault(); labelerSkip(); }
    else if (e.key === 't' || e.key === 'T') { e.preventDefault(); labelerQuickBool(true); }
    else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); labelerQuickBool(false); }
});

