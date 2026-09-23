/**
 * TabBar component — ARIA-compliant tabs.
 */
export class TabBar extends HTMLElement {
    constructor() {
        super();
        this.tabs = [];
        this.activeTab = null;
        this.changeListeners = [];
    }

    connectedCallback() {
        this.render();
        this.attachEvents();
    }

    addTab(id, label, badge = null) {
        if (!this.tabs.find(t => t.id === id)) {
            this.tabs.push({ id, label, badge });
            this.render();
            this.attachEvents();
        }
    }

    activateTab(id, silent = false) {
        const tab = this.tabs.find(t => t.id === id);
        if (!tab) return;
        this.activeTab = id;
        this.updateActiveStates();
        if (!silent) {
            this.changeListeners.forEach(cb => cb(id));
        }
        // Emit custom event
        this.dispatchEvent(new CustomEvent('tab-change', {
            detail: { id },
            bubbles: true,
        }));
    }

    onChange(callback) {
        this.changeListeners.push(callback);
    }

    render() {
        this.innerHTML = `
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
            <style>
                :host {
                    display: block;
                    border-bottom: 1px solid var(--border, #d4d8de);
                }
                .tab-list {
                    display: flex;
                    gap: 4px;
                    margin: 0;
                    padding: 0;
                    list-style: none;
                    overflow-x: auto;
                    scrollbar-width: thin;
                }
                button[role="tab"] {
                    background: transparent;
                    border: none;
                    padding: 10px 16px;
                    cursor: pointer;
                    color: var(--text-secondary, #5a6470);
                    font-size: 14px;
                    font-weight: 500;
                    font-family: inherit;
                    border-bottom: 2px solid transparent;
                    transition: all 0.2s;
                    white-space: nowrap;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                }
                button[role="tab"]:hover {
                    color: var(--text-primary, #1a1a1a);
                }
                button[role="tab"][aria-selected="true"] {
                    color: var(--accent, #2563eb);
                    border-bottom-color: var(--accent, #2563eb);
                }
                button[role="tab"]:focus-visible {
                    outline: 2px solid var(--accent, #2563eb);
                    outline-offset: -2px;
                }
                .badge {
                    background: var(--bg-tertiary, #e8ecf2);
                    color: var(--text-secondary, #5a6470);
                    border-radius: 10px;
                    padding: 1px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }
            </style>
            <div role="tablist" class="tab-list" aria-label="Вкладки протокола">
                ${this.tabs.map(t => `
                    <button role="tab" id="tab-${t.id}" aria-controls="panel-${t.id}"
                            tabindex="${t.id === this.activeTab ? '0' : '-1'}"
                            aria-selected="${t.id === this.activeTab}">
                        ${t.label}
                        ${t.badge !== null ? `<span class="badge">${t.badge}</span>` : ''}
                    </button>
                `).join('')}
            </div>
        `;
    }

    attachEvents() {
        const buttons = this.querySelectorAll('button[role="tab"]');
        buttons.forEach((btn, index) => {
            btn.addEventListener('click', () => {
                const id = btn.id.replace('tab-', '');
                this.activateTab(id);
            });
            btn.addEventListener('keydown', (e) => {
                let newIndex = index;
                if (e.key === 'ArrowRight') {
                    e.preventDefault();
                    newIndex = (index + 1) % this.tabs.length;
                } else if (e.key === 'ArrowLeft') {
                    e.preventDefault();
                    newIndex = (index - 1 + this.tabs.length) % this.tabs.length;
                } else if (e.key === 'Home') {
                    e.preventDefault();
                    newIndex = 0;
                } else if (e.key === 'End') {
                    e.preventDefault();
                    newIndex = this.tabs.length - 1;
                } else {
                    return;
                }
                const newBtn = buttons[newIndex];
                newBtn.focus();
                this.activateTab(newBtn.id.replace('tab-', ''));
            });
        });
    }

    updateActiveStates() {
        this.querySelectorAll('button[role="tab"]').forEach(btn => {
            const id = btn.id.replace('tab-', '');
            const isActive = id === this.activeTab;
            btn.setAttribute('aria-selected', isActive);
            btn.setAttribute('tabindex', isActive ? '0' : '-1');
        });
    }

    escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = String(s);
        return div.innerHTML;
    }
}

customElements.define('tab-bar', TabBar);
