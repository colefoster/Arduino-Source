// ═══════════════════════════════════════════════════════════════
// Validation
// ═══════════════════════════════════════════════════════════════
let validationInited = false;

async function validationInit() {
    if (validationInited) return;
    validationInited = true;

    const content = document.getElementById('validation-content');
    content.innerHTML = '<div style="color:#484f58; font-size:12px;">Loading validation data...</div>';

    try {
        const data = await api('/api/validation/summary');
        if (!data || !data.length) {
            content.innerHTML = '<div style="color:#484f58; font-size:12px;">No screens found</div>';
            return;
        }

        let html = '<table style="width:100%; border-collapse:collapse; font-size:12px;">';
        html += '<thead><tr style="border-bottom:1px solid #30363d; color:#8b949e;">';
        html += '<th style="text-align:left; padding:6px;">Screen</th>';
        html += '<th style="text-align:right; padding:6px;">Total</th>';
        html += '<th style="text-align:right; padding:6px;">Labeled</th>';
        html += '<th style="text-align:right; padding:6px;">Partial</th>';
        html += '<th style="text-align:right; padding:6px;">Unlabeled</th>';
        html += '<th style="text-align:right; padding:6px;">Issues</th>';
        html += '<th style="text-align:left; padding:6px;">Progress</th>';
        html += '</tr></thead><tbody>';

        let grandTotal = 0, grandLabeled = 0, grandPartial = 0, grandUnlabeled = 0, grandErrors = 0;

        for (const s of data) {
            const pct = s.total > 0 ? Math.round((s.labeled / s.total) * 100) : 0;
            const barColor = pct === 100 ? '#3fb950' : pct > 50 ? '#d29922' : '#f85149';
            grandTotal += s.total; grandLabeled += s.labeled; grandPartial += s.partial;
            grandUnlabeled += s.unlabeled; grandErrors += s.errors.length;

            html += `<tr style="border-bottom:1px solid #21262d;">`;
            html += `<td style="padding:6px;"><a href="#/gallery" onclick="setTimeout(()=>{gallerySelectedScreen='${s.screen}';loadGalleryScreenImages('${s.screen}');renderGallerySidebar();},100)" style="color:#58a6ff; cursor:pointer;">${s.screen}</a></td>`;
            html += `<td style="text-align:right; padding:6px;">${s.total}</td>`;
            html += `<td style="text-align:right; padding:6px; color:#3fb950;">${s.labeled}</td>`;
            html += `<td style="text-align:right; padding:6px; color:#d29922;">${s.partial}</td>`;
            html += `<td style="text-align:right; padding:6px; color:#f85149;">${s.unlabeled}</td>`;
            html += `<td style="text-align:right; padding:6px; color:${s.errors.length ? '#f85149' : '#8b949e'};">${s.errors.length}</td>`;
            html += `<td style="padding:6px;"><div style="background:#21262d; border-radius:3px; height:12px; width:120px; overflow:hidden;">`;
            html += `<div style="background:${barColor}; height:100%; width:${pct}%;"></div></div></td>`;
            html += `</tr>`;
        }

        // Grand total row
        const grandPct = grandTotal > 0 ? Math.round((grandLabeled / grandTotal) * 100) : 0;
        html += `<tr style="border-top:2px solid #30363d; font-weight:bold;">`;
        html += `<td style="padding:6px;">TOTAL</td>`;
        html += `<td style="text-align:right; padding:6px;">${grandTotal}</td>`;
        html += `<td style="text-align:right; padding:6px; color:#3fb950;">${grandLabeled}</td>`;
        html += `<td style="text-align:right; padding:6px; color:#d29922;">${grandPartial}</td>`;
        html += `<td style="text-align:right; padding:6px; color:#f85149;">${grandUnlabeled}</td>`;
        html += `<td style="text-align:right; padding:6px;">${grandErrors}</td>`;
        html += `<td style="padding:6px;">${grandPct}%</td>`;
        html += `</tr>`;
        html += '</tbody></table>';

        // Show errors if any
        if (grandErrors > 0) {
            html += '<h2 style="margin-top:24px; font-size:14px;">Issues</h2>';
            html += '<div style="font-size:11px; max-height:300px; overflow-y:auto;">';
            for (const s of data) {
                for (const err of s.errors) {
                    html += `<div style="padding:2px 0; color:#f85149;">`;
                    html += `<span style="color:#8b949e;">${s.screen}/</span>${err.filename}`;
                    if (err.missing_readers) html += ` - missing: ${err.missing_readers.join(', ')}`;
                    if (err.error) html += ` - ${err.reader}.${err.field}: ${err.error}`;
                    html += `</div>`;
                }
            }
            html += '</div>';
        }

        content.innerHTML = html;
    } catch (e) {
        content.innerHTML = '<div style="color:#f85149; font-size:12px;">Failed to load validation data</div>';
    }
}

