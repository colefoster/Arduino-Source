// Lead/Team Advisor view
// Calls /api/advisor with own + opp team strings, renders the hybrid result.

let advisorInited = false;

function advisorInit() {
    if (advisorInited) return;
    advisorInited = true;

    document.getElementById('advisor-go').addEventListener('click', advisorRun);
    document.getElementById('advisor-swap').addEventListener('click', () => {
        const o = document.getElementById('advisor-own');
        const p = document.getElementById('advisor-opp');
        const t = o.value;
        o.value = p.value;
        p.value = t;
    });
    document.getElementById('advisor-clear').addEventListener('click', () => {
        document.getElementById('advisor-own').value = '';
        document.getElementById('advisor-opp').value = '';
        document.getElementById('advisor-source').textContent = '';
        document.getElementById('advisor-bring').innerHTML = '';
        document.querySelector('#advisor-brought-alts tbody').innerHTML = '';
        document.querySelector('#advisor-leads tbody').innerHTML = '';
        document.getElementById('advisor-status').textContent = '';
    });

    document.querySelectorAll('#advisor-own, #advisor-opp').forEach(el => {
        el.addEventListener('keydown', e => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) advisorRun();
        });
    });
}

function _splitSpecies(s) {
    return s.split(',').map(x => x.trim()).filter(Boolean);
}

async function advisorRun() {
    const own = _splitSpecies(document.getElementById('advisor-own').value);
    const opp = _splitSpecies(document.getElementById('advisor-opp').value);
    const status = document.getElementById('advisor-status');

    if (own.length !== 6 || opp.length !== 6) {
        status.textContent = `Need exactly 6 species each (got own=${own.length}, opp=${opp.length})`;
        return;
    }
    status.textContent = 'Recommending...';

    let data;
    try {
        const resp = await fetch('/api/advisor', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ own, opp }),
        });
        data = await resp.json();
    } catch (e) {
        status.textContent = `Error: ${e}`;
        return;
    }

    if (data.error) {
        status.textContent = data.error;
        return;
    }
    status.textContent = '';

    // Source line
    const src = document.getElementById('advisor-source');
    let srcText = `Source: ${data.source}`;
    if (data.support) srcText += `  (team_n=${data.support.team_n}, lead_n=${data.support.lead_n})`;
    src.textContent = srcText;

    // Bring set
    const bring = document.getElementById('advisor-bring');
    bring.innerHTML = (data.brought.set || []).map(sp =>
        `<span class="advisor-mon">${sp}</span>`
    ).join('');

    // Alternative brought sets
    const altsBody = document.querySelector('#advisor-brought-alts tbody');
    altsBody.innerHTML = '';
    const cands = data.brought.candidates || [];
    if (cands.length === 0) {
        altsBody.innerHTML = '<tr><td colspan="3" class="muted">(none — single recommendation)</td></tr>';
    } else {
        cands.forEach(c => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${(c.share * 100).toFixed(1)}%</td><td>${c.count}</td><td>${(c.set || []).join(', ')}</td>`;
            altsBody.appendChild(tr);
        });
    }

    // Lead pairs
    const leadsBody = document.querySelector('#advisor-leads tbody');
    leadsBody.innerHTML = '';
    (data.leads || []).forEach(l => {
        const [a, b] = l.pair;
        const tr = document.createElement('tr');
        const cnt = (l.count !== undefined && l.count !== '') ? l.count : '';
        tr.innerHTML = `<td>${((l.prob || 0) * 100).toFixed(1)}%</td><td>${cnt}</td><td>${a} + ${b}</td>`;
        leadsBody.appendChild(tr);
    });
}
