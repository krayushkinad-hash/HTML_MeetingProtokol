// US-064 — видео плеер

/**
 * VideoPlayer component — HTML5 video player с custom controls.
 *
 * Поддерживает:
 * - HTTP Range streaming (/media/protocols/{id}/source.ext?t={sec})
 * - Play/Pause, Seek, Volume, Mute, Fullscreen
 * - Playback speed (0.5x, 1x, 1.5x, 2x)
 * - Keyboard navigation
 * - Custom Events: 'timeupdate', 'ended', 'seekTo'
 */
export class VideoPlayer extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this.currentTime = 0;
        this.duration = 0;
        this.isPlaying = false;
        this.isMuted = false;
        this.volume = 1.0;
        this.playbackRate = 1.0;
        this.isFullscreen = false;
        this.lastUpdateTime = 0;
    }

    connectedCallback() {
        this.render();
        this.video = this.shadowRoot.querySelector('video');
        this.attachEvents();
    }

    setSource(url) {
        if (!this.video) return;
        this.video.src = url;
        this.video.load();
    }

    seekTo(seconds) {
        if (this.video) {
            this.video.currentTime = seconds;
            this.updateTimeDisplay();
        }
    }

    play() {
        if (this.video) this.video.play();
    }

    pause() {
        if (this.video) this.video.pause();
    }

    render() {
        this.shadowRoot.innerHTML = `
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
            <style>
                :host {
                    display: block;
                    position: relative;
                    background: #000;
                    border-radius: 8px;
                    overflow: hidden;
                    font-family: var(--font-sans, -apple-system, sans-serif);
                    color: white;
                }
                video {
                    width: 100%;
                    height: 100%;
                    display: block;
                    background: #000;
                    max-height: 60vh;
                    object-fit: contain;
                }
                .controls {
                    position: absolute;
                    bottom: 0;
                    left: 0;
                    right: 0;
                    background: linear-gradient(to top, rgba(0,0,0,0.8), transparent);
                    padding: 12px 16px;
                    opacity: 0;
                    transition: opacity 0.2s;
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }
                :host(:hover) .controls,
                .controls.visible {
                    opacity: 1;
                }
                .progress-row {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .progress-bar {
                    flex: 1;
                    height: 6px;
                    background: rgba(255,255,255,0.2);
                    border-radius: 3px;
                    cursor: pointer;
                    position: relative;
                }
                .progress-fill {
                    height: 100%;
                    background: var(--accent, #2563eb);
                    border-radius: 3px;
                    width: 0%;
                    transition: width 0.1s linear;
                }
                .progress-bar:hover {
                    height: 8px;
                }
                .controls-row {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }
                button {
                    background: transparent;
                    border: none;
                    color: white;
                    cursor: pointer;
                    padding: 4px 8px;
                    font-size: 16px;
                    transition: opacity 0.2s;
                    font-family: inherit;
                }
                button:hover {
                    opacity: 0.8;
                }
                button:focus-visible {
                    outline: 2px solid white;
                    outline-offset: 2px;
                }
                .time-display {
                    font-variant-numeric: tabular-nums;
                    font-size: 13px;
                    opacity: 0.9;
                    min-width: 110px;
                }
                .volume-slider {
                    width: 80px;
                    height: 4px;
                    accent-color: var(--accent, #2563eb);
                }
                .speed-select {
                    background: rgba(255,255,255,0.1);
                    color: white;
                    border: 1px solid rgba(255,255,255,0.3);
                    border-radius: 4px;
                    padding: 2px 6px;
                    font-size: 13px;
                    font-family: inherit;
                    cursor: pointer;
                }
                .spacer { flex: 1; }
                .error {
                    position: absolute;
                    inset: 0;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    background: rgba(0,0,0,0.9);
                }
                .error.hidden { display: none; }
            </style>
            <video preload="metadata"></video>
            <div class="controls">
                <div class="progress-row">
                    <div class="progress-bar" part="progress" tabindex="0" role="slider"
                         aria-label="Перемотка видео" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
                        <div class="progress-fill"></div>
                    </div>
                </div>
                <div class="controls-row">
                    <button class="play-pause" aria-label="Воспроизведение/пауза">▶</button>
                    <button class="back-5" aria-label="Назад 5 секунд">−5s</button>
                    <button class="fwd-5" aria-label="Вперёд 5 секунд">+5s</button>
                    <span class="time-display">0:00 / 0:00</span>
                    <button class="mute" aria-label="Звук вкл/выкл">🔊</button>
                    <input type="range" class="volume-slider" min="0" max="1" step="0.05" value="1" aria-label="Громкость">
                    <select class="speed-select" aria-label="Скорость воспроизведения">
                        <option value="0.5">0.5×</option>
                        <option value="0.75">0.75×</option>
                        <option value="1" selected>1×</option>
                        <option value="1.25">1.25×</option>
                        <option value="1.5">1.5×</option>
                        <option value="2">2×</option>
                    </select>
                    <span class="spacer"></span>
                    <button class="fullscreen" aria-label="Полный экран">⛶</button>
                </div>
            </div>
            <div class="error hidden">
                <div>
                    <p>⚠️ Не удалось загрузить видео</p>
                    <small>Проверьте, что файл существует на диске</small>
                </div>
            </div>
        `;
    }

    attachEvents() {
        this.video.addEventListener('loadedmetadata', () => {
            this.duration = this.video.duration || 0;
            this.updateTimeDisplay();
        });

        this.video.addEventListener('timeupdate', () => {
            // Throttle: emit только каждые 250ms
            const now = Date.now();
            if (now - this.lastUpdateTime > 250) {
                this.currentTime = this.video.currentTime;
                this.dispatchEvent(new CustomEvent('timeupdate', {
                    detail: { currentTime: this.currentTime, duration: this.duration },
                    bubbles: true,
                }));
                this.updateTimeDisplay();
                this.lastUpdateTime = now;
            }
        });

        this.video.addEventListener('play', () => {
            this.isPlaying = true;
            this.shadowRoot.querySelector('.play-pause').textContent = '⏸';
        });

        this.video.addEventListener('pause', () => {
            this.isPlaying = false;
            this.shadowRoot.querySelector('.play-pause').textContent = '▶';
        });

        this.video.addEventListener('ended', () => {
            this.dispatchEvent(new CustomEvent('ended', { bubbles: true }));
        });

        this.video.addEventListener('error', () => {
            this.shadowRoot.querySelector('.error').classList.remove('hidden');
        });

        // Buttons
        this.shadowRoot.querySelector('.play-pause').addEventListener('click', () => this.togglePlay());
        this.shadowRoot.querySelector('.back-5').addEventListener('click', () => this.skip(-5));
        this.shadowRoot.querySelector('.fwd-5').addEventListener('click', () => this.skip(5));
        this.shadowRoot.querySelector('.mute').addEventListener('click', () => this.toggleMute());
        this.shadowRoot.querySelector('.volume-slider').addEventListener('input', (e) => {
            this.video.volume = parseFloat(e.target.value);
            this.video.muted = false;
        });
        this.shadowRoot.querySelector('.speed-select').addEventListener('change', (e) => {
            this.video.playbackRate = parseFloat(e.target.value);
        });
        this.shadowRoot.querySelector('.fullscreen').addEventListener('click', () => this.toggleFullscreen());

        // Progress bar click
        const progressBar = this.shadowRoot.querySelector('.progress-bar');
        progressBar.addEventListener('click', (e) => {
            const rect = progressBar.getBoundingClientRect();
            const ratio = (e.clientX - rect.left) / rect.width;
            this.seekTo(ratio * this.duration);
        });
        progressBar.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                this.skip(-5);
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                this.skip(5);
            }
        });

        // Auto-hide controls
        let hideTimer;
        this.addEventListener('mousemove', () => {
            this.shadowRoot.querySelector('.controls').classList.add('visible');
            clearTimeout(hideTimer);
            if (this.isPlaying) {
                hideTimer = setTimeout(() => {
                    this.shadowRoot.querySelector('.controls').classList.remove('visible');
                }, 3000);
            }
        });

        // Keyboard
        document.addEventListener('keydown', (e) => {
            // Не перехватываем если фокус в input/textarea
            if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
            if (!this.isConnected) return;

            switch (e.key) {
                case ' ':
                    e.preventDefault();
                    this.togglePlay();
                    break;
                case 'ArrowLeft':
                    this.skip(e.shiftKey ? -30 : -5);
                    break;
                case 'ArrowRight':
                    this.skip(e.shiftKey ? 30 : 5);
                    break;
                case 'm':
                case 'M':
                    this.toggleMute();
                    break;
                case 'f':
                case 'F':
                    this.toggleFullscreen();
                    break;
                case '0': case '1': case '2': case '3': case '4':
                case '5': case '6': case '7': case '8': case '9':
                    const percent = parseInt(e.key) / 10;
                    this.seekTo(this.duration * percent);
                    break;
            }
        });
    }

    togglePlay() {
        if (this.video.paused) {
            this.video.play();
        } else {
            this.video.pause();
        }
    }

    skip(seconds) {
        if (this.video) {
            this.video.currentTime = Math.max(0, Math.min(this.video.duration, this.video.currentTime + seconds));
            this.updateTimeDisplay();
        }
    }

    toggleMute() {
        if (this.video) {
            this.video.muted = !this.video.muted;
            this.shadowRoot.querySelector('.mute').textContent = this.video.muted ? '🔇' : '🔊';
        }
    }

    toggleFullscreen() {
        if (!document.fullscreenElement) {
            this.requestFullscreen?.();
        } else {
            document.exitFullscreen?.();
        }
    }

    updateTimeDisplay() {
        if (!this.duration || !this.video) return;
        const cur = this.formatTime(this.video.currentTime);
        const dur = this.formatTime(this.duration);
        this.shadowRoot.querySelector('.time-display').textContent = `${cur} / ${dur}`;
        const percent = (this.video.currentTime / this.duration) * 100;
        this.shadowRoot.querySelector('.progress-fill').style.width = `${percent}%`;
        this.shadowRoot.querySelector('.progress-bar').setAttribute('aria-valuenow', Math.round(percent));
    }

    formatTime(seconds) {
        if (!isFinite(seconds)) return '0:00';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) {
                return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }
        return `${m}:${String(s).padStart(2, '0')}`;
    }
}

customElements.define('video-player', VideoPlayer);
