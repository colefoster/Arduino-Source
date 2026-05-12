// Live Trace view: polls /api/live-trace/recent, renders pipeline + engine view + feed.
let liveTraceInited = false;
let liveTraceTimer = null;
let liveTraceSinceSeq = 0;
let liveTraceLastEvent = null;
let liveTraceEventCount = 0;
let liveTraceExpandedRows = new Set();
const LIVETRACE_FEED_MAX = 80;

const PIPELINE_GROUPS = [
    { title: 'Screen Detectors', filter: e => e.category === 'detector' && (
        e.name.endsWith('Detector') && [
            'TeamPreviewDetector','PreparingForBattleDetector','ActionMenuDetector',
            'MoveSelectDetector','ResultScreenDetector','PostMatchScreenDetector',
            'MainMenuDetector','ActiveHUDSlotDetector'
        ].includes(e.name)) },
    { title: 'Wired Readers', filter: e => e.category === 'reader' && e.status !== 'wip' && e.status !== 'n/a' },
    { title: 'WIP / Unavailable', filter: e => e.status === 'wip' || e.status === 'n/a' },
];

async function liveTraceInit() {
    if (!liveTraceInited) {
        liveTraceInited = true;
    }
    if (liveTraceTimer) clearInterval(liveTraceTimer);
    liveTraceSinceSeq = 0;
    liveTraceLastEvent = null;
    liveTraceEventCount = 0;
    liveTraceExpandedRows = new Set();
    document.getElementById('livetrace-feed').innerHTML = '';
    document.getElementById('lt-pipeline').innerHTML = '<div style="color:#6e7681; font-size:11px; font-style:italic;">no data yet</div>';
    document.getElementById('lt-own-team').innerHTML = '<div style="color:#6e7681; font-size:11px; font-style:italic;">no data yet</div>';
    document.getElementById('lt-opp-team').innerHTML = '<div style="color:#6e7681; font-size:11px; font-style:italic;">no data yet</div>';
    document.getElementById('lt-bs-own-active-row').innerHTML = '';
    document.getElementById('lt-bs-opp-active-row').innerHTML = '';
    document.getElementById('lt-field').innerHTML = '<span style="color:#6e7681; font-size:11px; font-style:italic;">no data yet</span>';
    document.getElementById('lt-snapshot').innerHTML = '<span style="color:#6e7681; font-size:11px; font-style:italic;">no data yet</span>';
    liveTracePoll();
    liveTraceTimer = setInterval(liveTracePoll, 1000);
}

async function liveTracePoll() {
    try {
        const r = await fetch('/api/live-trace/recent?since=' + liveTraceSinceSeq + '&limit=20');
        if (!r.ok) {
            ltSetConn('disconnected (HTTP ' + r.status + ')');
            return;
        }
        const data = await r.json();
        if (data.error) {
            ltSetConn('disconnected: ' + data.error);
            return;
        }
        ltSetConn('connected');
        const events = data.events || [];
        for (const ev of events) {
            ltHandleEvent(ev);
            if (typeof ev.server_seq === 'number' && ev.server_seq > liveTraceSinceSeq) {
                liveTraceSinceSeq = ev.server_seq;
            }
        }
        const sr = await fetch('/api/live-trace/status');
        if (sr.ok) {
            const s = await sr.json();
            const age = s.last_event_age_sec;
            document.getElementById('lt-age').textContent = age == null ? '-' : age.toFixed(1) + 's';
        }
        document.getElementById('lt-head').textContent = data.head_seq != null ? data.head_seq : '-';
        const dr = await fetch('/api/live-trace/derived-state');
        if (dr.ok) ltRenderDerivedState(await dr.json());
    } catch (e) {
        ltSetConn('disconnected: ' + e.message);
    }
}

function ltSetConn(s) {
    const el = document.getElementById('lt-conn');
    el.textContent = s;
    el.className = s === 'connected' ? 'lt-conn-connected' : 'lt-conn-disconnected';
}

