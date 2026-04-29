// ═══════════════════════════════════════════════════════════════
// Model Review
// ═══════════════════════════════════════════════════════════════
let modelInited = false;

async function modelInit() {
    if (modelInited) return;
    modelInited = true;

    // Check model status
    const status = await api('/api/model/status');
    const msgEl = document.getElementById('model-status-msg');
    if (!status.has_checkpoint) {
        msgEl.style.display = 'block';
        msgEl.innerHTML = '<span style="color:#f85149;">No model checkpoint found.</span> Train a model first: <code>python -m vgc_model.training.train</code>';
        return;
    }
    if (!status.has_vocabs) {
        msgEl.style.display = 'block';
        msgEl.innerHTML = '<span style="color:#f85149;">No vocabulary files found.</span> Build vocabs first: <code>python scripts/build_vocab.py</code>';
        return;
    }
    if (status.loaded && status.checkpoint_info) {
        const ci = status.checkpoint_info;
        msgEl.style.display = 'block';
        msgEl.style.borderColor = '#238636';
        msgEl.innerHTML = `<span style="color:#3fb950;">Model loaded</span> &mdash; ${(ci.params||0).toLocaleString()} params` +
            (ci.val_top1 != null ? `, val top-1: ${ci.val_top1.toFixed(1)}%` : '') +
            (ci.val_top3 != null ? `, val top-3: ${ci.val_top3.toFixed(1)}%` : '') +
            (ci.epoch != null ? `, epoch ${ci.epoch}` : '');
    }

    // If cache already populated, load it
    if (status.cached_replays > 0) {
        await modelRefreshList();
        await modelRefreshSummary();
    }

    // Wire buttons
    document.getElementById('model-analyze-btn').addEventListener('click', modelRunAnalysis);
    document.getElementById('model-clear-btn').addEventListener('click', async () => {
        await apiPost('/api/model/clear', {});
        _review_cache_local = {};
        document.getElementById('model-replay-list').innerHTML = '';
        document.getElementById('model-replay-detail').innerHTML = '';
        await modelRefreshSummary();
    });
}

async function modelRunAnalysis() {
    const btn = document.getElementById('model-analyze-btn');
    const loading = document.getElementById('model-loading');
    const minRating = parseInt(document.getElementById('model-min-rating').value) || 0;
    const count = parseInt(document.getElementById('model-count').value) || 20;

    btn.disabled = true;
    loading.style.display = 'inline';
    loading.textContent = `Analyzing ${count} replays...`;

    try {
        const result = await api(`/api/model/analyze?count=${count}&min_rating=${minRating}`);
        if (result.error) {
            const msgEl = document.getElementById('model-status-msg');
            msgEl.style.display = 'block';
            msgEl.innerHTML = `<span style="color:#f85149;">Error: ${result.error}</span>`;
        } else {
            loading.textContent = `Done! ${result.analyzed} new, ${result.total_cached} total`;
            await modelRefreshList();
            await modelRefreshSummary();
        }
    } catch (e) {
        loading.textContent = `Error: ${e.message}`;
    }
    btn.disabled = false;
    setTimeout(() => { loading.style.display = 'none'; }, 3000);
}

async function modelRefreshSummary() {
    const s = await api('/api/model/summary');
    document.getElementById('model-replays-val').textContent = s.total_replays || '--';
    document.getElementById('model-acc-val').textContent = s.avg_accuracy ? s.avg_accuracy + '%' : '--';
    document.getElementById('model-acc-val').style.color = s.avg_accuracy >= 40 ? '#3fb950' : s.avg_accuracy >= 25 ? '#d29922' : '#f85149';
    document.getElementById('model-turns-val').textContent = s.total_turns || '--';
    document.getElementById('model-correct-val').textContent = s.total_actions ? `${s.total_matches} / ${s.total_actions}` : '--';
}

async function modelRefreshList() {
    const replays = await api('/api/model/replays');
    const list = document.getElementById('model-replay-list');
    if (!replays.length) {
        list.innerHTML = '<div style="padding:12px; color:#484f58; font-size:12px;">No replays analyzed yet</div>';
        return;
    }
    list.innerHTML = replays.map(r => {
        const accColor = r.accuracy >= 50 ? '#3fb950' : r.accuracy >= 30 ? '#d29922' : '#f85149';
        return `<div class="model-replay-item" data-id="${r.id}" style="padding:8px 12px; border-bottom:1px solid #21262d; cursor:pointer; font-size:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:#c9d1d9;">${(r.players||[]).join(' vs ')}</span>
                <span style="color:${accColor}; font-weight:600;">${r.accuracy}%</span>
            </div>
            <div style="color:#484f58; font-size:10px; margin-top:2px;">
                ${r.rating ? `Rating: ${r.rating}` : 'Unrated'} &middot; ${r.total_turns} turns &middot; Winner: ${r.winner}
            </div>
        </div>`;
    }).join('');

    list.querySelectorAll('.model-replay-item').forEach(el => {
        el.addEventListener('click', () => modelShowReplay(el.dataset.id));
        el.addEventListener('mouseenter', () => el.style.background = '#21262d');
        el.addEventListener('mouseleave', () => el.style.background = '');
    });
}

