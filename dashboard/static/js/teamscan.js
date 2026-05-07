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

    function renderSlot(slot) {
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
        `;
        return div;
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
            (r.slots || []).forEach(slot => slotsEl.appendChild(renderSlot(slot)));
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