function ltHandleEvent(ev) {
    liveTraceEventCount++;
    document.getElementById('lt-events').textContent = liveTraceEventCount;
    liveTraceLastEvent = ev;
    if (ev.current_screen) {
        const pill = document.getElementById('lt-screen');
        pill.textContent = ev.current_screen;
        pill.className = 'lt-screen-pill lt-pill-big screen-' + ev.current_screen;
    }
    if (ev.battle_mode) document.getElementById('lt-mode').textContent = ev.battle_mode;
    if (typeof ev.match_in_progress === 'boolean') {
        document.getElementById('lt-match').textContent = ev.match_in_progress ? 'in progress' : 'idle';
    }
    if (ev.pipeline) ltRenderPipeline(ev.pipeline);
    if (ev.engine_view) ltRenderEngineView(ev.engine_view, ev.pipeline || {});
    if (ev.snapshot) ltRenderSnapshot(ev.snapshot, ev.engine_view || {});
    ltRenderSuggestion(ev.suggested_input);
    ltAppendFeed(ev);
}

function ltRenderSuggestion(s) {
    const el = document.getElementById('lt-suggest');
    if (!el) return;
    if (!s || !s.button) {
        el.hidden = true;
        el.innerHTML = '';
        return;
    }
    const label = s.label || (s.button + ' — ?');
    const reason = s.reason ? `<span class="lt-suggest-reason">${s.reason}</span>` : '';
    el.innerHTML = `▶ ${label}${reason}`;
    el.hidden = false;
}

function ltRenderPipeline(pipeline) {
    const container = document.getElementById('lt-pipeline');
    container.innerHTML = '';
    const entries = Object.entries(pipeline)
        .map(([name, info]) => Object.assign({ name }, info))
        .sort((a, b) => a.name.localeCompare(b.name));

    for (const group of PIPELINE_GROUPS) {
        const matched = entries.filter(group.filter);
        if (matched.length === 0) continue;
        const header = document.createElement('div');
        header.className = 'lt-pipe-group-head';
        header.textContent = group.title + ' (' + matched.length + ')';
        container.appendChild(header);
        for (const e of matched) {
            container.appendChild(ltPipelineRowEl(e));
        }
    }
}

function ltPipelineRowEl(e) {
    const row = document.createElement('div');
    row.className = 'lt-pipe-row' + (liveTraceExpandedRows.has(e.name) ? ' expanded' : '');
    const dotCls = ltStatusDotClass(e.status);
    const ageStr = ltAgeStr(e.last_fire_ms_ago);
    row.innerHTML =
        '<span class="lt-dot ' + dotCls + '"></span>' +
        '<span class="name">' + ltEsc(e.name) + ' <span class="cat">' + ltEsc(e.category || '') + '</span></span>' +
        '<span class="status">' + ltEsc(e.status) + '</span>' +
        '<span class="age">' + ltEsc(ageStr) + '</span>';
    if (e.note || e.last_output) {
        const detail = document.createElement('div');
        detail.className = 'detail';
        let txt = '';
        if (e.note) txt += e.note + '\n';
        if (e.last_output) txt += '\nlast_output: ' + JSON.stringify(e.last_output, null, 2);
        detail.textContent = txt.trim();
        row.appendChild(detail);
        row.style.cursor = 'pointer';
        row.onclick = () => {
            if (liveTraceExpandedRows.has(e.name)) {
                liveTraceExpandedRows.delete(e.name);
                row.classList.remove('expanded');
            } else {
                liveTraceExpandedRows.add(e.name);
                row.classList.add('expanded');
            }
        };
    }
    return row;
}

function ltStatusDotClass(status) {
    switch (status) {
        case 'ok': return 'lt-ok';
        case 'stale': return 'lt-stale';
        case 'skipped': return 'lt-skipped';
        case 'wip': return 'lt-wip';
        case 'n/a': return 'lt-na';
        case 'error': return 'lt-error';
        default: return 'lt-skipped';
    }
}

