// Live Trace view: polls /api/live-trace/recent, renders engine view + feed.
let liveTraceInited = false;
let liveTraceTimer = null;
let liveTraceSinceSeq = 0;
let liveTraceLastView = null;
let liveTraceEventCount = 0;
const LIVETRACE_FEED_MAX = 100;

async function liveTraceInit() {
    if (!liveTraceInited) {
        liveTraceInited = true;
    }
    if (liveTraceTimer) clearInterval(liveTraceTimer);
    liveTraceSinceSeq = 0;
    liveTraceLastView = null;
    liveTraceEventCount = 0;
    document.getElementById('livetrace-feed').innerHTML = '';
    document.getElementById('livetrace-own').innerHTML = '<div class="livetrace-slot">(no data yet)</div>';
    document.getElementById('livetrace-opp').innerHTML = '<div class="livetrace-slot">(no data yet)</div>';
    liveTracePoll();
    liveTraceTimer = setInterval(liveTracePoll, 1000);
}

async function liveTracePoll() {
    try {
        const r = await fetch(`/api/live-trace/recent?since=${liveTraceSinceSeq}&limit=100`);
        if (!r.ok) {
            liveTraceSetState('disconnected (HTTP ' + r.status + ')');
            return;
        }
        const data = await r.json();
        if (data.error) {
            liveTraceSetState('disconnected: ' + data.error);
            return;
        }
        liveTraceSetState('connected');
        document.getElementById('livetrace-head-seq').textContent = 'head_seq: ' + (data.head_seq ?? '-');
        const events = data.events || [];
        for (const ev of events) {
            liveTraceHandleEvent(ev);
            if (typeof ev.server_seq === 'number' && ev.server_seq > liveTraceSinceSeq) {
                liveTraceSinceSeq = ev.server_seq;
            }
        }
        // Status (last event age) — fetch separately, cheap.
        const sr = await fetch('/api/live-trace/status');
        if (sr.ok) {
            const s = await sr.json();
            const age = s.last_event_age_sec;
            document.getElementById('livetrace-last-age').textContent =
                age == null ? 'last event: -' : 'last event: ' + age.toFixed(1) + 's ago';
        }
    } catch (e) {
        liveTraceSetState('disconnected: ' + e.message);
    }
}

function liveTraceSetState(s) {
    document.getElementById('livetrace-conn-state').textContent = s;
}

function liveTraceHandleEvent(ev) {
    liveTraceEventCount++;
    document.getElementById('livetrace-event-count').textContent = 'events seen: ' + liveTraceEventCount;
    if (ev.type === 'engine_view' && ev.engine_view) {
        liveTraceLastView = ev.engine_view;
        liveTraceRenderView(ev.engine_view);
    }
    liveTraceAppendFeed(ev);
}

function liveTraceRenderView(view) {
    // Engine view is to_predict_json output: own_active[2], own_bench[N], opp_active[2], opp_bench[N], field
    const own = document.getElementById('livetrace-own');
    const opp = document.getElementById('livetrace-opp');
    own.innerHTML = '';
    opp.innerHTML = '';

    const renderSide = (containerEl, activeArr, benchArr) => {
        if (Array.isArray(activeArr)) {
            for (const slot of activeArr) {
                containerEl.appendChild(liveTraceSlotEl(slot, true));
            }
        }
        if (Array.isArray(benchArr)) {
            for (const slot of benchArr) {
                containerEl.appendChild(liveTraceSlotEl(slot, false));
            }
        }
    };

    renderSide(own, view.own_active, view.own_bench);
    renderSide(opp, view.opp_active, view.opp_bench);

    if (own.children.length === 0) own.innerHTML = '<div class="livetrace-slot">(empty)</div>';
    if (opp.children.length === 0) opp.innerHTML = '<div class="livetrace-slot">(empty)</div>';
}

function liveTraceSlotEl(slot, isActive) {
    const div = document.createElement('div');
    div.className = 'livetrace-slot' + (isActive ? ' active' : '');
    if (!slot || typeof slot !== 'object') {
        div.innerHTML = '<span class="livetrace-slot-species">(empty)</span>';
        return div;
    }
    //  Schema (BattleStateTracker::to_predict_json):
    //    species: string (slug, "" if unknown)
    //    hp: float 0..1
    //    alive: bool
    //    item, ability, status: string
    //    is_mega: bool
    //    moves: array of strings
    //    boosts: array of 6 ints
    if (slot.alive === false || slot.hp === 0) {
        div.classList.add('fainted');
    }
    const species = slot.species && slot.species.length > 0 ? slot.species : '(unknown)';
    const hpPct = (typeof slot.hp === 'number') ? Math.round(slot.hp * 100) + '%' : '';
    const parts = [];
    if (hpPct) parts.push(hpPct);
    if (slot.is_mega) parts.push('mega');
    if (slot.item) parts.push(slot.item);
    if (slot.ability) parts.push(slot.ability);
    if (slot.status) parts.push(slot.status);
    const moves = Array.isArray(slot.moves) ? slot.moves.filter(Boolean).join(', ') : '';
    div.innerHTML =
        '<div class="livetrace-slot-species">' + escapeHtml(species) + '</div>' +
        (parts.length ? '<div class="livetrace-slot-meta">' + escapeHtml(parts.join(' / ')) + '</div>' : '') +
        (moves ? '<div class="livetrace-slot-meta">' + escapeHtml(moves) + '</div>' : '');
    return div;
}

function liveTraceAppendFeed(ev) {
    const feed = document.getElementById('livetrace-feed');
    const row = document.createElement('div');
    row.className = 'livetrace-event-row';
    const ts = ev.server_ts_ms ? new Date(ev.server_ts_ms).toLocaleTimeString() : '-';
    row.innerHTML =
        '<span class="seq">#' + (ev.server_seq ?? '?') + '</span>' +
        '<span class="type">' + escapeHtml(ev.type || 'event') + '</span>' +
        '<span>' + escapeHtml(ts) + '</span>';
    feed.insertBefore(row, feed.firstChild);
    while (feed.children.length > LIVETRACE_FEED_MAX) {
        feed.removeChild(feed.lastChild);
    }
}

function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}
