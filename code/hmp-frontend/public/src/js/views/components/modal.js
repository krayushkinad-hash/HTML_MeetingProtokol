/**
 * Modal component — reusable modal dialog (ARIA).
 */
export class Modal extends HTMLElement {
    constructor() {
        super();
        this.title = '';
        this.isOpen = false;
        this.closeOnBackdrop = true;
        this.closeOnEscape = true;
    }

    static get observedAttributes() {
        return ['open', 'title'];
    }

    attributeChangedCallback(name, oldValue, newValue) {
        if (name === 'open') {
            this.isOpen = this.hasAttribute('open');
            if (this.isOpen) {
                this.show();
            } else {
                this.hide();
            }
        } else if (name === 'title') {
            this.title = newValue || '';
            this.updateTitle();
        }
    }

    connectedCallback() {
        this.render();
        this.attachEvents();
    }

    // E224: снимаем обработчик с document при удалении из DOM (утечка памяти).
    disconnectedCallback() {
        if (this._keydownHandler) {
            document.removeEventListener('keydown', this._keydownHandler);
            this._keydownHandler = null;
        }
    }

    open(title = '') {
        if (title) this.title = title;
        this.setAttribute('open', '');
    }

    close() {
        this.removeAttribute('open');
    }

    show() {
        document.body.style.overflow = 'hidden';
        const previouslyFocused = document.activeElement;
        this._previouslyFocused = previouslyFocused;
        // Focus first focusable element
        requestAnimationFrame(() => {
            const focusable = this.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
            if (focusable) focusable.focus();
        });
    }

    hide() {
        document.body.style.overflow = '';
        if (this._previouslyFocused) {
            this._previouslyFocused.focus();
        }
    }

    render() {
        this.innerHTML = `
            <style>
                :host {
                    display: none;
                    position: fixed;
                    inset: 0;
                    z-index: 1000;
                    align-items: center;
                    justify-content: center;
                    font-family: var(--font-sans, -apple-system, sans-serif);
                }
                :host([open]) {
                    display: flex;
                }
                .backdrop {
                    position: absolute;
                    inset: 0;
                    background: rgba(0, 0, 0, 0.6);
                    backdrop-filter: blur(4px);
                }
                .modal-content {
                    position: relative;
                    background: var(--bg-primary, #ffffff);
                    color: var(--text-primary, #1a1a1a);
                    border-radius: 12px;
                    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
                    max-width: 90vw;
                    max-height: 90vh;
                    overflow: auto;
                    padding: 24px;
                    min-width: 320px;
                    max-width: 600px;
                }
                .modal-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 16px;
                }
                .modal-title {
                    font-size: 18px;
                    font-weight: 600;
                    margin: 0;
                }
                .close-btn {
                    background: transparent;
                    border: none;
                    font-size: 24px;
                    cursor: pointer;
                    color: var(--text-muted, #8a94a3);
                    padding: 4px 8px;
                    border-radius: 4px;
                    line-height: 1;
                    font-family: inherit;
                }
                .close-btn:hover {
                    background: var(--bg-tertiary, #e8ecf2);
                }
                .close-btn:focus-visible {
                    outline: 2px solid var(--accent, #2563eb);
                    outline-offset: 2px;
                }
            </style>
            <div class="backdrop" part="backdrop"></div>
            <div class="modal-content" role="dialog" aria-modal="true" aria-labelledby="modal-title">
                <div class="modal-header">
                    <h2 class="modal-title" id="modal-title">${this.escapeHtml(this.title)}</h2>
                    <button class="close-btn" aria-label="Закрыть">×</button>
                </div>
                <slot></slot>
            </div>
        `;
    }

    attachEvents() {
        const closeBtn = this.querySelector('.close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.close());
        }
        const backdrop = this.querySelector('.backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', () => this.close());
        }
        // E224: сохраняем handler в this._keydownHandler для disconnectedCallback
        this._keydownHandler = (e) => {
            if (!this.isOpen) return;
            if (e.key === 'Escape') {
                e.preventDefault();
                this.close();
            }
            // Trap focus
            if (e.key === 'Tab') {
                const focusable = Array.from(this.querySelectorAll(
                    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                )).filter(el => !el.disabled && el.offsetParent !== null);
                if (focusable.length === 0) return;
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                    e.preventDefault();
                    last.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                    e.preventDefault();
                    first.focus();
                }
            }
        };
        document.addEventListener('keydown', this._keydownHandler);
    }

    updateTitle() {
        const titleEl = this.querySelector('.modal-title');
        if (titleEl) titleEl.textContent = this.title;
    }

    escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = String(s);
        return div.innerHTML;
    }
}

customElements.define('modal-dialog', Modal);
