// ═══════════════════════════════════════════════════════════════
// Gallery
// ═══════════════════════════════════════════════════════════════
let galleryInited = false;
let galleryReaders = [];
let gallerySelectedReader = null;
let galleryImages = [];
let galleryFilter = 'all';

let galleryScreens = [];
let _regressionFailures = {};
let gallerySelectedScreen = null;
let galleryScreenImages = [];

async function galleryInit() {
    if (galleryInited) return;
    galleryInited = true;

    try {
        // Use new screen-based API
        galleryScreens = await api('/api/gallery/screens');
        // Load regression failures to annotate sidebar
        try {
            const reg = await api('/api/regression/summary');
            if (reg && reg.readers) {
                // Map detector failures to screens via screens.yaml registration
                _regressionFailures = {};
                for (const s of galleryScreens) {
                    let screenFails = 0;
                    for (const det of (s.detectors || [])) {
                        const r = reg.readers[det];
                        if (r && r.failed > 0) screenFails += r.failed;
                    }
                    if (screenFails > 0) _regressionFailures[s.name] = screenFails;
                }
            }
        } catch (e) { /* regression data optional */ }
        renderGallerySidebar();
    } catch (e) {
        document.getElementById('gallery-sidebar').innerHTML = '<div style="color:#f85149; font-size:12px;">Failed to load screens</div>';
    }

    // Filter buttons
    document.querySelectorAll('.gallery-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            galleryFilter = btn.dataset.filter;
            document.querySelectorAll('.gallery-filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderGalleryGrid();
        });
    });
}

function renderGallerySidebar() {
    const sidebar = document.getElementById('gallery-sidebar');
    // Group: screens with images, then empty screens, then overlays
    const withImages = galleryScreens.filter(s => s.count > 0 && s.type === 'screen');
    const empty = galleryScreens.filter(s => s.count === 0 && s.type === 'screen');
    const overlays = galleryScreens.filter(s => s.type === 'overlay');

    const pillFor = (s, displayName) => {
        const fails = _regressionFailures[s.name] || 0;
        const labeled = s.labeled || 0;
        const total = s.count || 0;
        const allLabeled = total > 0 && labeled === total;
        const countColor = total === 0 ? '#484f58' : (allLabeled ? '#3fb950' : '#c9d1d9');
        const tip = `${labeled}/${total} labeled` + (fails > 0 ? ` \u00b7 ${fails} detector failures` : '');
        const failBadge = fails > 0 ? '<span style="color:#f85149; font-size:9px; margin-left:4px;" title="' + fails + ' detector failures">&#9888;' + fails + '</span>' : '';
        const active = gallerySelectedScreen === s.name ? ' active' : '';
        const opacity = total === 0 ? ' style="opacity:0.5;"' : '';
        return '<div class="reader-pill' + active + '" data-screen="' + s.name + '" title="' + tip + '"' + opacity + '>'
            + '<span>' + displayName + failBadge + '</span>'
            + '<span class="count-badge" style="color:' + countColor + ';">' + labeled + '/' + total + '</span>'
            + '</div>';
    };

    let html = '';
    if (withImages.length) {
        html += '<div style="color:#8b949e; font-size:10px; text-transform:uppercase; margin-bottom:4px;">Screens (labeled/total)</div>';
        html += withImages.map(s => pillFor(s, s.name)).join('');
    }
    if (empty.length) {
        html += '<div style="color:#8b949e; font-size:10px; text-transform:uppercase; margin:8px 0 4px;">Empty</div>';
        html += empty.map(s => pillFor(s, s.name)).join('');
    }
    if (overlays.length) {
        html += '<div style="color:#8b949e; font-size:10px; text-transform:uppercase; margin:8px 0 4px;">Overlays</div>';
        html += overlays.map(s => pillFor(s, s.name.replace('_overlays/', ''))).join('');
    }

    // Inbox link
    html += '<div style="color:#8b949e; font-size:10px; text-transform:uppercase; margin:8px 0 4px;">Inbox</div>';
    html += `<div class="reader-pill${gallerySelectedScreen === '_inbox' ? ' active' : ''}" data-screen="_inbox" style="border-color:#d29922;">
        <span>Unsorted</span>
        <span class="count-badge" id="inbox-count">...</span>
    </div>`;

    sidebar.innerHTML = html;

    // Load inbox count
    api('/api/gallery/inbox').then(d => {
        const badge = document.getElementById('inbox-count');
        if (badge) badge.textContent = d.count || 0;
    }).catch(() => {});

    sidebar.querySelectorAll('.reader-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            gallerySelectedScreen = pill.dataset.screen;
            renderGallerySidebar();
            if (gallerySelectedScreen === '_inbox') {
                loadGalleryInbox();
            } else {
                loadGalleryScreenImages(gallerySelectedScreen);
            }
        });
    });
}

// Store current screen data for use by label form
let _currentScreenData = null;

