// US-019, US-030 — live mode

/**
 * LiveModeView — three-panel UI для Live Mode (US-018..021).
 *
 * Layout:
 * - Left: video (iframe Телемост) + WebSocket events log
 * - Center: live transcript
 * - Right: screenshots gallery + controls
 *
 * WebSocket подключается к ws://localhost:8000/api/v1/hmp/live/{id}/stream
 */
import { api, ApiError } from '../api/client.js';
import { toast } from '../utils/toast.js';
import './components/empty-state.js';

let ws = null;
let currentProtocolId = null;

export async function renderLiveView(rootEl, protocolId) {
    currentProtocolId = protocolId || null;
    rootEl.innerHTML = `
        <div class="live-toolbar">
            <h1>🎥 Live Mode</h1>
            <div class="live-actions">
                <button class="btn btn-primary" id="btn-start"><i class="fa-solid fa-play"></i> Начать</button>
                <button class="btn" id="btn-stop" disabled><i class="fa-solid fa-stop"></i> Остановить</button>
                <span class="live-status" id="live-status">⏸ Не запущено</span>
            </div>
        </div>

        <div class="live-grid">
            <section class="live-panel video-panel">
                <h3>📺 Видео (Яндекс Телемост)</h3>
                <div id="telemost-container" class="telemost-frame">
                    <p class="text-muted">Нажмите «Начать» для запуска</p>
                </div>
            </section>

            <section class="live-panel transcript-panel">
                <h3><i class="fa-regular fa-note-sticky"></i> Транскрипция (live)</h3>
                <div id="live-transcript" class="live-transcript">
                    <empty-state icon="💬" title="Транскрипция пуста" description="Здесь будут появляться реплики в реальном времени."></empty-state>
                </div>
            </section>

            <section class="live-panel screenshots-panel">
                <h3><i class="fa-regular fa-image"></i>️ Скриншоты</h3>
                <div id="live-screenshots" class="live-screenshots">
                    <p class="text-muted">Скриншоты появятся автоматически</p>
                </div>
            </section>
        </div>

        <details class="live-events-log">
            <summary><i class="fa-regular fa-clipboard"></i> WebSocket события</summary>
            <div id="ws-log"></div>
        </details>
    `;

    document.getElementById('btn-start').addEventListener('click', startLive);
    document.getElementById('btn-stop').addEventListener('click', stopLive);

    // Cleanup on navigation
    window.addEventListener('hashchange', () => {
        if (ws) {
            ws.close();
            ws = null;
        }
    }, { once: true });
}

async function startLive() {
    const telemostUrl = prompt('URL встречи в Яндекс Телемост:', 'https://telemost.yandex.ru/j/');
    if (!telemostUrl) return;
    if (!telemostUrl.startsWith('https://')) {
        toast.error('URL должен начинаться с https://');
        return;
    }

    const title = prompt('Название встречи:', 'Планёрка') || 'Без названия';

    try {
        const result = await api.startLive({
            telemost_url: telemostUrl,
            title,
            audio_device: 'default',
            enable_screenshots: true,
            screenshot_interval_sec: 60,
        });

        currentProtocolId = result.protocol_id;
        toast.success('Live Mode запущен');

        // Update UI
        document.getElementById('btn-start').disabled = true;
        document.getElementById('btn-stop').disabled = false;
        document.getElementById('live-status').innerHTML = '<span style="color:var(--success);">●</span> Активно';

        // Embed Telemost
        document.getElementById('telemost-container').innerHTML = `
            <iframe src="${result.telemost_iframe_url}"
                    title="Яндекс Телемост"
                    allow="camera; microphone; autoplay; encrypted-media; fullscreen"
                    allowfullscreen></iframe>
        `;

        // Connect WebSocket
        connectWebSocket(result.websocket_url);

        toast.info('Live Mode активен. WebSocket подключен.');
    } catch (err) {
        if (err instanceof ApiError) {
            toast.error(`Ошибка запуска: ${err.message}`);
        } else {
            toast.error(`Не удалось запустить: ${err.message}`);
        }
    }
}

