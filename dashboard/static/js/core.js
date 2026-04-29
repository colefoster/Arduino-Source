// ═══════════════════════════════════════════════════════════════
// App core: routing, API helper
// ═══════════════════════════════════════════════════════════════
const API = window.location.origin;

function api(path) { return fetch(`${API}${path}`).then(r => r.json()); }
function apiPost(path, body) {
    const fd = new FormData();
    for (const [k, v] of Object.entries(body)) fd.append(k, v);
    return fetch(`${API}${path}`, { method: 'POST', body: fd }).then(r => r.json());
}

const views = ['dashboard', 'gallery', 'labeler', 'inspector', 'recognition', 'teampreview', 'templates', 'model', 'training', 'validation'];
let currentView = null;

function route() {
    const hash = location.hash.replace('#/', '') || 'dashboard';
    const view = views.includes(hash) ? hash : 'dashboard';
    if (view === currentView) return;
    currentView = view;

    // Toggle views
    views.forEach(v => {
        document.getElementById(`view-${v}`).classList.toggle('active', v === view);
    });

    // Toggle nav
    document.querySelectorAll('.nav-link').forEach(el => {
        el.classList.toggle('active', el.dataset.route === view);
    });

    // Init view if needed
    if (view === 'dashboard') dashboardInit();
    if (view === 'gallery') galleryInit();
    if (view === 'labeler') labelerInit();
    if (view === 'inspector') inspectorInit();
    if (view === 'recognition') recognitionInit();
    if (view === 'teampreview') teamPreviewInit();
    if (view === 'templates') templatesInit();
    if (view === 'model') modelInit();
    if (view === 'training') trainingInit();
    if (view === 'validation') validationInit();
}

window.addEventListener('hashchange', route);
window.addEventListener('load', route);
