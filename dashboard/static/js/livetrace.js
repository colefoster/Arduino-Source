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
    document.getElementById('lt-pipeline').innerHTML = '<div style="color:#8b949e;">(no data yet)</div>';
    document.getElementById('lt-own-team').innerHTML = '<div class="lt-slot">(no data yet)</div>';
    document.getElementById('lt-opp-team').innerHTML = '<div class="lt-slot">(no data yet)</div>';
    document.getElementById('lt-field').innerHTML = '(no data yet)';
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
        document.getElementById('lt-head').textContent = 'head_seq: ' + (data.head_seq != null ? data.head_seq : '-');
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
            document.getElementById('lt-age').textContent =
                age == null ? 'last event: -' : 'last event: ' + age.toFixed(1) + 's ago';
        }
        const dr = await fetch('/api/live-trace/derived-state');
        if (dr.ok) ltRenderDerivedState(await dr.json());
    } catch (e) {
        ltSetConn('disconnected: ' + e.message);
    }
}

function ltSetConn(s) {
    document.getElementById('lt-conn').textContent = s;
}

function ltHandleEvent(ev) {
    liveTraceEventCount++;
    document.getElementById('lt-events').textContent = 'events seen: ' + liveTraceEventCount;
    liveTraceLastEvent = ev;
    if (ev.current_screen) {
        const pill = document.getElementById('lt-screen');
        pill.textContent = 'screen: ' + ev.current_screen;
        pill.className = 'lt-pill screen-' + ev.current_screen;
    }
    if (ev.battle_mode) document.getElementById('lt-mode').textContent = 'mode: ' + ev.battle_mode;
    if (typeof ev.match_in_progress === 'boolean') {
        document.getElementById('lt-match').textContent = 'match: ' + (ev.match_in_progress ? 'in progress' : 'idle');
    }
    if (ev.pipeline) ltRenderPipeline(ev.pipeline);
    if (ev.engine_view) ltRenderEngineView(ev.engine_view, ev.pipeline || {});
    ltAppendFeed(ev);
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
        header.style.cssText = 'color:#6e7681; font-size:10px; text-transform:uppercase; letter-spacing:0.5px; margin:8px 0 4px 0;';
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
    const own = document.getElementById('lt-own-team');
    const opp = document.getElementById('lt-opp-team');
    own.innerHTML = '';
    opp.innerHTML = '';

    // Pokeballs from PokeballAliveDetector last_output if present
    const pb = pipeline.PokeballAliveDetector && pipeline.PokeballAliveDetector.last_output;
    ltRenderPokeballs('lt-own-pokeballs', pb && pb.own);
    ltRenderPokeballs('lt-opp-pokeballs', pb && pb.opp);

    // Active mons + bench
    const ownActiveLabel = document.createElement('div');
    ownActiveLabel.className = 'lt-slot-label';
    ownActiveLabel.textContent = 'Active';
    own.appendChild(ownActiveLabel);
    if (Array.isArray(view.own_active)) {
        for (const slot of view.own_active) own.appendChild(ltSlotEl(slot, true));
    }
    const ownBenchLabel = document.createElement('div');
    ownBenchLabel.className = 'lt-slot-label';
    ownBenchLabel.textContent = 'Bench';
    own.appendChild(ownBenchLabel);
    if (Array.isArray(view.own_bench)) {
        for (const slot of view.own_bench) own.appendChild(ltSlotEl(slot, false));
    }

    const oppActiveLabel = document.createElement('div');
    oppActiveLabel.className = 'lt-slot-label';
    oppActiveLabel.textContent = 'Active';
    opp.appendChild(oppActiveLabel);
    if (Array.isArray(view.opp_active)) {
        for (const slot of view.opp_active) opp.appendChild(ltSlotEl(slot, true));
    }
    const oppBenchLabel = document.createElement('div');
    oppBenchLabel.className = 'lt-slot-label';
    oppBenchLabel.textContent = 'Bench';
    opp.appendChild(oppBenchLabel);
    if (Array.isArray(view.opp_bench)) {
        for (const slot of view.opp_bench) opp.appendChild(ltSlotEl(slot, false));
    }

    // Field state
    if (view.field) ltRenderField(view.field);
}