function ltAgeStr(msAgo) {
    if (msAgo == null || msAgo < 0) return '-';
    if (msAgo < 1000) return msAgo + 'ms';
    if (msAgo < 60000) return (msAgo / 1000).toFixed(1) + 's';
    return Math.floor(msAgo / 60000) + 'm';
}

function ltRenderEngineView(view, pipeline) {
    const ownBench = document.getElementById('lt-own-team');
    const oppBench = document.getElementById('lt-opp-team');
    const ownActive = document.getElementById('lt-bs-own-active-row');
    const oppActive = document.getElementById('lt-bs-opp-active-row');

    // Pokeballs (active ring matches the currently-active slot indices).
    const pb = pipeline.PokeballAliveDetector && pipeline.PokeballAliveDetector.last_output;
    const ownActiveIdx = ltActiveIndices(view.own_active, pb && pb.own);
    const oppActiveIdx = ltActiveIndices(view.opp_active, pb && pb.opp);
    ltRenderPokeballs('lt-own-pokeballs', pb && pb.own, ownActiveIdx);
    ltRenderPokeballs('lt-opp-pokeballs', pb && pb.opp, oppActiveIdx);

    const isDoubles = Array.isArray(view.own_active) && view.own_active.length > 1
                   || Array.isArray(view.opp_active) && view.opp_active.length > 1;

    // Active goes inside the Battle State hero card.
    ownActive.innerHTML = '';
    oppActive.innerHTML = '';
    ownActive.className = 'lt-bs-active-row' + (isDoubles ? '' : ' singles');
    oppActive.className = 'lt-bs-active-row' + (isDoubles ? '' : ' singles');
    if (Array.isArray(view.own_active)) {
        view.own_active.forEach((slot, i) => ownActive.appendChild(ltSlotEl(slot, true, isDoubles ? i : null)));
    }
    if (Array.isArray(view.opp_active)) {
        view.opp_active.forEach((slot, i) => oppActive.appendChild(ltSlotEl(slot, true, isDoubles ? i : null)));
    }

    // Bench goes in its dedicated columns.
    ownBench.innerHTML = '';
    oppBench.innerHTML = '';
    if (Array.isArray(view.own_bench) && view.own_bench.length) {
        for (const slot of view.own_bench) ownBench.appendChild(ltSlotEl(slot, false, null));
    } else {
        ownBench.innerHTML = '<div style="color:#6e7681; font-size:11px; font-style:italic;">no bench data</div>';
    }
    if (Array.isArray(view.opp_bench) && view.opp_bench.length) {
        for (const slot of view.opp_bench) oppBench.appendChild(ltSlotEl(slot, false, null));
    } else {
        oppBench.innerHTML = '<div style="color:#6e7681; font-size:11px; font-style:italic;">no bench data</div>';
    }

    // Leads row + turn pill.
    ltRenderLeads(view);
    const turnEl = document.getElementById('lt-bs-turn');
    if (view.field && typeof view.field.turn === 'number') {
        turnEl.textContent = view.field.turn > 0 ? `turn ${view.field.turn}` : '';
    } else {
        turnEl.textContent = '';
    }

    if (view.field) ltRenderField(view.field);
}

function _bsName(slot) {
    if (!slot) return '?';
    const sp = (slot.species || '').replace(/-/g, ' ');
    if (!sp || sp === '(unknown)') return '?';
    return sp.replace(/\b\w/g, c => c.toUpperCase());
}

