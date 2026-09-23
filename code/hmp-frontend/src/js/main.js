// US-001, US-002, US-005, US-010, US-018 — все основные сценарии

/**
 * Main entry point — router + app initialization.
 *
 * Hash-based router: #/, #/calendar, #/upload, #/protocols/{id}, etc.
 */
import { renderListView } from './views/list.js';
import { renderCalendarView } from './views/calendar.js';
import { renderUploadView } from './views/upload.js';
import { renderProtocolDetail } from './views/protocol.js';
import { renderEditSpeakers } from './views/edit-speakers.js';
import { renderLiveView } from './views/live.js';
import { renderSettingsView, SETTINGS_CSS } from './views/settings.js';
import { renderWhisperModelsView } from './views/whisper-models.js';
import { toast } from './utils/toast.js';


// Inject settings CSS once
if (!document.getElementById('settings-css')) {
    const style = document.createElement('style');
    style.id = 'settings-css';
    style.textContent = SETTINGS_CSS;
    document.head.appendChild(style);
}

const routes = {
    '#/': renderListView,
    '#/calendar': renderCalendarView,
    '#/upload': renderUploadView,
    '#/live': renderLiveView,
    '#/settings': renderSettingsView,
    '#/whisper': renderWhisperModelsView,
};

function matchRoute(hash) {
    // Static routes
    if (routes[hash.split('?')[0]]) {
        return { handler: routes[hash.split('?')[0]], params: {} };
    }

    // Dynamic routes
    // E228: добавлен флаг A (uppercase) и якорь на длину UUID 36
    const protocolMatch = hash.match(/^#\/protocols\/([a-fA-F0-9-]{36})(\/(speakers|transcript))?/);
    if (protocolMatch) {
        const [, protocolId, subRoute] = protocolMatch;
        if (subRoute === '/speakers') {
            return { handler: renderEditSpeakers, params: { protocolId } };
        }
        return { handler: renderProtocolDetail, params: { protocolId } };
    }

    return null;
}

// E227: защита от двойного вызова router() (DOMContentLoaded + hashchange)
let _routerRunning = false;

async function router() {
    if (_routerRunning) return;  // E227: уже выполняется — пропускаем
    _routerRunning = true;
    try {
        await _routerImpl();
    } finally {
        _routerRunning = false;
    }
}

async function _routerImpl() {
    const hash = window.location.hash || '#/';
    const root = document.getElementById('view-root');

    // Mark active nav link
    document.querySelectorAll('.nav-link').forEach(link => {
        const href = link.getAttribute('href');
        const isActive = href === hash.split('?')[0] ||
            (href === '#/' && hash === '#/') ||
            (href === '#/' && hash.startsWith('#/protocols'));
        link.classList.toggle('active', isActive);
    });

    const match = matchRoute(hash);

    if (!match) {
        root.innerHTML = `<h2>404</h2><p>Страница не найдена: ${escapeHtml(hash)}</p>`;
        return;
    }

    try {
        await match.handler(root, ...Object.values(match.params));
    } catch (err) {
        console.error('Route handler failed:', err);
        toast.error(`Ошибка: ${err.message}`);
        root.innerHTML = `<p class="text-error">Ошибка загрузки: ${escapeHtml(err.message)}</p>`;
    }
}

// E229: используем window.API_BASE_URL (задаётся в api/client.js)
async function checkBackend() {
    // API_BASE = "http://127.0.0.1:8000/api/v1/hmp"
    // /health — на корне backend, без /api/v1/hmp
    const apiBase = window.API_BASE_URL || 'http://127.0.0.1:8000/api/v1/hmp';
    const root = apiBase.replace(/\/api\/v1\/hmp\/?$/, '');
    try {
        const res = await fetch(`${root}/health`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        console.log('Backend OK:', data);
    } catch (err) {
        toast.warning('Backend недоступен. Работа в offline-режиме (только просмотр кэша).');
        console.warn('Backend health check failed:', err);
    }
}

window.addEventListener('hashchange', router);
window.addEventListener('DOMContentLoaded', () => {
    checkBackend();
    router();
});

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}
