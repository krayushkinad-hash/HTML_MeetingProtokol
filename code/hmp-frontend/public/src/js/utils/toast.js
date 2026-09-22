/**
 * Toast notification manager.
 */
class ToastManager {
    constructor() {
        this.container = null;
        this._ensureContainer();
    }

    _ensureContainer() {
        if (this.container) return;
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        document.body.appendChild(this.container);
    }

    _show(message, type = 'info', durationMs = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        toast.textContent = message;
        this.container.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, durationMs);
    }

    info(message, duration) { this._show(message, 'info', duration); }
    success(message, duration) { this._show(message, 'success', duration); }
    warning(message, duration = 5000) { this._show(message, 'warning', duration); }
    error(message, duration = 7000) { this._show(message, 'error', duration); }
}

export const toast = new ToastManager();