function ltRenderLeads(view) {
    const leadsRow = document.getElementById('lt-bs-leads-row');
    const leads = Array.isArray(view.own_leads) ? view.own_leads : [];
    if (leads.length === 0) {
        leadsRow.innerHTML = '<span class="lt-leads-empty">leads not yet read</span>';
        return;
    }
    const byIdx = {};
    const collect = (arr) => Array.isArray(arr) && arr.forEach(s => {
        if (s && typeof s.slot === 'number') byIdx[s.slot] = s;
    });
    collect(view.own_active); collect(view.own_bench);
    leadsRow.innerHTML = leads.map((slotIdx, i) => {
        const name = _bsName(byIdx[slotIdx]) || `slot ${slotIdx}`;
        return `<span class="lt-lead-pill"><span class="order">${i + 1}</span>${ltEsc(name)}</span>`;
    }).join('');
}

function ltRenderPokeballs(elId, arr, activeIdx) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = '';
    const active = new Set(Array.isArray(activeIdx) ? activeIdx : []);
    if (!Array.isArray(arr)) {
        for (let i = 0; i < 6; i++) {
            const p = document.createElement('div');
            p.className = 'lt-pokeball EMPTY' + (active.has(i) ? ' active' : '');
            p.title = 'unknown';
            el.appendChild(p);
        }
        return;
    }
    arr.forEach((state, i) => {
        const p = document.createElement('div');
        p.className = 'lt-pokeball ' + (state || 'EMPTY') + (active.has(i) ? ' active' : '');
        p.title = (state || 'EMPTY') + (active.has(i) ? ' (active slot ' + i + ')' : '');
        el.appendChild(p);
    });
}

// Best-effort: figure out which roster indices the two active mons occupy.
// Backend doesn't echo the slot indices today, so fall back to the first N
// non-fainted positions in the pokeball array (N = active.length).
function ltActiveIndices(activeArr, pbArr) {
    const n = Array.isArray(activeArr) ? activeArr.length : 0;
    if (n === 0) return [];
    if (!Array.isArray(pbArr)) return Array.from({ length: n }, (_, i) => i);
    const out = [];
    for (let i = 0; i < pbArr.length && out.length < n; i++) {
        if (pbArr[i] === 'alive' || pbArr[i] === 'alive_statused' ||
            pbArr[i] === 'ALIVE') {
            out.push(i);
        }
    }
    while (out.length < n) out.push(out.length);
    return out;
}