async function loadGalleryScreenImages(screen) {
    const grid = document.getElementById('gallery-grid');
    grid.innerHTML = '<div style="color:#484f58; font-size:12px;">Loading...</div>';
    document.getElementById('gallery-filters').style.display = 'flex';
    document.querySelectorAll('.gallery-filter-btn').forEach(b => {
        if (b.dataset.filter === 'true') b.textContent = 'Labeled';
        if (b.dataset.filter === 'false') b.textContent = 'Unlabeled';
    });
    try {
        const data = await api(`/api/gallery/screen/${encodeURIComponent(screen)}`);
        _currentScreenData = data;
        galleryScreenImages = data.images || [];
        galleryImages = galleryScreenImages;
        gallerySelectedReader = screen;
        refreshCurrentScreenCounts();
        // Reset grid layout: toolbar slot, bulk slot, cards container (renderGalleryGrid targets #gallery-cards).
        // Override parent display so slots stack vertically; cards container gets the grid layout.
        grid.style.display = 'block';
        grid.innerHTML = '<div id="gallery-toolbar-slot"></div><div id="gallery-bulk-slot"></div><div id="gallery-cards" style="display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px;"></div>';
        renderGalleryGrid();

        // Toolbar: info + action buttons
        const hasReaders = data.readers && Object.keys(data.readers).length > 0;
        const unlabeledCount = galleryImages.filter(i => i.status === 'unlabeled').length;
        const toolbar = document.createElement('div');
        toolbar.style.cssText = 'font-size:11px; color:#8b949e; margin-bottom:8px; padding:6px 8px; background:#161b22; border-radius:4px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;';

        let info = data.description || '';
        if (hasReaders) info += ` | Readers: ${Object.keys(data.readers).join(', ')}`;
        info += ` | ${unlabeledCount} unlabeled`;

        let buttons = '';
        if (!hasReaders && unlabeledCount > 0) {
            // No readers - offer bulk confirm
            buttons += `<button class="btn btn-primary" id="bulk-confirm-btn" style="font-size:11px; padding:3px 10px;">Confirm All ${unlabeledCount} (no labels needed)</button>`;
        }
        if (hasReaders && unlabeledCount > 0) {
            buttons += `<button class="btn" id="bulk-ocr-btn" style="font-size:11px; padding:3px 10px;">Bulk OCR Suggest (${unlabeledCount} unlabeled)</button>`;
            buttons += `<button class="btn" id="start-labeling-btn" style="font-size:11px; padding:3px 10px;">Start Labeling Unlabeled</button>`;
        }

        // Always show these tools
        buttons += `<button class="btn" id="bulk-select-toggle" style="font-size:11px; padding:3px 10px;">Select Mode</button>`;
        buttons += `<button class="btn" id="verify-detectors-btn" style="font-size:11px; padding:3px 10px;">Verify Detectors</button>`;

        toolbar.innerHTML = `<span>${info}</span><div style="display:flex; gap:6px; flex-wrap:wrap;">${buttons}</div>`;
        document.getElementById('gallery-toolbar-slot').appendChild(toolbar);

        // Bulk select mode toggle
        document.getElementById('bulk-select-toggle').addEventListener('click', () => {
            _bulkSelectMode = !_bulkSelectMode;
            _bulkSelected.clear();
            document.getElementById('bulk-select-toggle').textContent = _bulkSelectMode ? 'Exit Select Mode' : 'Select Mode';
            // Add/remove bulk action bar
            let bar = document.getElementById('bulk-action-bar');
            if (_bulkSelectMode && !bar) {
                bar = document.createElement('div');
                bar.id = 'bulk-action-bar';
                bar.style.cssText = 'display:flex; gap:8px; align-items:center; padding:6px 8px; background:#161b22; border:1px solid #30363d; border-radius:4px; margin-bottom:8px; font-size:11px;';
                const screenOpts = galleryScreens.filter(s => s.name !== gallerySelectedScreen).map(s => `<option value="${s.name}">${s.name}</option>`).join('');
                bar.innerHTML = `
                    <button class="btn" id="bulk-select-all" style="font-size:10px; padding:2px 8px;">Select All</button>
                    <button class="btn" id="bulk-select-flagged" style="font-size:10px; padding:2px 8px;">Select Flagged</button>
                    <span id="bulk-count" style="color:#8b949e;">0 selected</span>
                    <select id="bulk-target" style="font-size:10px; padding:2px 4px; background:#0d1117; color:#c9d1d9; border:1px solid #30363d; border-radius:3px;">
                        <option value="_inbox">_inbox</option>
                        <option value="_other">_other (animations/misc)</option>
                        ${screenOpts}
                    </select>
                    <button class="btn" id="bulk-move-btn" disabled style="font-size:10px; padding:2px 8px;">Move Selected</button>
                    <button class="btn" id="bulk-delete-btn" disabled style="font-size:10px; padding:2px 8px; color:#f85149;">Delete Selected</button>
                `;
                document.getElementById('gallery-bulk-slot').appendChild(bar);
                document.getElementById('bulk-select-all').addEventListener('click', () => {
                    const all = _bulkSelected.size === galleryImages.length;
                    _bulkSelected.clear();
                    if (!all) galleryImages.forEach(i => _bulkSelected.add(i.filename));
                    renderGalleryGrid();
                    _updateBulkBar();
                });
                document.getElementById('bulk-select-flagged').addEventListener('click', () => {
                    _bulkSelected.clear();
                    galleryImages.filter(i => i._detectorFail).forEach(i => _bulkSelected.add(i.filename));
                    renderGalleryGrid();
                    _updateBulkBar();
                });
                document.getElementById('bulk-move-btn').addEventListener('click', async () => {
                    const target = document.getElementById('bulk-target').value;
                    const fnames = [..._bulkSelected];
                    if (!fnames.length) return;
                    const btn = document.getElementById('bulk-move-btn');
                    btn.disabled = true; btn.textContent = `Moving ${fnames.length}...`;
                    for (const fname of fnames) {
                        await fetch(`${API}/api/gallery/image-move`, {
                            method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({screen: gallerySelectedScreen, filename: fname, target})
                        });
                    }
                    _bulkSelected.clear();
                    _bulkSelectMode = false;
                    loadGalleryScreenImages(gallerySelectedScreen);
                });
                document.getElementById('bulk-delete-btn').addEventListener('click', async () => {
                    const fnames = [..._bulkSelected];
                    if (!fnames.length || !confirm(`Delete ${fnames.length} images?`)) return;
                    const btn = document.getElementById('bulk-delete-btn');
                    btn.disabled = true; btn.textContent = `Deleting...`;
                    for (const fname of fnames) {
                        await fetch(`${API}/api/gallery/image-move`, {
                            method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({screen: gallerySelectedScreen, filename: fname, target: '__delete'})
                        });
                    }
                    _bulkSelected.clear();
                    _bulkSelectMode = false;
                    loadGalleryScreenImages(gallerySelectedScreen);
                });
            } else if (!_bulkSelectMode && bar) {
                bar.remove();
            }
            renderGalleryGrid();
        });

        // Verify detectors - batch debug all images via single ColePC request
        document.getElementById('verify-detectors-btn').addEventListener('click', async () => {
            const btn = document.getElementById('verify-detectors-btn');
            const screenInfo = galleryScreens.find(s => s.name === gallerySelectedScreen);
            const registered = screenInfo ? (screenInfo.detectors || []) : [];

            if (registered.length === 0) {
                btn.textContent = 'No detectors registered';
                setTimeout(() => { btn.textContent = 'Verify Detectors'; }, 2000);
                return;
            }

            btn.disabled = true;
            btn.textContent = `Verifying ${galleryImages.length} images...`;

            try {
                const resp = await fetch(`${API}/api/detector/debug-batch`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({screen: gallerySelectedScreen})
                }).then(r => r.json());

                let failures = 0;
                if (resp.ok && resp.results) {
                    for (const img of galleryImages) {
                        const r = resp.results[img.filename];
                        if (r && r.detectors) {
                            const anyTrue = r.detectors.some(d => registered.includes(d.name) && d.detected);
                            img._detectorFail = !anyTrue;
                            if (!anyTrue) failures++;
                        } else if (r && r.error) {
                            img._detectorFail = true;
                            failures++;
                        }
                    }
                }
                btn.textContent = failures > 0 ? `${failures} failures (red border)` : 'All passed!';
            } catch (e) {
                btn.textContent = 'Error - ColePC reachable?';
                console.error('verify batch:', e);
            }
            btn.disabled = false;
            renderGalleryGrid();
        });

        // Bulk confirm handler
        const confirmBtn = document.getElementById('bulk-confirm-btn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', async () => {
                confirmBtn.disabled = true;
                confirmBtn.textContent = 'Confirming...';
                try {
                    const resp = await fetch(`${API}/api/gallery/manifest/${encodeURIComponent(screen)}/bulk-confirm`, {method:'POST'}).then(r=>r.json());
                    confirmBtn.textContent = `Done! ${resp.confirmed} confirmed`;
                    setTimeout(() => loadGalleryScreenImages(screen), 800);
                } catch (e) { confirmBtn.textContent = 'Error'; }
            });
        }

        // Bulk OCR suggest handler
        const ocrBtn = document.getElementById('bulk-ocr-btn');
        if (ocrBtn) {
            ocrBtn.addEventListener('click', async () => {
                ocrBtn.disabled = true;
                const readers = Object.keys(data.readers);
                let totalSuggested = 0;
                for (const reader of readers) {
                    ocrBtn.textContent = `Running ${reader}...`;
                    try {
                        const resp = await fetch(`${API}/api/ocr/suggest-bulk`, {
                            method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({screen, reader, auto_save: true})
                        }).then(r=>r.json());
                        if (resp.results) {
                            // Bulk-update the manifest
                            const labels = {};
                            for (const [fname, fields] of Object.entries(resp.results)) {
                                labels[fname] = {[reader]: fields};
                            }
                            if (Object.keys(labels).length) {
                                await fetch(`${API}/api/gallery/manifest/${encodeURIComponent(screen)}/bulk-update`, {
                                    method:'POST', headers:{'Content-Type':'application/json'},
                                    body: JSON.stringify({labels})
                                });
                                totalSuggested += Object.keys(labels).length;
                            }
                        }
                    } catch (e) { console.error('bulk ocr:', e); }
                }
                ocrBtn.textContent = `Done! ${totalSuggested} suggested`;
                setTimeout(() => loadGalleryScreenImages(screen), 800);
            });
        }

        // Start labeling - open first unlabeled image
        const startBtn = document.getElementById('start-labeling-btn');
        if (startBtn) {
            startBtn.addEventListener('click', () => {
                const first = galleryImages.find(i => i.status === 'unlabeled');
                if (first) expandGalleryCard(first.filename);
            });
        }
    } catch (e) {
        grid.innerHTML = '<div style="color:#f85149; font-size:12px;">Failed to load images</div>';
    }
}

