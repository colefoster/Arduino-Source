// ═══════════════════════════════════════════════════════════════
// Digit Templates
// ═══════════════════════════════════════════════════════════════

let templatesInited = false;

async function templatesInit() {
    if (templatesInited) return;
    templatesInited = true;
    await loadTemplates();
}

async function loadTemplates() {
    const grid = document.getElementById('templates-grid');
    grid.innerHTML = '<div style="color:#8b949e;">Loading...</div>';
    try {
        const data = await api('/api/templates/list');
        grid.innerHTML = '';
        if (data.templates.length === 0) {
            grid.innerHTML = '<div style="color:#8b949e;">No digit templates found.</div>';
            return;
        }
        data.templates.forEach(t => {
            const card = document.createElement('div');
            card.style.cssText = 'background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; text-align:center; min-width:100px;';
            card.innerHTML = `
                <div style="font-size:24px; font-weight:bold; color:#58a6ff; margin-bottom:8px;">${t.digit}</div>
                <img src="/api/templates/image/${t.digit}?t=${Date.now()}" style="image-rendering:pixelated; height:60px; border:1px solid #30363d; border-radius:4px; background:#fff;">
                <div style="margin-top:8px;">
                    <button class="btn" style="font-size:10px; padding:2px 8px; color:#f85149; border-color:#f85149;" onclick="deleteTemplate('${t.digit}')">Delete</button>
                </div>
            `;
            grid.appendChild(card);
        });
    } catch (e) {
        grid.innerHTML = '<div style="color:#f85149;">Error: ' + e.message + '</div>';
    }
}

async function deleteTemplate(digit) {
    if (!confirm(`Delete template for digit ${digit}?`)) return;
    await fetch(`${API}/api/templates/${digit}`, { method: 'DELETE' });
    templatesInited = false;
    await templatesInit();
}