function ltSlotEl(slot, isActive, slotIdx) {
    const div = document.createElement('div');
    div.className = 'lt-slot' + (isActive ? ' active' : '');
    const idxPill = (slotIdx != null) ? `<span class="slot-idx">${slotIdx}</span>` : '';
    if (!slot || typeof slot !== 'object') {
        div.innerHTML = `<div class="row1"><span class="species">${idxPill}(empty)</span></div>`;
        return div;
    }
    if (slot.alive === false || slot.hp === 0) div.classList.add('fainted');
    const speciesRaw = (slot.species && slot.species.length > 0) ? slot.species : '(unknown)';
    const isUnknown = speciesRaw === '(unknown)';
    const species = isUnknown ? '(unknown)' : speciesRaw.replace(/-/g, ' ');

    // Row 1: idx + name + status/mega pills
    const pills = [];
    if (slot.status) pills.push(`<span class="status-pill ${ltEsc(slot.status)}">${ltEsc(slot.status)}</span>`);
    if (slot.is_mega) pills.push(`<span class="mega-pill">mega</span>`);
    let html = `<div class="row1">
        <span class="species">${idxPill}${ltEsc(species)}</span>
        <span style="display:flex; gap:4px;">${pills.join('')}</span>
    </div>`;

    // HP bar — skipped for unknown placeholder (placeholder has hp=1.0 by default).
    if (!isUnknown && typeof slot.hp === 'number') {
        const pct = Math.max(0, Math.min(1, slot.hp));
        const cls = pct > 0.5 ? 'high' : pct > 0.2 ? 'mid' : 'low';
        html += `<div class="lt-hp">
            <div class="bar"><div class="fill ${cls}" style="width:${(pct*100).toFixed(0)}%"></div></div>
            <span class="pct">${(pct*100).toFixed(0)}%</span>
        </div>`;
    }

    // Ability + item (compact, dim if missing)
    if (!isUnknown) {
        const abK = slot.ability ? '' : 'miss';
        const itK = slot.item ? '' : 'miss';
        const ab = slot.ability ? slot.ability.replace(/-/g, ' ') : 'unknown';
        const it = slot.item ? slot.item.replace(/-/g, ' ') : 'unknown';
        html += `<div class="lt-ai">
            <span class="kv ${abK}"><span class="k">A</span><span class="v">${ltEsc(ab)}</span></span>
            <span class="kv ${itK}"><span class="k">I</span><span class="v">${ltEsc(it)}</span></span>
        </div>`;
    }

    // Boost chips: only render non-zero stages.
    if (!isUnknown && Array.isArray(slot.boosts)) {
        const STAT_LABELS = ['atk','def','spa','spd','spe','eva'];
        const chips = slot.boosts
            .map((v, i) => ({ v, label: STAT_LABELS[i] }))
            .filter(b => b.v !== 0)
            .map(b => {
                const sign = b.v > 0 ? '+' : '';
                const cls = b.v > 0 ? 'up' : 'down';
                return `<span class="lt-boost ${cls}">${b.label} ${sign}${b.v}</span>`;
            });
        if (chips.length) {
            html += `<div class="lt-boosts">${chips.join('')}</div>`;
        }
    }

    // Moves (4 chips, 2x2). Active mons get the full grid; bench shows them too if known.
    const moves = Array.isArray(slot.moves) ? slot.moves.filter(Boolean) : [];
    const movePp = Array.isArray(slot.move_pp) ? slot.move_pp : [];
    if (isUnknown) {
        html += `<div style="color:#6e7681; font-size:10px; font-style:italic;">waiting for HUD read…</div>`;
    } else if (isActive || moves.length) {
        const cells = [];
        for (let i = 0; i < 4; i++) {
            const m = moves[i];
            const pp = movePp[i];                   //  [current, max] or null
            const ppSuffix = (Array.isArray(pp) && pp.length === 2)
                ? `<span class="pp">${pp[0]}/${pp[1]}</span>` : '';
            cells.push(m
                ? `<span class="move">${ltEsc(m.replace(/-/g, ' '))}${ppSuffix}</span>`
                : `<span class="move miss">—</span>`);
        }
        html += `<div class="lt-moves">${cells.join('')}</div>`;
    }

    div.innerHTML = html;
    return div;
}

function ltRenderDerivedState(s) {
    const el = document.getElementById('lt-derived');
    const st = document.getElementById('lt-derived-status');
    if (!s || !s.in_match) {
        el.textContent = '(no match in progress)';
        st.textContent = s && s.last_seq_seen ? `last_seq_seen: ${s.last_seq_seen}` : '';
        return;
    }
    st.textContent = `match #${s.match_id} | turn ${s.turn} | last_seq ${s.last_seq}`;
    const pillFor = (state) => {
        const color = state === 'alive'          ? '#3fb950'
                    : state === 'alive_statused' ? '#d97706'
                    : state === 'fainted'        ? '#f85149'
                    :                              '#30363d';
        return `<span style="display:inline-block;width:14px;height:14px;border-radius:50%;margin:0 2px;vertical-align:middle;background:${color};" title="${state}"></span>`;
    };
    const ownPills = (s.own || []).map(pillFor).join('');
    const oppPills = (s.opp || []).map(pillFor).join('');
    let html = '';
    html += `<div><span style="color:#6e7681;">own:</span> ${ownPills} <span style="color:#3fb950;">${s.own_alive_count}</span> alive</div>`;
    html += `<div style="margin-top:4px;"><span style="color:#6e7681;">opp:</span> ${oppPills} <span style="color:#f85149;">${s.opp_alive_count}</span> alive</div>`;
    if (s.faints && s.faints.length) {
        const list = s.faints.slice(-6).map(f =>
            `<span style="color:${f.side === 'own' ? '#f85149' : '#3fb950'};">${f.side}[${f.slot}]</span>`
        ).join(', ');
        html += `<div style="margin-top:8px; color:#6e7681;">faints (${s.faint_count}): ${list}</div>`;
    }
    el.innerHTML = html;
}