async function modelShowReplay(id) {
    const detail = document.getElementById('model-replay-detail');
    detail.innerHTML = '<div style="color:#484f58; padding:12px;">Loading...</div>';

    // Highlight selected
    document.querySelectorAll('.model-replay-item').forEach(el => {
        el.style.background = el.dataset.id === id ? '#1f6feb22' : '';
        el.style.borderLeft = el.dataset.id === id ? '3px solid #1f6feb' : '';
    });

    const data = await api(`/api/model/replay/${id}`);
    if (data.error) {
        detail.innerHTML = `<div style="color:#f85149; padding:12px;">${data.error}</div>`;
        return;
    }

    const header = `<div style="background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px 16px; margin-bottom:12px;">
        <div style="font-size:14px; font-weight:600; color:#c9d1d9;">${(data.players||[]).join(' vs ')}</div>
        <div style="font-size:11px; color:#8b949e; margin-top:4px;">
            ${data.rating ? `Rating: <span style="color:#58a6ff;">${data.rating}</span>` : 'Unrated'}
            &middot; Winner: <span style="color:#3fb950;">${data.winner}</span>
            &middot; Accuracy: <span style="color:${data.accuracy >= 50 ? '#3fb950' : data.accuracy >= 30 ? '#d29922' : '#f85149'}; font-weight:600;">${data.accuracy}%</span>
            &middot; ${data.matches}/${data.total_actions} correct
        </div>
    </div>`;

    const turnCards = data.turns.map(t => {
        const ownPokes = (t.own_active||[]).map(p =>
            `<span style="color:#c9d1d9;">${p.species}</span> <span style="color:${p.hp > 50 ? '#3fb950' : p.hp > 25 ? '#d29922' : '#f85149'};">${p.hp}%</span>${p.status ? ` <span style="color:#bc8cff; font-size:10px;">${p.status}</span>` : ''}`
        ).join(' &middot; ');
        const oppPokes = (t.opp_active||[]).map(p =>
            `<span style="color:#c9d1d9;">${p.species}</span> <span style="color:${p.hp > 50 ? '#3fb950' : p.hp > 25 ? '#d29922' : '#f85149'};">${p.hp}%</span>${p.status ? ` <span style="color:#bc8cff; font-size:10px;">${p.status}</span>` : ''}`
        ).join(' &middot; ');

        const bench = (t.own_bench||[]).map(p => p.species).join(', ');
        const field = (t.field||[]).length ? `<div style="margin-top:4px;"><span style="color:#d29922; font-size:10px;">${t.field.join(' | ')}</span></div>` : '';

        function slotHtml(slot, label) {
            if (!slot) return '';
            const match = slot.match;
            const border = match ? '#238636' : '#da3633';
            const badge = match
                ? '<span style="background:#238636; color:#fff; font-size:9px; padding:1px 5px; border-radius:3px; margin-left:6px;">MATCH</span>'
                : '<span style="background:#da3633; color:#fff; font-size:9px; padding:1px 5px; border-radius:3px; margin-left:6px;">MISS</span>';

            const preds = (slot.predictions||[]).map((p, i) => {
                const isMatch = p.idx === slot.actual_idx;
                return `<div style="display:flex; align-items:center; gap:8px; margin-top:3px;">
                    <span style="color:#484f58; font-size:10px; width:14px;">#${i+1}</span>
                    <div style="flex:1; background:#21262d; border-radius:3px; height:16px; position:relative; overflow:hidden;">
                        <div style="background:${isMatch ? '#238636' : '#30363d'}; height:100%; width:${Math.max(p.prob, 2)}%; border-radius:3px;"></div>
                        <span style="position:absolute; left:6px; top:0; line-height:16px; font-size:10px; color:${isMatch ? '#fff' : '#c9d1d9'};">${p.action}</span>
                        <span style="position:absolute; right:6px; top:0; line-height:16px; font-size:10px; color:#8b949e;">${p.prob}%</span>
                    </div>
                </div>`;
            }).join('');

            return `<div style="flex:1; min-width:0;">
                <div style="font-size:10px; color:#8b949e; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;">${label}${badge}</div>
                <div style="font-size:12px; color:#c9d1d9; margin-bottom:6px;">Actual: <span style="color:#58a6ff;">${slot.actual}</span></div>
                <div style="font-size:11px; color:#8b949e; margin-bottom:2px;">Predictions:</div>
                ${preds}
            </div>`;
        }

        return `<div style="background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px 16px; margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <span style="font-size:13px; font-weight:600; color:#c9d1d9;">Turn ${t.turn}</span>
                <span style="font-size:10px; color:#484f58;">${t.slot_a?.match && t.slot_b?.match ? '2/2' : t.slot_a?.match || t.slot_b?.match ? '1/2' : '0/2'} correct</span>
            </div>
            <div style="font-size:11px; margin-bottom:4px;">
                <span style="color:#8b949e;">Own:</span> ${ownPokes}
                ${bench ? `<span style="color:#484f58; margin-left:8px;">Bench: ${bench}</span>` : ''}
            </div>
            <div style="font-size:11px; margin-bottom:4px;">
                <span style="color:#8b949e;">Opp:</span> ${oppPokes}
            </div>
            ${field}
            <div style="display:flex; gap:16px; margin-top:10px; border-top:1px solid #21262d; padding-top:10px;">
                ${slotHtml(t.slot_a, 'Slot A')}
                ${slotHtml(t.slot_b, 'Slot B')}
            </div>
        </div>`;
    }).join('');

    detail.innerHTML = header + turnCards;
}

