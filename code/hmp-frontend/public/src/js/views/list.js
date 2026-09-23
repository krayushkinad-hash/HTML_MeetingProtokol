// US-010 — список протоколов; US-014 — фильтр по дате

/**
 * List view — отображение списка протоколов (F-HMP-2).
 */
import { api } from '../api/client.js';
import { storage, STORES } from '../storage/indexeddb.js';
import { toast } from '../utils/toast.js';
import { ICONS } from './components/icons.js';

// E214: FolderManager не инстанцируется — убран из импорта
import { FOLDER_MANAGER_CSS } from './components/folder-manager.js';


let currentFolderFilter = null;  // null = all, folder.id = filter by folder

export async function renderListView(rootEl) {
    rootEl.innerHTML = `
        <div class="toolbar">
            <input type="search" class="input search-input" placeholder="Поиск по протоколам..." id="search-input">
            <button class="btn btn-primary" onclick="window.location.hash='#/upload'"><i class="fa-regular fa-folder"></i> Загрузить</button>
        </div>
        <div id="protocols-list" class="list">
            <div class="loading"><div class="spinner"></div> Загрузка протоколов...</div>
        </div>
    
<style>
${FOLDER_MANAGER_CSS}
.protocol-card[draggable="true"] {
    cursor: grab;
}
.protocol-card[draggable="true"]:active {
    cursor: grabbing;
}
.folders-layout {
    display: flex;
    gap: 20px;
    height: 100%;
}
.folders-layout .protocols-section {
    flex: 1;
    min-width: 0;
}
</style>
`;

    const listEl = document.getElementById('protocols-list');
    const searchInput = document.getElementById('search-input');

    async function load(q = '') {
        try {
            // E213: клиентский фильтр по протоколам.
            // api.search() ищет по utterance, а не по протоколам —
            // раньше при поиске показывались строки с undefined.
            const response = await api.listProtocols({ limit: 200 });
            let protocols = response.items || [];

            if (q) {
                const qLower = q.toLowerCase();
                protocols = protocols.filter(p =>
                    (p.title || '').toLowerCase().includes(qLower) ||
                    (p.location || '').toLowerCase().includes(qLower) ||
                    (p.chair || '').toLowerCase().includes(qLower)
                );
            }

            // Кэшируем в IndexedDB для офлайн
            if (Array.isArray(protocols)) {
                for (const p of protocols) {
                    if (p.id) await storage.put(STORES.protocols, p);
                }
            }

            render(protocols || []);
        } catch (err) {
            console.error('Failed to load protocols:', err);
            // Fallback на IndexedDB кэш
            const cached = await storage.getAll(STORES.protocols);
            if (cached.length > 0) {
                toast.warning('Нет связи с сервером, показаны кэшированные протоколы');
                render(cached);
            } else {
                toast.error(`Ошибка загрузки: ${err.message}`);
                listEl.innerHTML = `<p class="text-error">Не удалось загрузить протоколы: ${err.message}</p>`;
            }
        }
    }

    function render(protocols) {
        if (!protocols.length) {
            listEl.innerHTML = `<p class="text-muted">Нет протоколов. <a href="#/upload">Загрузить первый</a></p>`;
            return;
        }

        listEl.innerHTML = protocols.map(p => `
            <div class="card protocol-card" draggable="true" data-id="${p.id}">
                <div class="card-header">
                    <div>
                        <div class="card-title">${escapeHtml(p.title)}</div>
                        <div class="card-meta">${p.date}${p.folder_id ? ' · <i class="fa-regular fa-folder"></i>' : ''}</div>
                    </div>
                    <span class="badge badge-${statusBadge(p.status)}">${statusLabel(p.status)}</span>
                </div>
                ${p.location ? `<div class="text-muted"><i class="fa-solid fa-location-dot"></i> ${escapeHtml(p.location)}</div>` : ''}
            </div>
        `).join('');

        listEl.querySelectorAll('.protocol-card').forEach(card => {
            // Click to open
            card.addEventListener('click', (e) => {
                // Don't open if it was a drag
                if (card.dataset.dragged === '1') {
                    card.dataset.dragged = '0';
                    return;
                }
                window.location.hash = `#/protocols/${card.dataset.id}`;
            });

            // Drag-and-drop
            card.addEventListener('dragstart', (e) => {
                card.dataset.dragged = '1';
                e.dataTransfer.setData('text/plain', card.dataset.id);
                e.dataTransfer.effectAllowed = 'move';
                card.classList.add('dragging');
            });
            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
                setTimeout(() => { card.dataset.dragged = '0'; }, 100);
            });
        });
    }

    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => load(e.target.value), 300);
    });

    await load();
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}

function statusBadge(status) {
    return {
        ready: 'success',
        loaded: 'warning',
        transcribing: 'warning',
        failed: 'danger',
    }[status] || 'warning';
}

function statusLabel(status) {
    return {
        ready: 'Готов',
        loaded: 'Загружен',
        transcribing: 'Транскрибируется',
        failed: 'Ошибка',
    }[status] || status;
}