function ltRenderField(f) {
    const el = document.getElementById('lt-field');
    el.innerHTML = '';
    //  Tailwind + screens have no detector yet — flag as 'wip' (yellow) rather
    //  than just 'unset' so it's visually distinct from "off but tracked."
    const rows = [
        { k: 'turn',         v: f.turn || 0,                          set: f.turn > 0 },
        { k: 'weather',      v: f.weather || 'none',                  set: !!f.weather },
        { k: 'terrain',      v: f.terrain || 'none',                  set: !!f.terrain },
        { k: 'trick room',   v: f.trick_room ? 'on' : 'off',          set: f.trick_room },
        { k: 'tailwind own', v: f.tailwind_own ? 'on' : 'off',        set: f.tailwind_own, wip: true },
        { k: 'tailwind opp', v: f.tailwind_opp ? 'on' : 'off',        set: f.tailwind_opp, wip: true },
        { k: 'screens own',  v: ltScreenSummary(f.screens_own),       set: ltAnyTrue(f.screens_own), wip: true },
        { k: 'screens opp',  v: ltScreenSummary(f.screens_opp),       set: ltAnyTrue(f.screens_opp), wip: true },
    ];
    for (const r of rows) {
        const span = document.createElement('span');
        let cls = 'lt-field-pill';
        if (r.set) cls += ' set';
        else if (r.wip) cls += ' wip';
        span.className = cls;
        span.innerHTML = `<span class="k">${ltEsc(r.k)}</span><span class="v">${ltEsc(String(r.v))}</span>`;
        if (r.wip && !r.set) span.title = 'WIP: no detector yet — value not tracked';
        el.appendChild(span);
    }
}

