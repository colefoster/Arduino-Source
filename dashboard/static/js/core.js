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

window.routeParams = {};

function route() {
    const raw = location.hash.replace('#/', '') || 'dashboard';
    const [name, query] = raw.split('?');
    const view = views.includes(name) ? name : 'dashboard';
    window.routeParams = {};
    if (query) {
        for (const [k, v] of new URLSearchParams(query)) window.routeParams[k] = v;
    }
    const sameView = view === currentView;
    currentView = view;
    //  Always re-init inspector when params present so Open-in-Inspector
    //  jumps to the requested frame even on re-entry.
    const forceInit = view === 'inspector' && Object.keys(window.routeParams).length > 0;
    if (sameView && !forceInit) return;

    //  Close any leftover full-screen overlays (gallery card modal, etc.)
    //  when navigating to a different view via hash.
    document.querySelectorAll('.gallery-expanded-overlay').forEach(el => el.remove());

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