async function stopLive() {
    if (!currentProtocolId) return;
    if (!confirm('Остановить Live Mode?')) return;

    try {
        await api.stopLive(currentProtocolId);
        toast.success('Live Mode остановлен');
        if (ws) {
            ws.close();
            ws = null;
        }
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-stop').disabled = true;
        document.getElementById('live-status').innerHTML = '<span style="color:var(--text-muted);">⏸</span> Остановлено';

        // Redirect to protocol detail after a moment
        setTimeout(() => {
            window.location.hash = `#/protocols/${currentProtocolId}`;
        }, 1500);
    } catch (err) {
        toast.error(`Ошибка остановки: ${err.message}`);
    }
}

function connectWebSocket(url) {
    const wsLog = document.getElementById('ws-log');

    try {
        ws = new WebSocket(url);
    } catch (err) {
        toast.error(`Не удалось подключиться к WebSocket: ${err.message}`);
        return;
    }

    ws.onopen = () => {
        logToWS('Connected', 'success');
        toast.info('WebSocket подключен');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg);
        } catch (err) {
            console.error('Failed to parse WS message:', err, event.data);
        }
    };

    ws.onerror = (err) => {
        logToWS(`Error: ${err.toString()}`, 'error');
        console.error('WebSocket error:', err);
    };

    ws.onclose = (event) => {
        logToWS(`Disconnected (code=${event.code})`, 'warning');
        if (event.code !== 1000) {
            toast.warning('WebSocket отключен. Reconnect через 5 секунд...');
            setTimeout(() => {
                if (currentProtocolId) connectWebSocket(url);
            }, 5000);
        }
    };

    function logToWS(message, level = 'info') {
        const div = document.createElement('div');
        div.className = `ws-log-entry ws-${level}`;
        const time = new Date().toLocaleTimeString('ru-RU');
        div.textContent = `[${time}] ${message}`;
        wsLog.appendChild(div);
        wsLog.scrollTop = wsLog.scrollHeight;
    }

    function handleWSMessage(msg) {
        // E221: backend шлёт {type: "...", ...}, а не {event: "..."}.
        // Раньше switch по msg.event всегда падал в default с undefined.
        const eventType = msg.type || msg.event;
        const eventData = msg.data || msg;

        logToWS(`[${eventType}] ${JSON.stringify(eventData).slice(0, 100)}`);

        switch (eventType) {
            case 'utterance':
                addUtterance(eventData);
                break;
            case 'screenshot':
                addScreenshot(eventData);
                break;
            case 'speaker_change':
                toast.info(`Новый оратор: ${eventData.new_speaker_label}`);
                break;
            case 'heartbeat':
                // No-op, just keep-alive
                break;
            case 'ack':
                // Server echo — ignore
                break;
            case 'error':
                console.warn('Server error:', eventData);
                break;
            default:
                console.warn('Unknown event type:', eventType, msg);
        }
    }
}

function addUtterance(data) {
    const container = document.getElementById('live-transcript');
    // Remove empty state if present
    const empty = container.querySelector('empty-state');
    if (empty) empty.remove();

    const item = document.createElement('div');
    item.className = 'live-utterance';
    item.innerHTML = `
        <span class="speaker-label">${escapeHtml(data.speaker_label || '?')}:</span>
        <span class="utterance-time">${formatTime(data.start_sec)}</span>
        <span class="utterance-content">${escapeHtml(data.text || '')}</span>
    `;
    container.appendChild(item);
    container.scrollTop = container.scrollHeight;
    // Flash effect
    item.classList.add('flash');
    setTimeout(() => item.classList.remove('flash'), 1000);
}

function addScreenshot(data) {
    const container = document.getElementById('live-screenshots');
    // Remove "no screenshots" placeholder
    const placeholder = container.querySelector('p.text-muted');
    if (placeholder) placeholder.remove();

    const img = document.createElement('div');
    img.className = 'live-screenshot';
    img.innerHTML = `
        <img src="${data.url}" alt="Скриншот ${formatTime(data.timestamp_sec)}" loading="lazy">
        <time>${formatTime(data.timestamp_sec)}</time>
    `;
    container.prepend(img);
    toast.info(`Скриншот: ${formatTime(data.timestamp_sec)}`);
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}
