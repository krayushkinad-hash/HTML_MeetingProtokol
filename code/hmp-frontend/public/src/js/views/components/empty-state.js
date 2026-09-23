/**
 * EmptyState component — для пустых вкладок и состояний.
 */
export class EmptyState extends HTMLElement {
    constructor() {
        super();
    }

    static get observedAttributes() {
        return ['icon', 'title', 'description', 'action-label'];
    }

    attributeChangedCallback() {
        this.render();
    }

    connectedCallback() {
        this.render();
    }

    render() {
        const icon = this.getAttribute('icon') || '📭';
        const title = this.getAttribute('title') || 'Пусто';
        const description = this.getAttribute('description') || '';
        const actionLabel = this.getAttribute('action-label');

        this.innerHTML = `
            <style>
                :host {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    padding: 48px 24px;
                    text-align: center;
                    color: var(--text-secondary, #5a6470);
                    font-family: var(--font-sans, -apple-system, sans-serif);
                }
                .icon {
                    font-size: 48px;
                    margin-bottom: 16px;
                    opacity: 0.7;
                }
                .title {
                    font-size: 18px;
                    font-weight: 600;
                    color: var(--text-primary, #1a1a1a);
                    margin: 0 0 8px;
                }
                .description {
                    font-size: 14px;
                    max-width: 400px;
                    margin: 0 0 24px;
                    line-height: 1.5;
                }
                .action {
                    background: var(--accent, #2563eb);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-size: 14px;
                    cursor: pointer;
                    font-family: inherit;
                    font-weight: 500;
                    transition: background 0.2s;
                }
                .action:hover {
                    background: var(--accent-hover, #1e4fd1);
                }
                .action:focus-visible {
                    outline: 2px solid var(--accent, #2563eb);
                    outline-offset: 2px;
                }
            </style>
            <div class="icon" aria-hidden="true">${icon}</div>
            <h3 class="title">${this.escapeHtml(title)}</h3>
            ${description ? `<p class="description">${this.escapeHtml(description)}</p>` : ''}
            ${actionLabel ? `<button class="action">${this.escapeHtml(actionLabel)}</button>` : ''}
        `;

        const actionBtn = this.querySelector('.action');
        if (actionBtn) {
            actionBtn.addEventListener('click', () => {
                this.dispatchEvent(new CustomEvent('action', { bubbles: true }));
            });
        }
    }

    escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = String(s);
        return div.innerHTML;
    }
}

customElements.define('empty-state', EmptyState);
