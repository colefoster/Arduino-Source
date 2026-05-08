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
        // Slug → display label: "throat-chop" → "Throat Chop"
        const titleize = s => s ? s.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : '';

        const speciesHtml = slot.species
            ? `<span class="species">${tsEsc(titleize(slot.species))}</span>`
            : `<span class="species" style="color:#6e7681; font-style:italic;">No species</span>`;
        const natureHtml = slot.nature
            ? `<span class="nature-pill">${tsEsc(slot.nature)}</span>`
            : '';

        const abilityHtml = slot.ability
            ? `<span class="ability">${tsEsc(titleize(slot.ability))}</span>`
            : `<span class="empty">no ability</span>`;
        const itemHtml = slot.item
            ? `<span class="item">${tsEsc(titleize(slot.item))}</span>`
            : `<span class="empty">no item</span>`;

        const STAT_LABELS = {hp:'HP', atk:'Atk', def:'Def', spa:'SpA', spd:'SpD', spe:'Spe'};
        const STAT_ORDER = ['hp','atk','def','spa','spd','spe'];
        const statHtml = STAT_ORDER.map(k => {
            const s = stats[k] || {};
            const cls = s.nature === 'boost' ? 'boost' : s.nature === 'drop' ? 'drop' : '';
            // Unicode escapes for triangle glyphs to keep this file ASCII-clean
            // (feedback_js_no_unicode_comments.md: literal Unicode in script
            // tags has tripped Chrome parsing in the past).
            const arrow = s.nature === 'boost' ? '\u25B2' : s.nature === 'drop' ? '\u25BC' : '';
            const ev = s.evs || 0;
            const evCls = ev === 0 ? 'zero' : (ev >= 32 ? 'full' : '');
            return `
                <div class="stat ${cls}">
                    <span class="arrow">${arrow}</span>
                    <span class="label">${STAT_LABELS[k]}</span>
                    <span class="value">${s.actual ?? 0}</span>
                    <span class="ev ${evCls}">${ev}</span>
                </div>
            `;
        }).join('');

        const moves = slot.moves || [];
        const movesHtml = moves.map(m =>
            m ? `<div class="move">${tsEsc(titleize(m))}</div>`
              : `<div class="move empty">—</div>`
        ).join('');

        div.innerHTML = `
            <div class="header">
                <div class="title">
                    <span class="slot-tag">Slot ${slot.slot}</span>
                    ${speciesHtml}
                </div>
                ${natureHtml}
            </div>
            <div class="meta">
                ${abilityHtml}
                <span class="sep">@</span>
                ${itemHtml}
            </div>
            <div class="stats">${statHtml}</div>
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

    //  Saved-team library section.
    async function loadSavedTeams() {
        const listEl = document.getElementById('ts-saved-list');
        const countEl = document.getElementById('ts-saved-count');
        const dirEl = document.getElementById('ts-saved-dir');
        try {
            const r = await fetchJson('/api/saved-teams/list');
            countEl.textContent = `(${r.count})`;
            dirEl.textContent = r.dir || '';
            if (!r.teams || !r.teams.length) {
                listEl.innerHTML = '<div style="color:#6e7681; font-size:11px; font-style:italic;">No saved teams yet — run a Moves & More scan in-game to populate.</div>';
                return;
            }
            listEl.innerHTML = r.teams.map(t => {
                if (t.error) {
                    return `<div class="ts-saved-card"><div class="head"><span style="color:#f85149;">${t.filename}: ${t.error}</span></div></div>`;
                }
                const monsHtml = (t.mons || []).map(m => {
                    const moves = (m.moves || []).filter(Boolean).map(mv =>
                        `<span class="move">${mv.replace(/-/g, ' ')}</span>`).join(' ');
                    const evs = (m.evs || []).map((v, i) => {
                        const labels = ['HP','Atk','Def','SpA','SpD','Spe'];
                        return v > 0 ? `<span class="nz">${labels[i]} ${v}</span>` : '';
                    }).filter(Boolean).join(' / ');
                    return `<div class="ts-saved-mon">
                        <div class="name">${(m.species || '?').replace(/-/g, ' ')}
                            ${m.nature ? `<span class="nature">${m.nature}</span>` : ''}
                        </div>
                        <div class="meta">
                            ${m.ability ? `<span class="ab">${m.ability.replace(/-/g, ' ')}</span>` : '<span style="color:#484f58;">no ability</span>'} /
                            ${m.item ? `<span class="it">${m.item.replace(/-/g, ' ')}</span>` : '<span style="color:#484f58;">no item</span>'}
                        </div>
                        <div class="moves">${moves || '<span style="color:#484f58;">no moves</span>'}</div>
                        ${evs ? `<div class="evs">${evs}</div>` : ''}
                    </div>`;
                }).join('');
                const date = t.mtime ? new Date(t.mtime * 1000).toLocaleString() : '';
                return `<div class="ts-saved-card">
                    <div class="head">
                        <span class="filename" title="${t.filename}">${t.filename}</span>
                        <span class="mtime">${date}</span>
                    </div>
                    <div class="grid">${monsHtml}</div>
                </div>`;
            }).join('');
        } catch (e) {
            listEl.innerHTML = `<div style="color:#f85149;">Error: ${e.message}</div>`;
        }
    }
    loadSavedTeams();
}