async function loadGalleryInbox() {
    const grid = document.getElementById('gallery-grid');
    grid.innerHTML = '<div style="color:#484f58; font-size:12px;">Loading inbox...</div>';
    document.getElementById('gallery-filters').style.display = 'none';
    try {
        const data = await api('/api/gallery/inbox');
        if (!data.images || !data.images.length) {
            grid.innerHTML = '<div style="color:#484f58; font-size:12px;">Inbox is empty</div>';
            return;
        }
        // Show assign UI
        const screenOptions = galleryScreens.filter(s => s.type === 'screen').map(s => `<option value="${s.name}">${s.name}</option>`).join('');
        grid.innerHTML = `
            <div style="margin-bottom:12px; display:flex; gap:8px; align-items:center;">
                <button class="btn" id="inbox-select-all">Select All</button>
                <select id="inbox-screen-select" style="font-size:12px; padding:4px 8px;">
                    <option value="">-- Assign to screen --</option>
                    ${screenOptions}
                </select>
                <button class="btn btn-primary" id="inbox-assign-btn" disabled>Assign Selected</button>
                <span id="inbox-selected-count" style="font-size:11px; color:#8b949e;">0 selected</span>
            </div>
            <div class="gallery-grid" id="inbox-grid">${data.images.map(img => `
                <div class="gallery-card inbox-card" data-filename="${img.filename}" style="cursor:pointer; position:relative;">
                    <input type="checkbox" class="inbox-check" style="position:absolute; top:4px; left:4px; z-index:1;">
                    <img class="thumb" loading="lazy" src="${API}/api/gallery/thumb/${img.path}" alt="${img.filename}">
                    <div class="fname">${img.filename}</div>
                </div>
            `).join('')}</div>
        `;
        // Wire up inbox interactions
        const checks = grid.querySelectorAll('.inbox-check');
        const countEl = document.getElementById('inbox-selected-count');
        const assignBtn = document.getElementById('inbox-assign-btn');
        const updateCount = () => {
            const n = grid.querySelectorAll('.inbox-check:checked').length;
            countEl.textContent = `${n} selected`;
            assignBtn.disabled = n === 0 || !document.getElementById('inbox-screen-select').value;
        };
        checks.forEach(cb => cb.addEventListener('change', updateCount));
        document.getElementById('inbox-screen-select').addEventListener('change', updateCount);
        document.getElementById('inbox-select-all').addEventListener('click', () => {
            const allChecked = [...checks].every(c => c.checked);
            checks.forEach(c => { c.checked = !allChecked; });
            updateCount();
        });
        // Click card to toggle
        grid.querySelectorAll('.inbox-card').forEach(card => {
            card.addEventListener('click', e => {
                if (e.target.type === 'checkbox') return;
                const cb = card.querySelector('.inbox-check');
                cb.checked = !cb.checked;
                updateCount();
            });
        });
        // Assign button
        assignBtn.addEventListener('click', async () => {
            const screen = document.getElementById('inbox-screen-select').value;
            if (!screen) return;
            const filenames = [...grid.querySelectorAll('.inbox-check:checked')].map(
                cb => cb.closest('.inbox-card').dataset.filename
            );
            if (!filenames.length) return;
            assignBtn.disabled = true;
            assignBtn.textContent = 'Assigning...';
            try {
                const resp = await fetch(`${API}/api/gallery/inbox/assign`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({filenames, screen})
                }).then(r => r.json());
                assignBtn.textContent = `Moved ${resp.moved}!`;
                // Refresh
                setTimeout(() => { galleryInited = false; galleryInit(); }, 800);
            } catch (e) {
                assignBtn.textContent = 'Error!';
            }
        });
    } catch (e) {
        grid.innerHTML = '<div style="color:#f85149; font-size:12px;">Failed to load inbox</div>';
    }
}