function ltRenderPokeballs(elId, arr) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = '';
    if (!Array.isArray(arr)) {
        for (let i = 0; i < 6; i++) {
            const p = document.createElement('div');
            p.className = 'lt-pokeball EMPTY';
            p.title = 'unknown';
            el.appendChild(p);
        }
        return;
    }
    for (const state of arr) {
        const p = document.createElement('div');
        p.className = 'lt-pokeball ' + (state || 'EMPTY');
        p.title = state || 'EMPTY';
        el.appendChild(p);
    }
}

function ltSlotEl(slot, isActive) {
    const div = document.createElement('div');
    div.className = 'lt-slot' + (isActive ? ' active' : '');
    if (!slot || typeof slot !== 'object') {
        div.innerHTML = '<span class="species">(empty)</span>';
        return div;
    }
    if (slot.alive === false || slot.hp === 0) div.classList.add('fainted');
    const species = (slot.species && slot.species.length > 0) ? slot.species : '(unknown)';
    const hpPct = (typeof slot.hp === 'number') ? Math.round(slot.hp * 100) + '%' : '';
    const meta = [];
    if (hpPct) meta.push(hpPct);
    if (slot.is_mega) meta.push('mega');
    if (slot.item) meta.push(slot.item);
    if (slot.ability) meta.push(slot.ability);
    if (slot.status) meta.push(slot.status);
    const moves = Array.isArray(slot.moves) ? slot.moves.filter(Boolean) : [];

    let html = '<div class="species">' + ltEsc(species) + '</div>';
    if (meta.length) html += '<div class="meta">' + ltEsc(meta.join(' / ')) + '</div>';
    if (moves.length) html += '<div class="meta">' + ltEsc(moves.join(', ')) + '</div>';
    else html += '<div class="wip">moves: missing (provide via OWN_TEAM_PASTE for own side; opp moves WIP)</div>';
    if (!slot.ability) html += '<div class="wip">ability: missing (own=paste, opp=WIP AbilityRevealReader)</div>';
    if (!slot.item && species !== '(unknown)') html += '<div class="wip">item: missing (own=paste, opp=WIP ItemRevealReader)</div>';
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
    const rows = [
        { k: 'turn', v: f.turn, set: f.turn > 0, isWip: false },
        { k: 'weather', v: f.weather || '-', set: !!f.weather, isWip: !f.weather },
        { k: 'terrain', v: f.terrain || '-', set: !!f.terrain, isWip: !f.terrain },
        { k: 'trick_room', v: f.trick_room ? 'on' : 'off', set: f.trick_room, isWip: false },
        { k: 'tailwind_own', v: f.tailwind_own ? 'on' : 'off', set: f.tailwind_own, isWip: false },
        { k: 'tailwind_opp', v: f.tailwind_opp ? 'on' : 'off', set: f.tailwind_opp, isWip: false },
        { k: 'screens_own', v: ltScreenSummary(f.screens_own), set: ltAnyTrue(f.screens_own), isWip: false },
        { k: 'screens_opp', v: ltScreenSummary(f.screens_opp), set: ltAnyTrue(f.screens_opp), isWip: false },
    ];
    for (const r of rows) {
        const span = document.createElement('span');
        span.className = 'lt-field-row';
        span.innerHTML = '<span class="key">' + ltEsc(r.k) + '=</span><span class="val ' + (r.set ? 'set' : 'unset') + '">' + ltEsc(String(r.v)) + '</span>';
        el.appendChild(span);
    }
    const note = document.createElement('div');
    note.style.cssText = 'color:#f85149; font-size:10px; margin-top:8px;';
    note.textContent = 'Field state is read from BattleLogReader (weather/terrain/trick_room). Tailwind/screens still have no detector and stay unset.';
    el.appendChild(note);
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
        '<span>' + ltEsc(ts) + '</span>';
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