//  BattleSnapshot renderer — surfaces the raw tracker snapshot. Engine_view
//  already shows the pretty version (sprites, names); this card is a
//  diagnostic strip for confirming the underlying indices and bitmaps the
//  C++ tracker is actually publishing each poll. Useful when reasoning
//  about active-slot bugs (was m_own_active correctly remapped?).
function ltRenderSnapshot(snap, view) {
    const el = document.getElementById('lt-snapshot');
    if (!snap) {
        el.innerHTML = '<span style="color:#6e7681; font-size:11px; font-style:italic;">no snapshot yet</span>';
        return;
    }

    //  Try to label each active slot with its species from engine_view.
    //  view.own_team / view.opp_team are arrays of mons indexed 0..5.
    const ownTeam = Array.isArray(view.own_team) ? view.own_team : [];
    const oppTeam = Array.isArray(view.opp_team) ? view.opp_team : [];
    const speciesAt = (team, idx) => {
        if (idx == null || idx < 0) return null;
        const mon = team[idx];
        if (!mon) return null;
        return mon.species || mon.name || null;
    };

    //  Use the snapshot's explicit mode field instead of inferring from
    //  slot[1] < 0 — the C++ snapshot() builder forces slot[1] = -1 in
    //  any non-DOUBLES state (including UNKNOWN), so the old inference
    //  rendered doubles as singles on every poll before
    //  BattleModeDetector fired on team_preview.
    const mode = (snap.mode || 'Unknown').toLowerCase();
    const slotsToShow = (mode === 'singles') ? 1 : 2;

    const activeRow = (label, slots, team) => {
        const safe = slots || [-1, -1];
        const cells = [];
        for (let i = 0; i < slotsToShow; i++) {
            const idx = safe[i];
            const sp = speciesAt(team, idx);
            const idxStr = (idx == null || idx < 0) ? '—' : String(idx);
            const spStr = sp ? `<span style="color:#c9d1d9;">${ltEsc(sp)}</span>` : '<span style="color:#6e7681;">unknown</span>';
            cells.push(`<span class="lt-snap-cell"><span class="k">slot ${i}</span><span class="v">[${idxStr}] ${spStr}</span></span>`);
        }
        return `<div class="lt-snap-row"><span class="lt-snap-label">${label}</span>${cells.join('')}</div>`;
    };

    const aliveDots = (arr) => {
        if (!Array.isArray(arr)) return '—';
        return arr.map((alive, i) =>
            `<span class="lt-snap-dot ${alive ? 'alive' : 'down'}" title="slot ${i}: ${alive ? 'alive' : 'down/empty'}">${alive ? '●' : '○'}</span>`
        ).join('');
    };

    let html = '';
    html += activeRow('own active', snap.own_active_slots, ownTeam);
    html += activeRow('opp active', snap.opp_active_slots, oppTeam);
    html += `<div class="lt-snap-row"><span class="lt-snap-label">own alive</span><span class="lt-snap-dots">${aliveDots(snap.own_alive)}</span></div>`;
    html += `<div class="lt-snap-row"><span class="lt-snap-label">opp alive</span><span class="lt-snap-dots">${aliveDots(snap.opp_alive)}</span></div>`;

    //  Field state — duplicated from the Field card on purpose, so this
    //  card is a self-contained read of what BattleStateTracker reported.
    //  Compact one-liner.
    const fieldBits = [];
    if (snap.weather)      fieldBits.push(`weather=${snap.weather}`);
    if (snap.terrain)      fieldBits.push(`terrain=${snap.terrain}`);
    if (snap.trick_room)   fieldBits.push(`trick_room`);
    if (snap.tailwind_own) fieldBits.push(`tailwind_own`);
    if (snap.tailwind_opp) fieldBits.push(`tailwind_opp`);
    if (ltAnyTrue(snap.screens_own)) fieldBits.push(`screens_own=${ltScreenSummary(snap.screens_own)}`);
    if (ltAnyTrue(snap.screens_opp)) fieldBits.push(`screens_opp=${ltScreenSummary(snap.screens_opp)}`);
    if (typeof snap.turn === 'number' && snap.turn > 0) fieldBits.push(`turn=${snap.turn}`);
    const fieldStr = fieldBits.length ? fieldBits.join(' · ') : '<span style="color:#6e7681;">no field effects</span>';
    html += `<div class="lt-snap-row"><span class="lt-snap-label">field</span><span class="lt-snap-field">${fieldStr}</span></div>`;

    el.innerHTML = html;
}

function ltScreenSummary(arr) {
    if (!Array.isArray(arr)) return '-';
    const labels = ['light', 'reflect', 'aurora'];
    const on = arr.map((v, i) => v ? labels[i] : null).filter(Boolean);
    return on.length ? on.join(',') : 'none';
}

function ltAnyTrue(arr) { return Array.isArray(arr) && arr.some(Boolean); }

function ltAppendFeed(ev) {
    const feed = document.getElementById('livetrace-feed');
    const row = document.createElement('div');
    row.className = 'lt-event-row';
    const ts = ev.server_ts_ms ? new Date(ev.server_ts_ms).toLocaleTimeString() : '-';
    row.innerHTML =
        '<span class="seq">#' + (ev.server_seq != null ? ev.server_seq : '?') + '</span>' +
        '<span class="scr">' + ltEsc(ev.current_screen || '-') + '</span>' +
        '<span class="ts">' + ltEsc(ts) + '</span>';
    feed.insertBefore(row, feed.firstChild);
    while (feed.children.length > LIVETRACE_FEED_MAX) {
        feed.removeChild(feed.lastChild);
    }
}

function ltEsc(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}
