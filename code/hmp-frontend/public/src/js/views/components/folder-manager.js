// US-059, US-061, US-062 — папки

/**
 * Folder Manager — UI для управления папками протоколов.
 *
 * Позволяет:
 * - Создавать папки
 * - Перетаскивать протоколы в папки (drag-and-drop)
 * - Переименовывать папки
 * - Удалять папки
 */
// E222: api и toast не были импортированы — FolderManager падал при load().
import { api } from '../../api/client.js';
import { toast } from '../../utils/toast.js';

export class FolderManager {
    constructor(rootEl, onChange) {
        this.rootEl = rootEl;
        this.onChange = onChange || (() => {});
        this.folders = [];
        this.expandedFolders = new Set();
        this.activeFolderId = null;
    }

    async load() {
        try {
            const folders = await api.listFolders();
            this.folders = Array.isArray(folders) ? folders : [];
        } catch (e) {
            console.warn('Failed to load folders:', e);
            this.folders = [];
        }
    }

    async createFolder(name = 'Новая папка') {
        try {
            const folder = await api.createFolder({
                name,
                color: '#3b82f6',
                icon: 'folder',
            });
            this.folders.push(folder);
            this.render();
            this.onChange();
            toast.success(`Папка "${name}" создана`);
            return folder;
        } catch (e) {
            toast.error('Ошибка создания папки: ' + e.message);
        }
    }

    async deleteFolder(folderId) {
        const folder = this.folders.find(f => f.id === folderId);
        if (!folder) return;
        if (!confirm(`Удалить папку "${folder.name}"? Протоколы из неё останутся доступными, но без категории.`)) {
            return;
        }
        try {
            await api.deleteFolder(folderId);
            this.folders = this.folders.filter(f => f.id !== folderId);
            this.render();
            this.onChange();
            toast.success('Папка удалена');
        } catch (e) {
            toast.error('Ошибка удаления: ' + e.message);
        }
    }

    async moveProtocol(protocolId, folderId) {
        try {
            await api.moveProtocolToFolder(protocolId, folderId);
            toast.success('Протокол перемещён');
            this.onChange();
        } catch (e) {
            toast.error('Ошибка перемещения: ' + e.message);
        }
    }

    toggleFolder(folderId) {
        if (this.expandedFolders.has(folderId)) {
            this.expandedFolders.delete(folderId);
        } else {
            this.expandedFolders.add(folderId);
        }
        this.render();
    }

    render() {
        if (!this.rootEl) return;

        let html = `
            <div class="folder-sidebar">
                <div class="folder-sidebar-header">
                    <h3>📂 Папки</h3>
                    <button class="btn btn-icon" id="btn-new-folder" title="Новая папка">+</button>
                </div>
                <div class="folder-list">
                    <div class="folder-item ${!this.activeFolderId ? 'active' : ''}" data-folder-id="">
                        <span class="folder-icon">📋</span>
                        <span class="folder-name">Все протоколы</span>
                        <span class="folder-count">${this._totalProtocolCount()}</span>
                    </div>
        `;

        for (const folder of this.folders) {
            const isExpanded = this.expandedFolders.has(folder.id);
            const isActive = this.activeFolderId === folder.id;
            html += `
                <div class="folder-item ${isActive ? 'active' : ''}" data-folder-id="${folder.id}">
                    <button class="folder-toggle" data-action="toggle" data-folder-id="${folder.id}">
                        ${isExpanded ? '▼' : '▶'}
                    </button>
                    <span class="folder-icon" style="color: ${folder.color || '#3b82f6'}">📁</span>
                    <span class="folder-name" data-action="open" data-folder-id="${folder.id}">${this._escape(folder.name)}</span>
                    <span class="folder-count">${folder.protocol_count || 0}</span>
                    <button class="folder-delete" data-action="delete" data-folder-id="${folder.id}" title="Удалить">✕</button>
                </div>
            `;
        }

        html += `
                </div>
            </div>
        `;

        this.rootEl.innerHTML = html;
        this._attachHandlers();
    }

    _totalProtocolCount() {
        return this.folders.reduce((sum, f) => sum + (f.protocol_count || 0), 0);
    }

    _escape(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    _attachHandlers() {
        // New folder button
        const newBtn = this.rootEl.querySelector('#btn-new-folder');
        if (newBtn) {
            newBtn.addEventListener('click', async () => {
                const name = prompt('Название папки:', 'Новая папка');
                if (name) await this.createFolder(name);
            });
        }

        // Folder items
        this.rootEl.querySelectorAll('.folder-item').forEach(item => {
            const folderId = item.dataset.folderId || null;

            // Click on name
            const nameEl = item.querySelector('[data-action="open"]');
            if (nameEl) {
                nameEl.addEventListener('click', () => {
                    this.activeFolderId = folderId;
                    this.render();
                    this.onChange(folderId);
                });
            }

            // Click on toggle
            const toggleEl = item.querySelector('[data-action="toggle"]');
            if (toggleEl) {
                toggleEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (folderId) this.toggleFolder(folderId);
                });
            }

            // Click on delete
            const deleteEl = item.querySelector('[data-action="delete"]');
            if (deleteEl) {
                deleteEl.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (folderId) await this.deleteFolder(folderId);
                });
            }

            // Drag-drop target
            item.addEventListener('dragover', (e) => {
                e.preventDefault();
                item.classList.add('drag-over');
            });
            item.addEventListener('dragleave', () => {
                item.classList.remove('drag-over');
            });
            item.addEventListener('drop', async (e) => {
                e.preventDefault();
                item.classList.remove('drag-over');
                const protocolId = e.dataTransfer.getData('text/plain');
                if (protocolId && folderId) {
                    await this.moveProtocol(protocolId, folderId);
                } else if (protocolId && !folderId) {
                    // Remove from folder
                    await this.moveProtocol(protocolId, null);
                }
            });
        });
    }
}

// CSS for folder sidebar
export const FOLDER_MANAGER_CSS = `
.folder-sidebar {
    background: var(--bg-secondary, #f9fafb);
    border-right: 1px solid var(--border, #e5e7eb);
    padding: 16px;
    min-width: 220px;
    height: 100%;
    overflow-y: auto;
}

.folder-sidebar-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
}

.folder-sidebar-header h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
}

.folder-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.folder-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: background 0.15s;
    position: relative;
}

.folder-item:hover {
    background: rgba(59, 130, 246, 0.08);
}

.folder-item.active {
    background: rgba(59, 130, 246, 0.15);
    font-weight: 500;
}

.folder-item.drag-over {
    background: rgba(34, 197, 94, 0.2);
    border: 2px dashed #22c55e;
}

.folder-icon {
    font-size: 16px;
}

.folder-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.folder-count {
    font-size: 11px;
    background: rgba(0, 0, 0, 0.08);
    padding: 2px 6px;
    border-radius: 10px;
    color: var(--text-secondary, #6b7280);
}

.folder-toggle {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    width: 16px;
    color: var(--text-secondary);
    font-size: 10px;
}

.folder-delete {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-secondary, #9ca3af);
    font-size: 12px;
    padding: 0;
    width: 20px;
    height: 20px;
    border-radius: 4px;
    transition: all 0.15s;
    opacity: 0;
}

.folder-item:hover .folder-delete {
    opacity: 1;
}

.folder-delete:hover {
    background: #fee2e2;
    color: #dc2626;
}
`;