function _gtLabel(img) {
    // New manifest-based labels
    if (img.status) {
        if (img.status === 'complete') return 'Labeled';
        if (img.status === 'partial') return 'Partial';
        if (img.status === 'unlabeled') return 'Unlabeled';
    }
    // Legacy filename-based labels
    const gt = img.ground_truth;
    if (!gt) return '';
    if (gt.type === 'bool') return gt.values[0] ? 'True' : 'False';
    if (gt.type === 'words') return gt.values.join(' ');
    if (gt.type === 'int') return String(gt.values[0]);
    return gt.raw || '';
}

let _bulkSelectMode = false;
let _bulkSelected = new Set();

// Recompute the current screen's count/labeled from in-memory images and refresh the sidebar.
function refreshCurrentScreenCounts() {
    if (!gallerySelectedScreen) return;
    const s = galleryScreens.find(x => x.name === gallerySelectedScreen);
    if (!s) return;
    s.count = galleryImages.length;
    s.labeled = galleryImages.filter(i => i.status && i.status !== 'unlabeled').length;
    renderGallerySidebar();
}

function renderGalleryGrid() {
    // Target the cards container if present, otherwise the whole grid (e.g. inbox view).
    const grid = document.getElementById('gallery-cards') || document.getElementById('gallery-grid');
    let filtered = galleryImages;
    if (galleryFilter === 'true') filtered = galleryImages.filter(i => (i.status || '') !== 'unlabeled' && _gtLabel(i) !== 'Unlabeled');
    if (galleryFilter === 'false') filtered = galleryImages.filter(i => i.status === 'unlabeled' || _gtLabel(i) === 'Unlabeled');

    if (!filtered.length) {
        grid.innerHTML = '<div style="color:#484f58; font-size:12px;">No images match filter</div>';
        return;
    }

    grid.innerHTML = filtered.map(img => {
        const label = _gtLabel(img);
        let badgeClass = 'badge-value';
        if (label === 'True' || label === 'Labeled') badgeClass = 'badge-true';
        else if (label === 'False' || label === 'Unlabeled') badgeClass = 'badge-false';
        else if (label === 'Partial') badgeClass = 'badge-value';
        const checked = _bulkSelected.has(img.filename) ? 'checked' : '';
        const flagged = img._detectorFail ? ' style="border:2px solid #f85149;"' : '';
        return `<div class="gallery-card" data-filename="${img.filename}"${flagged}>
            ${_bulkSelectMode ? `<input type="checkbox" class="bulk-check" ${checked} style="position:absolute; top:4px; left:4px; z-index:1;">` : ''}
            <img class="thumb" loading="lazy" src="${API}/api/gallery/thumb/${img.path}" alt="${img.filename}">
            <div class="fname">${img.filename}</div>
            <span class="truth-badge ${badgeClass}">${label}</span>
            ${img._detectorFail ? '<span style="position:absolute; top:4px; right:4px; background:#f85149; color:#fff; font-size:9px; padding:1px 4px; border-radius:3px;">FAIL</span>' : ''}
        </div>`;
    }).join('');

    grid.querySelectorAll('.gallery-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (_bulkSelectMode) {
                if (e.target.type === 'checkbox') return; // let checkbox handle itself
                const cb = card.querySelector('.bulk-check');
                if (cb) { cb.checked = !cb.checked; }
                const fname = card.dataset.filename;
                if (cb && cb.checked) _bulkSelected.add(fname); else _bulkSelected.delete(fname);
                _updateBulkBar();
                return;
            }
            expandGalleryCard(card.dataset.filename);
        });
        const cb = card.querySelector('.bulk-check');
        if (cb) cb.addEventListener('change', () => {
            const fname = card.dataset.filename;
            if (cb.checked) _bulkSelected.add(fname); else _bulkSelected.delete(fname);
            _updateBulkBar();
        });
    });
}

