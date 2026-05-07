// Team Scan Verify — runs TeamSummaryReader + TeamStatsReader on the
// latest moves_and_more / team_stats pair, displays per-slot reads, and
// renders the assembled team as a Showdown paste.

let _teamScanInited = false;

async function teamScanInit() {
    if (_teamScanInited) return;
    _teamScanInited = true;

    async function fetchJson(path, opts) {
        const r = await fetch(path, opts);
        return r.json();
    }

    async function loadFileList(screen, selectId) {
        const sel = document.getElementById(selectId);
        sel.innerHTML = '';
        try {
            const r = await fetchJson('/api/gallery/screen/' + encodeURIComponent(screen));
            (r.images || []).forEach(img => {
                const opt = document.createElement('option');
                opt.value = img.filename;
                opt.textContent = img.filename;
                sel.appendChild(opt);
            });
        } catch (e) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = '(error loading)';
            sel.appendChild(opt);
        }
    }

    function tsEsc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function renderSlot(slot, mmFile, stFile) {
        const div = document.createElement('div');
        div.className = 'tsc-card';
        const stats = slot.stats || {};
        const speciesLabel = slot.species ? slot.species : '<span class="empty">(no species)</span>';
        const natureLabel = slot.nature ? `<span class="nature">${tsEsc(slot.nature)}</span>` : '';
        const itemLabel = slot.item ? slot.item : '<span class="empty">(no item)</span>';
        const abilityLabel = slot.ability ? slot.ability : '<span class="empty">(no ability)</span>';

        const statRows = ['hp','atk','def','spa','spd','spe'].map(k => {
            const s = stats[k] || {};
            const cls = s.nature === 'boost' ? 'boost' : s.nature === 'drop' ? 'drop' : '';
            const arrow = s.nature === 'boost' ? '+' : s.nature === 'drop' ? '-' : ' ';
            const evTag = s.evs ? ` <span style="color:#6e7681;">EV ${s.evs}</span>` : '';
            return `<div class="row ${cls}"><span class="key">${arrow} ${k.toUpperCase()}</span><span>${s.actual ?? 0}${evTag}</span></div>`;
        }).join('');

        const moves = (slot.moves || []).filter(m => m);
        const movesHtml = moves.length ?
            moves.map(m => `<div>${tsEsc(m)}</div>`).join('') :
            '<span class="empty">(no moves)</span>';

        div.innerHTML = `
            <div class="head">
                Slot ${slot.slot} — ${tsEsc(speciesLabel)} ${natureLabel}
            </div>
            <div class="meta">${tsEsc(abilityLabel)} @ ${tsEsc(itemLabel)}</div>
            <div style="margin-top:6px;">${statRows}</div>
            <div class="moves">${movesHtml}</div>
            <button class="crops-toggle">show crops &amp; raw OCR</button>
            <div class="crops-panel"></div>
        `;

        const toggleBtn = div.querySelector('.crops-toggle');
        const panel = div.querySelector('.crops-panel');
        let loaded = false;
        toggleBtn.addEventListener('click', async () => {
            const isOpen = panel.classList.toggle('open');
            toggleBtn.textContent = isOpen ? 'hide crops' : 'show crops & raw OCR';
            if (isOpen && !loaded) {
                loaded = true;
                panel.innerHTML = '<div style="font-size:10px; color:#8b949e;">loading...</div>';
                try {
                    const params = new URLSearchParams({slot: slot.slot, mm_file: mmFile, st_file: stFile});
                    const r = await fetchJson('/api/team-scan/crops?' + params);
                    panel.innerHTML = renderCropsPanel(r, slot);
                } catch (e) {
                    panel.innerHTML = `<div style="color:#f85149;">error: ${tsEsc(e.message)}</div>`;
                }
            }
        });

        return div;
    }

    function renderCropsPanel(crops, slot) {
        const stats = slot.stats || {};
        // For each stats crop, also pull the raw OCR text from the read result.
        // crops.stats entries have .field like "atk_actual" / "atk_evs" / "atk_nature".
        const lookup = (field) => {
            const [stat, sub] = field.split('_');
            const s = stats[stat] || {};
            if (sub === 'actual') return {raw: s.raw_actual, parsed: s.actual};
            if (sub === 'evs')    return {raw: s.raw_evs,    parsed: s.evs};
            if (sub === 'nature') return {raw: '', parsed: s.nature || 'neutral'};
            return {raw: '', parsed: ''};
        };
        const mmCells = crops.mm.map(c => `
            <div class="crop-cell">
                <div class="field">${tsEsc(c.field)}</div>
                ${c.data ? `<img src="${c.data}">` : '<span style="color:#f85149;">no img</span>'}
            </div>
        `).join('');
        const statCells = crops.stats.map(c => {
            const {raw, parsed} = lookup(c.field);
            return `
                <div class="crop-cell">
                    <div class="field">${tsEsc(c.field)}</div>
                    ${c.data ? `<img src="${c.data}">` : '<span style="color:#f85149;">no img</span>'}
                    <div class="read">parsed: ${tsEsc(String(parsed))}</div>
                    ${raw ? `<div class="read" style="color:#79c0ff;">raw: ${tsEsc(raw)}</div>` : ''}
                </div>
            `;
        }).join('');
        return `
            <div class="crops-section-label">Moves &amp; More boxes</div>
            <div class="crops-grid">${mmCells}</div>
            <div class="crops-section-label" style="margin-top:8px;">Stats boxes (parsed | raw OCR)</div>
            <div class="crops-grid">${statCells}</div>
        `;
    }

    function imgUrl(screen, filename) {
        return '/api/gallery/image/' + encodeURIComponent(screen + '/' + filename);
    }

    async function runScan() {
        const mm = document.getElementById('ts-mm-file').value;
        const st = document.getElementById('ts-st-file').value;
        const status = document.getElementById('ts-status');
        const slotsEl = document.getElementById('ts-slots');
        const pasteEl = document.getElementById('ts-paste');

        status.textContent = 'Reading...';
        slotsEl.innerHTML = '';
        pasteEl.textContent = '';

        document.getElementById('ts-mm-img').src = imgUrl('moves_and_more', mm);
        document.getElementById('ts-st-img').src = imgUrl('team_stats', st);

        try {
            const r = await fetchJson('/api/team-scan/read', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({moves_more_file: mm, stats_file: st}),
            });
            if (!r.ok) {
                status.textContent = 'Error: ' + (r.error || 'unknown');
                return;
            }
            (r.slots || []).forEach(slot => slotsEl.appendChild(renderSlot(slot, mm, st)));
            pasteEl.textContent = r.ps_paste || '';
            status.textContent = 'OK';
        } catch (e) {
            status.textContent = 'Error: ' + e.message;
        }
    }

    document.getElementById('ts-run').addEventListener('click', runScan);
    document.getElementById('ts-copy').addEventListener('click', () => {
        const txt = document.getElementById('ts-paste').textContent;
        navigator.clipboard.writeText(txt);
    });

    await loadFileList('moves_and_more', 'ts-mm-file');
    await loadFileList('team_stats', 'ts-st-file');

    try {
        const latest = await fetchJson('/api/team-scan/latest');
        if (latest.moves_more_file) document.getElementById('ts-mm-file').value = latest.moves_more_file;
        if (latest.stats_file)      document.getElementById('ts-st-file').value = latest.stats_file;
    } catch (e) { /* ignore */ }

    runScan();
}
