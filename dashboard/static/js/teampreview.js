// ═══════════════════════════════════════════════════════════════
// Team Preview Examples
// Cropped opp sprites + matched atlas refs across labeled
// team_preview_locked_in / team_preview_selecting frames.
// ═══════════════════════════════════════════════════════════════
let tpExamplesInited = false;

async function teamPreviewInit() {
    if (tpExamplesInited) return;
    tpExamplesInited = true;

    try {
        const ex = await api('/api/sprites/examples');
        renderTpExamples(ex.examples || []);
    } catch (e) {
        document.getElementById('tp-examples').innerHTML =
            '<div style="color:#f85149;">Failed to load examples</div>';
    }
}

function renderTpExamples(examples) {
    const root = document.getElementById('tp-examples');
    if (!examples.length) {
        root.innerHTML = '<div style="color:#484f58; font-size:12px;">No labeled team-preview frames available</div>';
        return;
    }

    const renderSlots = (slots, sideLabel) => {
        if (!slots || !slots.length) return '';
        const pairs = slots.map((s, i) => {
            const cropImg = `<img src="${s.crop}" style="width:56px; height:56px; object-fit:contain; image-rendering:pixelated; display:block; background:#0d1117; border:1px solid #30363d; border-radius:3px;">`;
            const refImg = s.species
                ? `<img src="${API}/api/teampreview/sprite/${encodeURIComponent(s.species)}" style="width:56px; height:56px; image-rendering:pixelated; display:block; background:#0d1117; border:1px solid #30363d; border-radius:3px;">`
                : `<div style="width:56px; height:56px; background:#21262d; border:1px dashed #30363d; border-radius:3px;"></div>`;
            const arrow = `<div style="color:#484f58; font-size:12px; align-self:center;">&rarr;</div>`;
            return `<div style="display:flex; flex-direction:column; align-items:center; gap:3px;">
                <div style="display:flex; gap:4px; align-items:center;">${cropImg}${arrow}${refImg}</div>
                <div style="font-size:9px; color:${s.species ? '#8b949e' : '#484f58'};">${i+1}: ${s.species || '-'}</div>
            </div>`;
        }).join('');
        return `<div>
            <div style="font-size:10px; color:#8b949e; margin-bottom:4px; text-transform:uppercase; letter-spacing:0.05em;">${sideLabel}</div>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">${pairs}</div>
        </div>`;
    };

    root.innerHTML = examples.map(ex => {
        const frameUrl = `${API}/api/gallery/thumb/${encodeURIComponent(ex.screen)}/${encodeURIComponent(ex.filename)}`;
        return `<div style="background:#161b22; border:1px solid #30363d; border-radius:6px; padding:10px; margin-bottom:10px; display:grid; grid-template-columns:240px 1fr; gap:14px; align-items:start;">
            <div>
                <div style="font-size:10px; color:#8b949e; margin-bottom:4px;">${ex.screen}/${ex.filename}</div>
                <img src="${frameUrl}" style="width:100%; border-radius:3px; border:1px solid #30363d;">
            </div>
            <div style="display:flex; flex-direction:column; gap:14px;">
                ${renderSlots(ex.own_slots, 'My side (text OCR)')}
                ${renderSlots(ex.opp_slots, 'Opp side (sprite match)')}
            </div>
        </div>`;
    }).join('');
}