function _updateBulkBar() {
    const bar = document.getElementById('bulk-action-bar');
    if (!bar) return;
    const count = _bulkSelected.size;
    bar.querySelector('#bulk-count').textContent = `${count} selected`;
    bar.querySelector('#bulk-move-btn').disabled = count === 0;
    bar.querySelector('#bulk-delete-btn').disabled = count === 0;
}

// Cache screen reader schema for label forms
let _screenReaderSchema = null;

async function expandGalleryCard(filename) {
    const overlay = document.createElement('div');
    overlay.className = 'gallery-expanded-overlay';
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

    const img = galleryImages.find(i => i.filename === filename);
    const screen = gallerySelectedScreen || gallerySelectedReader;
    const imgPath = img ? img.path : `${encodeURIComponent(screen)}/${encodeURIComponent(filename)}`;

    overlay.innerHTML = `<div class="gallery-expanded">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div style="font-size:14px; color:#58a6ff; font-weight:bold;">${filename}</div>
            <div style="display:flex; gap:8px;">
                <span id="gallery-save-status" style="font-size:11px; color:#8b949e; line-height:28px;"></span>
                <button class="btn btn-primary" id="gallery-save-labels-btn" style="display:none;">Save Labels</button>
                <button class="btn" id="gallery-debug-detectors" style="font-size:10px; padding:2px 8px;" title="Run all detectors on this image">Debug Detectors</button>
                <select id="gallery-move-to" style="font-size:10px; padding:2px 4px; background:#161b22; color:#c9d1d9; border:1px solid #30363d; border-radius:3px;">
                    <option value="">Move to...</option>
                </select>
                <button class="btn" id="gallery-nav-prev" title="Previous">&#9664;</button>
                <button class="btn" id="gallery-nav-next" title="Next">&#9654;</button>
                <button class="btn" onclick="this.closest('.gallery-expanded-overlay').remove()">Close</button>
            </div>
        </div>
        <div style="display:flex; gap:16px; flex-wrap:wrap;">
            <div style="flex:1; min-width:400px;">
                <img src="${API}/api/gallery/image/${imgPath}" alt="${filename}" style="max-width:100%;">
                <div class="crops" id="gallery-expanded-crops" style="margin-top:8px;"><div style="color:#484f58; font-size:12px;">Loading crops...</div></div>
            </div>
            <div style="flex:0 0 340px;" id="gallery-label-form">
                <div style="color:#484f58; font-size:12px;">Loading schema...</div>
            </div>
        </div>
    </div>`;
    document.body.appendChild(overlay);

    // Nav buttons
    const imgIdx = galleryImages.findIndex(i => i.filename === filename);
    overlay.querySelector('#gallery-nav-prev').addEventListener('click', () => {
        if (imgIdx > 0) { overlay.remove(); expandGalleryCard(galleryImages[imgIdx - 1].filename); }
    });
    overlay.querySelector('#gallery-nav-next').addEventListener('click', () => {
        if (imgIdx < galleryImages.length - 1) { overlay.remove(); expandGalleryCard(galleryImages[imgIdx + 1].filename); }
    });

    // Helper: find next/prev unlabeled
    const nextUnlabeled = (from, dir) => {
        for (let i = from + dir; i >= 0 && i < galleryImages.length; i += dir) {
            if (galleryImages[i].status === 'unlabeled' || galleryImages[i].status === 'partial') return i;
        }
        return -1;
    };

    // Keyboard nav
    const keyHandler = (e) => {
        // Don't intercept when typing in inputs
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') {
            // Ctrl/Cmd+Enter: save + advance even from input
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const saveBtn = overlay.querySelector('#gallery-save-labels-btn');
                if (saveBtn && !saveBtn.disabled) saveBtn.click();
            }
            return;
        }
        if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', keyHandler); }
        // Arrow nav
        if (e.key === 'ArrowLeft' && imgIdx > 0) { overlay.remove(); document.removeEventListener('keydown', keyHandler); expandGalleryCard(galleryImages[imgIdx - 1].filename); }
        if (e.key === 'ArrowRight' && imgIdx < galleryImages.length - 1) { overlay.remove(); document.removeEventListener('keydown', keyHandler); expandGalleryCard(galleryImages[imgIdx + 1].filename); }
        // Ctrl+Arrow: skip to next/prev unlabeled
        if ((e.ctrlKey || e.metaKey) && e.key === 'ArrowRight') { e.preventDefault(); const n = nextUnlabeled(imgIdx, 1); if (n >= 0) { overlay.remove(); document.removeEventListener('keydown', keyHandler); expandGalleryCard(galleryImages[n].filename); } }
        if ((e.ctrlKey || e.metaKey) && e.key === 'ArrowLeft') { e.preventDefault(); const n = nextUnlabeled(imgIdx, -1); if (n >= 0) { overlay.remove(); document.removeEventListener('keydown', keyHandler); expandGalleryCard(galleryImages[n].filename); } }
        // Ctrl/Cmd+Enter: save + advance
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            const saveBtn = overlay.querySelector('#gallery-save-labels-btn');
            if (saveBtn && !saveBtn.disabled) saveBtn.click();
        }
    };
    document.addEventListener('keydown', keyHandler);
    const obs = new MutationObserver(() => { if (!document.body.contains(overlay)) { document.removeEventListener('keydown', keyHandler); obs.disconnect(); } });
    obs.observe(document.body, {childList: true});

    // Load crops
    try {
        const crops = await api(`/api/gallery/screen_crops/${encodeURIComponent(screen)}/${encodeURIComponent(filename)}`);
        const cropsEl = overlay.querySelector('#gallery-expanded-crops');
        if (Array.isArray(crops) && crops.length) {
            cropsEl.innerHTML = crops.map(c => `
                <div class="crop-item">
                    <img src="${c.data || ''}" alt="${c.name}" style="image-rendering:pixelated;">
                    <div class="crop-label">${c.reader}: ${c.name}</div>
                </div>
            `).join('');
        } else {
            cropsEl.innerHTML = '<div style="color:#484f58; font-size:12px;">No crops defined</div>';
        }
    } catch (e) { console.error('loadCrops:', e); }

    // "Move to..." dropdown - populate with all screens + inbox + delete
    const moveTo = overlay.querySelector('#gallery-move-to');
    const screenList = galleryScreens.filter(s => s.name !== screen);
    moveTo.innerHTML = '<option value="">Move to...</option>'
        + screenList.map(s => `<option value="${s.name}">${s.name}</option>`).join('')
        + '<option value="_inbox">_inbox</option>'
        + '<option value="_other">_other (animations/misc)</option>'
        + '<option value="__delete" style="color:#f85149;">Delete image</option>';
    moveTo.addEventListener('change', async () => {
        const target = moveTo.value;
        if (!target) return;
        if (target === '__delete') {
            if (!confirm(`Delete ${filename}?`)) { moveTo.value = ''; return; }
            await fetch(`${API}/api/gallery/image-move`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({screen, filename, target: '__delete'})
            });
        } else {
            await fetch(`${API}/api/gallery/image-move`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({screen, filename, target})
            });
        }
        // Remove from local array and advance
        const idx = galleryImages.findIndex(i => i.filename === filename);
        if (idx >= 0) galleryImages.splice(idx, 1);
        refreshCurrentScreenCounts();
        overlay.remove();
        if (galleryImages.length > 0) {
            const next = Math.min(idx, galleryImages.length - 1);
            expandGalleryCard(galleryImages[next].filename);
        }
    });

    // Debug detectors button
    overlay.querySelector('#gallery-debug-detectors').addEventListener('click', async function() {
        const btn = this;
        btn.disabled = true;
        btn.textContent = 'Running...';
        try {
            const resp = await fetch(`${API}/api/detector/debug`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({screen, filename})
            }).then(r => r.json());

            if (resp.ok && resp.result) {
                const r = resp.result;
                let html = '<div style="margin-top:12px; font-size:11px; border:1px solid #30363d; border-radius:6px; padding:8px; background:#0d1117;">';
                html += '<div style="color:#8b949e; text-transform:uppercase; margin-bottom:6px; font-size:10px;">Detector Results</div>';
                // Detector pass/fail
                for (const d of (r.detectors || [])) {
                    const color = d.detected ? '#3fb950' : '#f85149';
                    html += `<div style="color:${color}; margin-bottom:2px;">${d.detected ? '✓' : '✗'} ${d.name}</div>`;
                }
                // Region color stats
                if (r.regions && r.regions.length) {
                    html += '<div style="color:#8b949e; text-transform:uppercase; margin-top:8px; margin-bottom:4px; font-size:10px;">Region Color Stats</div>';
                    html += '<table style="font-size:10px; color:#c9d1d9; border-collapse:collapse; width:100%;">';
                    html += '<tr style="color:#8b949e;"><th style="text-align:left; padding:2px 4px;">Region</th><th>Avg RGB</th><th>StdDev</th></tr>';
                    for (const reg of r.regions) {
                        const avg = reg.avg ? reg.avg.map(v => Math.round(v * 255)).join(', ') : '?';
                        const sd = reg.stddev != null ? reg.stddev.toFixed(2) : '?';
                        const bgColor = reg.avg ? `rgb(${reg.avg.map(v => Math.round(v * 255)).join(',')})` : '#000';
                        html += `<tr><td style="padding:2px 4px;">${reg.name}</td>`;
                        html += `<td style="padding:2px 4px; text-align:center;"><span style="display:inline-block; width:12px; height:12px; background:${bgColor}; border:1px solid #30363d; border-radius:2px; vertical-align:middle; margin-right:4px;"></span>${avg}</td>`;
                        html += `<td style="padding:2px 4px; text-align:center;">${sd}</td></tr>`;
                    }
                    html += '</table>';
                }
                html += '</div>';

                // Insert after crops
                const cropsEl = overlay.querySelector('#gallery-expanded-crops');
                cropsEl.insertAdjacentHTML('afterend', html);
                btn.textContent = 'Debug Detectors';
                btn.disabled = false;
            } else {
                btn.textContent = resp.error || 'Failed';
                setTimeout(() => { btn.textContent = 'Debug Detectors'; btn.disabled = false; }, 3000);
            }
        } catch (e) {
            btn.textContent = 'Error';
            console.error('detector debug:', e);
            setTimeout(() => { btn.textContent = 'Debug Detectors'; btn.disabled = false; }, 3000);
        }
    });

    // Build label form from screen schema
    await buildLabelForm(overlay, screen, filename, img);
}

async function buildLabelForm(overlay, screen, filename, img) {
    const formEl = overlay.querySelector('#gallery-label-form');
    const saveBtn = overlay.querySelector('#gallery-save-labels-btn');
    const statusEl = overlay.querySelector('#gallery-save-status');

    // Get screen info (with reader schemas)
    let screenData;
    try {
        screenData = await api(`/api/gallery/screen/${encodeURIComponent(screen)}`);
    } catch (e) {
        formEl.innerHTML = '<div style="color:#f85149; font-size:12px;">Failed to load schema</div>';
        return;
    }

    const readers = screenData.readers || {};
    if (!Object.keys(readers).length) {
        formEl.innerHTML = '<div style="color:#484f58; font-size:12px;">No readers registered for this screen</div>';
        return;
    }

    const existingLabels = (img && img.labels) || {};

    let html = '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">'
        + '<span style="font-size:11px; color:#8b949e; text-transform:uppercase;">Reader Labels</span>'
        + '<button class="btn" id="gallery-copy-prev" style="font-size:10px; padding:2px 8px;">Copy Prev</button>'
        + '<button class="btn" id="gallery-auto-suggest-all" style="font-size:10px; padding:2px 8px;">Auto-Suggest All</button>'
        + '</div>';

    for (const [readerName, readerDef] of Object.entries(readers)) {
        const fields = readerDef.fields || {};
        const existing = existingLabels[readerName] || {};
        html += `<div style="background:#161b22; border:1px solid #30363d; border-radius:6px; padding:10px; margin-bottom:8px;">`;
        html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-size:12px; color:#58a6ff; font-weight:bold;">${readerName}</span>
            <button class="btn suggest-reader-btn" data-reader="${readerName}" style="font-size:9px; padding:1px 6px;">Suggest</button>
        </div>`;

        for (const [fieldName, fieldDef] of Object.entries(fields)) {
            const val = existing[fieldName];
            html += `<div style="margin-bottom:6px;">`;
            html += `<label style="font-size:11px; color:#8b949e; display:block; margin-bottom:2px;">${fieldName}</label>`;

            if (fieldDef.type === 'array') {
                const len = fieldDef.length || 1;
                const items = fieldDef.items || 'string';
                for (let i = 0; i < len; i++) {
                    const arrVal = Array.isArray(val) && val[i] != null ? val[i] : '';
                    const inputType = items === 'int' ? 'number' : 'text';
                    html += `<input type="${inputType}" class="manifest-input" data-reader="${readerName}" data-field="${fieldName}" data-index="${i}"
                        value="${arrVal}" placeholder="${fieldName}[${i}]"
                        style="width:100%; font-size:12px; padding:3px 6px; margin-bottom:2px; background:#0d1117; border:1px solid #30363d; color:#c9d1d9; border-radius:3px;">`;
                }
            } else if (fieldDef.type === 'int') {
                html += `<input type="number" class="manifest-input" data-reader="${readerName}" data-field="${fieldName}"
                    value="${val != null ? val : ''}" placeholder="${fieldName}"
                    ${fieldDef.min != null ? `min="${fieldDef.min}"` : ''} ${fieldDef.max != null ? `max="${fieldDef.max}"` : ''}
                    style="width:100%; font-size:12px; padding:3px 6px; background:#0d1117; border:1px solid #30363d; color:#c9d1d9; border-radius:3px;">`;
            } else if (fieldDef.type === 'bool') {
                html += `<select class="manifest-input" data-reader="${readerName}" data-field="${fieldName}"
                    style="width:100%; font-size:12px; padding:3px 6px; background:#0d1117; border:1px solid #30363d; color:#c9d1d9; border-radius:3px;">
                    <option value="" ${val == null ? 'selected' : ''}>--</option>
                    <option value="true" ${val === true ? 'selected' : ''}>true</option>
                    <option value="false" ${val === false ? 'selected' : ''}>false</option>
                </select>`;
            } else {
                // string
                html += `<input type="text" class="manifest-input" data-reader="${readerName}" data-field="${fieldName}"
                    value="${val != null ? val : ''}" placeholder="${fieldName}"
                    style="width:100%; font-size:12px; padding:3px 6px; background:#0d1117; border:1px solid #30363d; color:#c9d1d9; border-radius:3px;">`;
            }
            html += `</div>`;
        }
        html += `</div>`;
    }

    formEl.innerHTML = html;
    saveBtn.style.display = 'inline-block';

    // Collect form values into a labels object
    function collectLabels() {
        const labels = {};
        formEl.querySelectorAll('.manifest-input').forEach(input => {
            const reader = input.dataset.reader;
            const field = input.dataset.field;
            const index = input.dataset.index;
            if (!labels[reader]) labels[reader] = {};
            let val = input.value.trim();
            if (val === '') { val = null; }
            else if (input.type === 'number') { val = parseInt(val, 10); }
            else if (input.tagName === 'SELECT') { val = val === 'true' ? true : val === 'false' ? false : null; }
            if (index != null) {
                if (!labels[reader][field]) labels[reader][field] = [];
                labels[reader][field][parseInt(index)] = val;
            } else {
                labels[reader][field] = val;
            }
        });
        return labels;
    }

    // Save and optionally advance to next image
    async function saveAndAdvance(advance = false) {
        const labels = collectLabels();
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
        try {
            await fetch(`${API}/api/gallery/manifest/${encodeURIComponent(screen)}/${encodeURIComponent(filename)}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(labels),
            });
            if (img) {
                img.labels = labels;
                img.status = Object.keys(labels).length ? 'complete' : 'unlabeled';
                img._visited = true;
            }
            refreshCurrentScreenCounts();
            if (advance) {
                // Find current position fresh (may have shifted from moves/deletes)
                const currentIdx = galleryImages.findIndex(im => im.filename === filename);
                // Find next unlabeled/partial that we haven't visited
                let target = -1;
                for (let i = currentIdx + 1; i < galleryImages.length; i++) {
                    const im = galleryImages[i];
                    if (!im._visited && (im.status === 'unlabeled' || im.status === 'partial')) { target = i; break; }
                }
                // If nothing forward, wrap from start
                if (target < 0) {
                    for (let i = 0; i < currentIdx; i++) {
                        const im = galleryImages[i];
                        if (!im._visited && (im.status === 'unlabeled' || im.status === 'partial')) { target = i; break; }
                    }
                }
                if (target >= 0) {
                    overlay.remove();
                    expandGalleryCard(galleryImages[target].filename);
                    return;
                }
                // All done
                statusEl.textContent = 'All images labeled!';
                statusEl.style.color = '#3fb950';
                saveBtn.textContent = 'Save Labels';
                saveBtn.disabled = false;
                return;
            }
            statusEl.textContent = 'Saved!';
            statusEl.style.color = '#3fb950';
            saveBtn.textContent = 'Save Labels';
            saveBtn.disabled = false;
            setTimeout(() => { statusEl.textContent = ''; }, 2000);
        } catch (e) {
            statusEl.textContent = 'Error!';
            statusEl.style.color = '#f85149';
            saveBtn.textContent = 'Save Labels';
            saveBtn.disabled = false;
        }
    }

    saveBtn.addEventListener('click', () => saveAndAdvance(false));

    // Ctrl/Cmd+Enter: save and advance to next unlabeled
    // (wired in keyHandler above, triggers saveBtn.click - override to use advance mode)
    saveBtn._saveAndAdvance = saveAndAdvance;

    // Override the Ctrl+Enter in keyHandler to use save+advance
    const origSaveBtnClick = saveBtn.onclick;
    overlay.querySelector('#gallery-save-labels-btn').addEventListener('dblclick', () => saveAndAdvance(true));
    // Add a separate "Save & Next" button
    const saveNextBtn = document.createElement('button');
    saveNextBtn.className = 'btn btn-primary';
    saveNextBtn.textContent = 'Save & Next (Ctrl+Enter)';
    saveNextBtn.style.cssText = 'font-size:11px;';
    saveNextBtn.addEventListener('click', () => saveAndAdvance(true));
    saveBtn.parentElement.insertBefore(saveNextBtn, saveBtn.nextSibling);

    // Rewire Ctrl+Enter in the keyboard handler
    const overlayKeyOverride = (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault(); e.stopPropagation();
            saveAndAdvance(true);
        }
    };
    overlay.addEventListener('keydown', overlayKeyOverride, true);

    // Per-reader suggest buttons
    formEl.querySelectorAll('.suggest-reader-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const reader = btn.dataset.reader;
            btn.textContent = '...';
            btn.disabled = true;
            try {
                const resp = await fetch(`${API}/api/ocr/suggest`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({screen, filename, reader}),
                }).then(r => r.json());
                if (resp.ok && resp.result) {
                    // Fill form fields with suggestions (highlighted)
                    const result = resp.result;
                    for (const [field, val] of Object.entries(result)) {
                        if (Array.isArray(val)) {
                            val.forEach((v, i) => {
                                const input = formEl.querySelector(`.manifest-input[data-reader="${reader}"][data-field="${field}"][data-index="${i}"]`);
                                if (input && !input.value) { input.value = v || ''; input.style.borderColor = '#d29922'; }
                            });
                        } else {
                            const input = formEl.querySelector(`.manifest-input[data-reader="${reader}"][data-field="${field}"]`);
                            if (input && !input.value) { input.value = val || ''; input.style.borderColor = '#d29922'; }
                        }
                    }
                    btn.textContent = 'Done';
                    statusEl.textContent = 'OCR suggestion applied (yellow = suggested)';
                    statusEl.style.color = '#d29922';
                } else {
                    btn.textContent = 'Failed';
                }
            } catch (e) {
                btn.textContent = 'Error';
                console.error('suggest:', e);
            }
            setTimeout(() => { btn.textContent = 'Suggest'; btn.disabled = false; }, 2000);
        });
    });

    // "Auto-Suggest All" button
    const suggestAllBtn = formEl.querySelector('#gallery-auto-suggest-all');
    if (suggestAllBtn) {
        suggestAllBtn.addEventListener('click', () => {
            formEl.querySelectorAll('.suggest-reader-btn').forEach(btn => btn.click());
        });
    }

    // "Copy from Previous" button
    const copyPrevBtn = formEl.querySelector('#gallery-copy-prev');
    if (copyPrevBtn) {
        if (imgIdx > 0 && galleryImages[imgIdx - 1].labels) {
            copyPrevBtn.addEventListener('click', () => {
                const prevLabels = galleryImages[imgIdx - 1].labels;
                for (const [reader, fields] of Object.entries(prevLabels)) {
                    for (const [field, val] of Object.entries(fields)) {
                        if (Array.isArray(val)) {
                            val.forEach((v, i) => {
                                const input = formEl.querySelector(`.manifest-input[data-reader="${reader}"][data-field="${field}"][data-index="${i}"]`);
                                if (input && !input.value) { input.value = v || ''; input.style.borderColor = '#58a6ff'; }
                            });
                        } else {
                            const input = formEl.querySelector(`.manifest-input[data-reader="${reader}"][data-field="${field}"]`);
                            if (input && !input.value) {
                                if (input.tagName === 'SELECT') {
                                    input.value = String(val);
                                } else {
                                    input.value = val != null ? val : '';
                                }
                                input.style.borderColor = '#58a6ff';
                            }
                        }
                    }
                }
                statusEl.textContent = 'Copied from previous (blue = copied)';
                statusEl.style.color = '#58a6ff';
            });
        } else {
            copyPrevBtn.disabled = true;
            copyPrevBtn.style.opacity = '0.4';
        }
    }

    // Auto-suggest on open if unlabeled
    if (img && img.status === 'unlabeled' && localStorage.getItem('autoSuggestOnOpen') !== 'false') {
        setTimeout(() => { if (suggestAllBtn) suggestAllBtn.click(); }, 300);
    }
}

