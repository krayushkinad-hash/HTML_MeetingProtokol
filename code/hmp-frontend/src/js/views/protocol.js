// US-005 — транскрипция; US-022 — саммари; US-023 — action items
// US-047: graceful fallback — основной протокол грузится обязательно,
// вспомогательные данные могут быть пустыми без ошибки.

/**
 * ProtocolDetail view -- детальный view протокола.
 *
 * Включает: video player, transcript, screenshots, decisions, action items, tags, summary.
 * Hotkeys: Space (play/pause), Esc (назад к списку), Ctrl+S (export DOCX).
 */
import { api, ApiError } from '../api/client.js';
import { storage, STORES } from '../storage/indexeddb.js';
import { toast } from '../utils/toast.js';
import './components/video-player.js';
import './components/tab-bar.js';
import './components/modal.js';
import './components/empty-state.js';

// Don't await on top level - this can break module loading
// Instead, open DB lazily on first call to storage
console.log('protocol.js loaded');
export async function renderProtocolDetail(rootEl, protocolId) {
    rootEl.innerHTML = '<div class="loading"><div class="spinner"></div> Загрузка протокола...</div>';

    let protocol, utterances, speakers, summary, tags, actionItems, screenshots, decisions;
    // US-053: helper to safely cast any value to array
    const safeArray = (x) => Array.isArray(x) ? x : [];

    // US-047: Сначала пробуем загрузить с сервера
    let serverSuccess = false;
    try {
        [protocol, utterances, speakers, summary, tags, actionItems, screenshots, decisions] = await Promise.all([
            api.getProtocol(protocolId),
            api.listUtterances(protocolId, { limit: 100 }).catch(() => []),
            api.listSpeakers(protocolId).catch(() => []),
            api.getSummary(protocolId).catch(() => null),
            api.listTags(protocolId).catch(() => []),
            api.listActionItems(protocolId).catch(() => []),
            api.listScreenshots ? api.listScreenshots(protocolId).catch(() => []) : Promise.resolve([]),
            api.listDecisions ? api.listDecisions(protocolId).catch(() => []) : Promise.resolve([]),
        ]);

        // Cache в IndexedDB (только если основной протокол загружен)
        if (protocol && protocol.id) {
            await storage.put(STORES.protocols, protocol);
            const utterancesList = Array.isArray(utterances) ? utterances : [];
            for (const u of utterancesList) await storage.put(STORES.utterances, u);
            const speakersList = Array.isArray(speakers) ? speakers : [];
            for (const s of speakersList) await storage.put(STORES.speakers, s);
            serverSuccess = true;
        }
    } catch (err) {
        // US-047: только если getProtocol упал — fallback на кэш
        if (err instanceof ApiError && err.status === 404) {
            toast.error('Протокол не найден');
            window.location.hash = '#/';
            return;
        }
        // Network error или другая ошибка — попробуем кэш
        console.warn('Server fetch failed, trying cache:', err);
    }

    // US-047: Fallback на кэш только если server не вернул protocol
    if (!serverSuccess || !protocol) {
        const cached = await storage.get(STORES.protocols, protocolId);
        if (cached) {
            toast.info('Нет связи с сервером, показана кэшированная версия');
            protocol = cached;
            utterances = safeArray(await storage.getByIndex(STORES.utterances, 'by_protocol', protocolId));
            speakers = safeArray(await storage.getByIndex(STORES.speakers, 'by_protocol', protocolId));
            summary = null;
            tags = safeArray(await storage.getByIndex(STORES.tags, 'by_protocol', protocolId));
            actionItems = safeArray(await storage.getByIndex(STORES.action_items, 'by_protocol', protocolId));
            screenshots = safeArray(await storage.getByIndex(STORES.screenshots, 'by_protocol', protocolId));
            decisions = safeArray(await storage.getByIndex(STORES.decisions, 'by_protocol', protocolId));
        } else {
            toast.error('Не удалось загрузить протокол (нет сервера и нет кэша)');
            window.location.hash = '#/';
            return;
        }
    }

    renderProtocolUI(
        rootEl, protocol,
        Array.isArray(utterances) ? utterances : [],
        Array.isArray(speakers) ? speakers : [],
        summary,
        Array.isArray(tags) ? tags : [],
        Array.isArray(actionItems) ? actionItems : [],
        Array.isArray(screenshots) ? screenshots : [],
        Array.isArray(decisions) ? decisions : []
    );

    // Check if transcription is already running for this protocol
    checkExistingTranscription(protocol);

    // Hotkeys
    setupHotkeys(protocolId);
}

function renderProtocolUI(rootEl, protocol, utterances, speakers, summary, tags, actionItems, screenshots = [], decisions = []) {
    const statusBadge = getStatusBadge(protocol.status);
    const dateStr = new Date(protocol.date).toLocaleDateString('ru-RU', {
        year: 'numeric', month: 'long', day: 'numeric',
    });

    rootEl.innerHTML = `
        <div class="protocol-header">
            <div>
                <button class="btn" onclick="window.location.hash='#/'" aria-label="Назад к списку">← Назад</button>
                <h1 style="display:inline-block; margin-left:12px;">${escapeHtml(protocol.title)}</h1>
                <span class="badge badge-${statusBadge.type}" style="margin-left:8px;">${statusBadge.label}</span>
            </div>
            <div class="actions">
                <button class="btn btn-primary" id="btn-export"><i class="fa-regular fa-file-lines"></i> Экспорт DOCX</button>
<button class="btn btn-danger" id="btn-delete"><i class="fa-regular fa-trash-can"></i> Удалить</button>
                <button class="btn" id="btn-transcribe"><i class="fa-solid fa-play"></i> Транскрибировать</button>
            </div>
        </div>

        <div class="protocol-meta">
            <span><i class="fa-regular fa-calendar"></i> ${dateStr || 'Дата не указана'}</span>
            ${protocol.location ? `<span><i class="fa-solid fa-location-dot"></i> ${escapeHtml(protocol.location)}</span>` : ''}
            ${protocol.chair ? `<span><i class="fa-regular fa-user"></i> ${escapeHtml(protocol.chair)}</span>` : ''}
            ${protocol.duration_sec ? `<span><i class="fa-regular fa-clock"></i> ${formatDuration(protocol.duration_sec)}</span>` : ''}
            ${protocol.wer_quality !== null ? `<span><i class="fa-solid fa-chart-column"></i> WER: ${protocol.wer_quality}%</span>` : ''}
        </div>

        ${protocol.audio_file ? `
            <div class="file-info">
                <div class="file-info-main" title="Кликните для просмотра полного пути">
                    <span class="file-info-icon">${protocol.audio_file.source === 'url' ? '<i class="fa-solid fa-link"></i>' : '<i class="fa-solid fa-paperclip"></i>'}</span>
                    <span class="file-info-name">${escapeHtml(protocol.audio_file.filename || 'Неизвестный файл')}</span>
                    <span class="file-info-size">${formatFileSize(protocol.audio_file.size_bytes || 0)}</span>
                    ${protocol.audio_file.source === 'url' && protocol.audio_file.source_url ?
                        `<a href="${escapeHtml(protocol.audio_file.source_url)}" target="_blank" class="file-info-link"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>` : ''}
                </div>
                ${protocol.audio_file.file_path ? `
                    <div class="file-info-path" title="${escapeHtml(protocol.audio_file.file_path)}">
                        <span class="file-info-path-label">Путь:</span>
                        <span class="file-info-path-value">${escapeHtml(formatPath(protocol.audio_file.file_path))}</span>
                        <button class="btn-copy-path" data-path="${escapeHtml(protocol.audio_file.file_path)}" title="Скопировать полный путь"><i class="fa-regular fa-clipboard"></i></button>
                        <button class="btn-open-folder" data-audio-id="${protocol.audio_file.id}" data-path="${escapeHtml(protocol.audio_file.file_path)}" title="Открыть папку с файлом"><i class="fa-regular fa-folder-open"></i></button>
                    </div>
                ` : ''}
            </div>
        ` : ''}

        <div id="video-container"></div>

        <tab-bar id="protocol-tabs">
            <button role="tab" id="tab-transcript" aria-controls="panel-transcript"><i class="fa-regular fa-note-sticky"></i> Транскрипция</button>
            <button role="tab" id="tab-screenshots" aria-controls="panel-screenshots"><i class="fa-regular fa-image"></i>️ Скриншоты</button>
            <button role="tab" id="tab-decisions" aria-controls="panel-decisions"><i class="fa-solid fa-check"></i> Решения</button>
            <button role="tab" id="tab-tasks" aria-controls="panel-tasks"><i class="fa-regular fa-clipboard"></i> Задачи</button>
            <button role="tab" id="tab-summary" aria-controls="panel-summary"><i class="fa-regular fa-file-lines"></i> Саммари</button>
            <button role="tab" id="tab-speakers" aria-controls="panel-speakers"><i class="fa-solid fa-microphone"></i> Ораторы</button>
        </tab-bar>

        <div id="panels">
            <div role="tabpanel" id="panel-transcript" aria-labelledby="tab-transcript" hidden></div>
            <div role="tabpanel" id="panel-screenshots" aria-labelledby="tab-screenshots" hidden></div>
            <div role="tabpanel" id="panel-decisions" aria-labelledby="tab-decisions" hidden></div>
            <div role="tabpanel" id="panel-tasks" aria-labelledby="panel-tasks" hidden></div>
            <div role="tabpanel" id="panel-summary" aria-labelledby="tab-summary" hidden></div>
            <div role="tabpanel" id="panel-speakers" aria-labelledby="tab-speakers" hidden></div>
        </div>
    `;

    // Video player
    // Safe array helpers
    const safeArray = (arr) => Array.isArray(arr) ? arr : [];
    const safeFilter = (arr, predicate) => safeArray(arr).filter(predicate);

    // Video player
    if (protocol.audio_file) {
        const player = document.createElement('video-player');
        const audioUrl = `${window.__BACKEND_URL__ || "http://127.0.0.1:8000"}/api/v1/hmp/media/protocols/${protocol.id}/source.${protocol.audio_file.extension}`;
        player.style.width = '100%';
        rootEl.querySelector('#video-container').appendChild(player);
        // Загружаем видео после монтирования
        requestAnimationFrame(() => player.setSource(audioUrl));
    }

    // Инициализация табов (нужно вызвать addTab для TabBar компонента)
    const tabBar = rootEl.querySelector('tab-bar');
    tabBar.tabs = [
        { id: 'transcript', label: '<i class="fa-regular fa-note-sticky"></i> Транскрипция', badge: utterances.length },
        { id: 'screenshots', label: '<i class="fa-regular fa-image"></i> Скриншоты', badge: screenshots.length },
        { id: 'decisions', label: '<i class="fa-solid fa-check"></i> Решения', badge: decisions.length },
        { id: 'tasks', label: '<i class="fa-regular fa-clipboard"></i> Задачи', badge: safeFilter(actionItems, a => a.status === 'open').length },
        { id: 'summary', label: '<i class="fa-regular fa-file-lines"></i> Саммари', badge: summary ? 1 : 0 },
        { id: 'speakers', label: '<i class="fa-solid fa-microphone"></i> Ораторы', badge: speakers.length },
    ];
    tabBar.render();
    tabBar.attachEvents();
    tabBar.activateTab('transcript', true);

    tabBar.onChange(tabId => switchTab(tabId, protocol, utterances, speakers, summary, tags, actionItems));

    // Рендерим все панели (но показываем только активную)
    renderTranscriptTab(rootEl, protocol, utterances, speakers);
    renderScreenshotsTab(rootEl, protocol, []);
    renderDecisionsTab(rootEl, protocol);
    renderTasksTab(rootEl, protocol, actionItems);
    renderSummaryTab(rootEl, protocol, summary);
    renderSpeakersTab(rootEl, protocol, speakers, utterances);

    // Action handlers
    document.getElementById('btn-export').addEventListener('click', () => startExport(protocol));

    // Copy path buttons
    rootEl.querySelectorAll('.btn-copy-path').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const path = btn.dataset.path;
            try {
                await navigator.clipboard.writeText(path);
                toast.success('Путь скопирован в буфер обмена');
            } catch (err) {
                toast.warning('Не удалось скопировать: ' + err.message);
            }
        });
    });

    // Open folder buttons (US-069)
    rootEl.querySelectorAll('.btn-open-folder').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const audioFileId = btn.dataset.audioId;
            const path = btn.dataset.path;
            
            // Copy path to clipboard as fallback
            try {
                await navigator.clipboard.writeText(path);
            } catch (err) {
                // ignore
            }
            
            try {
                const result = await api.openAudioFolder(audioFileId);
                
                if (result.error) {
                    toast.error('Ошибка открытия: ' + result.error);
                } else if (!result.file_exists && !result.folder_exists) {
                    toast.warning('Файл/папка не найдены: ' + path);
                    toast.info('Путь скопирован в буфер');
                } else {
                    const osLabel = {windows: 'Проводник', darwin: 'Finder', linux: 'файловый менеджер'}[result.os] || 'файл-менеджер';
                    toast.success(`${osLabel} открыт: ${result.folder}`);
                    toast.info('Путь также скопирован в буфер');
                }
            } catch (err) {
                toast.error('Ошибка: ' + err.message);
                toast.info('Путь скопирован в буфер. Вставьте в проводник.');
            }
        });
    });
document.getElementById('btn-delete')?.addEventListener('click', () => confirmDeleteProtocol(protocol));
    document.getElementById('btn-transcribe').addEventListener('click', () => startTranscribe(protocol));
}

function switchTab(tabId, protocol, utterances, speakers, summary, tags, actionItems) {
    const panels = document.querySelectorAll('[role="tabpanel"]');
    panels.forEach(p => p.hidden = true);
    const active = document.getElementById(`panel-${tabId}`);
    if (active) active.hidden = false;
}

// ────────────────────────────────────────────────────────────
// Tab renderers (to be expanded in next iteration)
// ────────────────────────────────────────────────────────────

function renderTranscriptTab(rootEl, protocol, utterances, speakers) {
    const panel = rootEl.querySelector('#panel-transcript');
    if (!utterances.length) {
        panel.innerHTML = `<empty-state icon="<i class="fa-regular fa-note-sticky"></i>" title="Нет транскрипции" description="Запустите транскрипцию чтобы получить распознанный текст." action-label="<i class="fa-solid fa-play"></i> Транскрибировать"></empty-state>`;
        return;
    }
    panel.innerHTML = `
        <div class="transcript-toolbar">
            <button class="btn" id="btn-cleanup-ai">✨ Исправить через AI</button>
            <span class="text-muted">${utterances.length} реплик · ${speakers.length} ораторов</span>
        </div>
        <div class="transcript-list">
            ${utterances.map(u => renderUtteranceItem(u, speakers)).join('')}
        </div>
    `;
    // Двойной клик → редактирование (заглушка)
    panel.querySelectorAll('.utterance-item').forEach(item => {
        item.addEventListener('dblclick', () => {
            toast.info('Редактирование реплик -- следующая итерация');
        });
    });

    // Обработчик кнопки "Транскрибировать" в empty-state
    const emptyState = panel.querySelector('empty-state');
    if (emptyState) {
        emptyState.addEventListener('action', () => startTranscribe(protocol));
    }
}

function renderUtteranceItem(u, speakers) {
    const speaker = speakers.find(s => s.id === u.speaker_id);
    const speakerName = speaker?.display_name || u.speaker_label || '--';
    const speakerColor = speaker?.color || '#888';
    const startTime = formatTimestamp(u.start_sec);
    const conf = u.confidence ?? 1.0;
    const confClass = conf < 0.4 ? 'danger' : conf < 0.7 ? 'warning' : 'success';
    const lowConfIcon = u.low_confidence ? ' <span title="Низкая уверенность" style="color:#f59e0b;">[?]</span>' : '';
    return `
        <div class="utterance-item" data-id="${u.id}" tabindex="0">
            <div class="utterance-meta">
                <span class="speaker-badge" style="background:${speakerColor};">${escapeHtml(speakerName)}</span>
                <span class="timestamp" data-time="${u.start_sec}">${startTime}</span>
                <span class="confidence-bar">
                    <span class="conf-fill conf-${confClass}" style="width:${conf * 100}%"></span>
                </span>
            </div>
            <div class="utterance-text">${escapeHtml(u.text)}${lowConfIcon}</div>
        </div>
    `;
}

function renderScreenshotsTab(rootEl, protocol, screenshots) {
    const panel = rootEl.querySelector('#panel-screenshots');
    panel.innerHTML = `
        <div class="toolbar" style="margin-bottom:16px;">
            <input type="file" id="screenshot-input" accept=".png,.jpg,.jpeg" style="display:none">
            <button class="btn btn-primary" id="btn-upload-screenshot">
                <i class="fa-solid fa-cloud-arrow-up"></i> Загрузить скриншот
            </button>
            <span class="text-muted" style="margin-left:8px;">PNG, JPG до 5 МБ</span>
        </div>
        <div id="screenshots-grid">
            ${screenshots.length === 0 ? `
                <empty-state icon="<i class="fa-regular fa-image"></i>" title="Нет скриншотов" description="Загрузите PNG/JPG или включите Live Mode (Яндекс Телемост)."></empty-state>
            ` : `
                <div class="screenshots-grid">${screenshots.map(s => `
                    <div class="screenshot-card">
                        <img src="/api/v1/hmp/screenshots/${s.id}/image" alt="${s.caption || ''}" loading="lazy">
                        <time>${formatTimestamp(s.timestamp_sec)}</time>
                        ${s.caption ? `<div class="caption">${escapeHtml(s.caption)}</div>` : ''}
                    </div>
                `).join('')}</div>
            `}
        </div>
    `;

    // Handler для загрузки скриншота
    const fileInput = panel.querySelector('#screenshot-input');
    const btnUpload = panel.querySelector('#btn-upload-screenshot');
    if (btnUpload && fileInput) {
        btnUpload.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            try {
                toast.info('Загрузка скриншота...');
                const screenshot = await api.uploadScreenshot(file, protocol.id, {
                    timestamp_sec: protocol.video_player?.currentTime || 0,
                    caption: file.name,
                });
                toast.success(`Скриншот загружен: ${screenshot.id}`);
                // Reload screenshots list
                const updated = await api.listScreenshots(protocol.id);
                renderScreenshotsTab(rootEl, protocol, updated);
            } catch (err) {
                toast.error('Ошибка загрузки: ' + err.message);
            } finally {
                fileInput.value = ''; // reset
            }
        });
    }
}

function renderDecisionsTab(rootEl, protocol) {
    const panel = rootEl.querySelector('#panel-decisions');
    panel.innerHTML = `<empty-state icon="<i class="fa-solid fa-check"></i>" title="Список решений пуст" description="Решения можно добавлять после транскрипции." action-label="Добавить решение"></empty-state>`;
}

function renderTasksTab(rootEl, protocol, actionItems) {
    const panel = rootEl.querySelector('#panel-tasks');
    const items = Array.isArray(actionItems) ? actionItems : [];
    if (!items.length) {
        panel.innerHTML = `<empty-state icon="<i class="fa-regular fa-clipboard"></i>" title="Нет задач" description="Action items появятся после AI-извлечения или ручного добавления." action-label="+ Добавить задачу"></empty-state>`;
        return;
    }
    panel.innerHTML = `<div class="tasks-list">${items.map(t => `
        <div class="task-card">
            <input type="checkbox" ${t.status === 'done' ? 'checked' : ''} data-id="${t.id}">
            <div class="task-content">
                <div class="task-title">${escapeHtml(t.task)}</div>
                <div class="task-meta">
                    ${t.owner ? `<i class="fa-regular fa-user"></i> ${escapeHtml(t.owner)}` : ''}
                    ${t.deadline ? `<i class="fa-regular fa-calendar"></i> ${t.deadline}` : ''}
                    <span class="badge badge-${t.status === 'done' ? 'success' : 'warning'}">${t.status}</span>
                </div>
            </div>
        </div>
    `).join('')}</div>`;
}

function renderSummaryTab(rootEl, protocol, summary) {
    const panel = rootEl.querySelector('#panel-summary');
    if (!summary) {
        panel.innerHTML = `
            <div style="text-align:center; padding:24px;">
                <p class="text-muted">Саммари ещё не сгенерировано</p>
                <button class="btn btn-primary" id="btn-summarize">✨ Создать саммари</button>
            </div>
        `;
        const btn = panel.querySelector('#btn-summarize');
        if (btn) btn.addEventListener('click', () => createSummary(protocol));
        return;
    }
    panel.innerHTML = `
        <div class="summary-header">
            <span class="text-muted">Провайдер: ${summary.provider} · ${summary.tokens_used || '?'} токенов · ${new Date(summary.generated_at).toLocaleString('ru-RU')}</span>
            <button class="btn" id="btn-regenerate">🔄 Регенерировать</button>
        </div>
        <div class="summary-content">${renderMarkdown(summary.text)}</div>
    `;
    panel.querySelector('#btn-regenerate')?.addEventListener('click', () => createSummary(protocol, true));
}

function renderSpeakersTab(rootEl, protocol, speakers, utterances) {
    const panel = rootEl.querySelector('#panel-speakers');
    if (!speakers.length) {
        panel.innerHTML = `<empty-state icon="<i class="fa-solid fa-microphone"></i>" title="Ораторы не найдены" description="Запустите диаризацию чтобы определить ораторов."></empty-state>`;
        return;
    }
    panel.innerHTML = `<div class="speakers-grid">${speakers.map(s => `
        <div class="speaker-card" style="border-left: 4px solid ${s.color || '#888'};">
            <div class="speaker-name">${escapeHtml(s.display_name || s.speaker_label)}</div>
            <div class="speaker-stats">${utterances.filter(u => u.speaker_id === s.id).length} реплик</div>
            ${s.is_user ? '<span class="badge badge-success">Вы</span>' : ''}
        </div>
    `).join('')}</div>`;
}

// ────────────────────────────────────────────────────────────
// Actions
// ────────────────────────────────────────────────────────────

async function startExport(protocol) {
    try {
        toast.info('Запуск экспорта DOCX...');
        const task = await api.startExport({
            protocol_id: protocol.id,
            include_timestamps: true,
            include_screenshots: true,
            include_video_links: true,
            group_by_speaker: true,
            mark_doubtful: true,
            include_summary: true,
            include_decisions: true,
            include_action_items: true,
        });
        toast.success(`Экспорт запущен (task ${task.task_id.slice(0, 8)})`);
        // Polling
        const interval = setInterval(async () => {
            try {
                const status = await api.getExportStatus(task.task_id);
                if (status.status === 'completed') {
                    clearInterval(interval);
                    toast.success('Экспорт готов!');
                    // Auto-download
                    const blob = await api.downloadExport(task.task_id);
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `protocol_${protocol.id}.docx`;
                    a.click();
                    URL.revokeObjectURL(url);
                } else if (status.status === 'failed') {
                    clearInterval(interval);
                    toast.error(`Ошибка экспорта: ${status.error_message}`);
                }
            } catch (err) {
                clearInterval(interval);
                toast.error(`Ошибка: ${err.message}`);
            }
        }, 2000);
    } catch (err) {
        toast.error(`Не удалось запустить экспорт: ${err.message}`);
    }
}

// Global state for transcription tracking
let transcriptionPollInterval = null;
let currentTranscriptionTaskId = null;
let _startTranscribeLock = false;  // E109: lock to prevent double-call
let _pollingActive = false;        // E134: защита от двойного запуска polling

async function checkExistingTranscription(protocol) {
    // E077: Reset state BEFORE checking
    currentTranscriptionTaskId = null;
    if (transcriptionPollInterval) {
        clearInterval(transcriptionPollInterval);
        transcriptionPollInterval = null;
    }

    try {
        const progress = await api.getTranscriptionProgressByProtocol(protocol.id);
        if (progress.status === 'running' || progress.status === 'queued' || progress.status === 'starting') {
            // E077: Try both id and task_id
            const taskId = progress.id || progress.task_id;
            if (!taskId) {
                // Running status but no task_id — stale state
                console.warn('Backend returned running status but no task_id');
                updateTranscribeButton(protocol, 'idle');
                hideProgressBar();
                return false;
            }

            // E078/E080/E083: Verify task with timeout + abort controller
            // AbortController cancels the underlying HTTP request on timeout
            try {
                const controller = new AbortController();
                const verifyPromise = api.getTranscriptionProgress(taskId, { signal: controller.signal });
                const timeoutId = setTimeout(() => {
                    controller.abort();
                }, 3000);
                try {
                    await verifyPromise;
                } finally {
                    clearTimeout(timeoutId);
                }
            } catch (verifyErr) {
                const vErrMsg = (verifyErr.message || '').toLowerCase();
                if (verifyErr.status === 404 || vErrMsg.includes('не найдена')) {
                    // Stale task — reset to idle
                    console.warn('Task is stale (not in registry):', taskId);
                    updateTranscribeButton(protocol, 'idle');
                    hideProgressBar();
                    return false;
                }
                if (verifyErr.name === 'AbortError' || vErrMsg.includes('aborted') || vErrMsg.includes('timeout')) {
                    // E083: Timeout — don't block UI on slow backend
                    console.warn('Verify aborted/timeout, continuing...');
                } else {
                    // Other errors — log but continue
                    console.warn('Verify task failed (continuing):', verifyErr);
                }
            }

            currentTranscriptionTaskId = taskId;
            updateProgressBar(progress);
            updateTranscribeButton(protocol, 'running');
            startProgressPolling(protocol, taskId);
            return true;
        } else if (progress.status === 'unknown' || progress.status === 'transcribing') {
            // E078: Stuck/unknown state — allow user to restart
            updateTranscribeButton(protocol, 'idle');
            // E089: dedupe warning per protocol (not global)
            const warnedKey = `__transcriptionStaleWarned_${protocol.id}`;
            if (!window[warnedKey]) {
                toast.warning('Предыдущая транскрипция была прервана. Можно запустить заново.');
                window[warnedKey] = true;
                setTimeout(() => { window[warnedKey] = false; }, 60000);
            }
            hideProgressBar();
            return false;
        } else {
            // E077: Other statuses (completed, failed, cancelled) → reset to idle
            updateTranscribeButton(protocol, 'idle');
            hideProgressBar();
            return false;
        }
    } catch (e) {
        console.warn('Failed to check transcription status:', e);
    }
    // Default: idle
    updateTranscribeButton(protocol, 'idle');
    hideProgressBar();
    return false;
}

async function startTranscribe(protocol) {
    // E109: Prevent double-click / double-call (3 layers of protection)
    if (transcriptionPollInterval || currentTranscriptionTaskId) {
        toast.warning('Транскрипция уже запущена');
        return;
    }
    if (_startTranscribeLock) {
        console.warn('startTranscribe already in flight');
        return;
    }
    _startTranscribeLock = true;
    try {
        toast.info('Запуск транскрипции...');
        const response = await api.startTranscription({
            protocol_id: protocol.id,
            model: 'large-v3',
            language: 'ru',
        });

        // Get task_id from response
        const taskId = response.id || response.task_id;
        if (!taskId) {
            toast.error('Не получен ID задачи');
            return;
        }

        currentTranscriptionTaskId = taskId;
        toast.success('Транскрипция запущена');

        // Start polling progress
        startProgressPolling(protocol, taskId);

        // Update button to "Stop"
        updateTranscribeButton(protocol, 'running');
    } catch (err) {
        if (err.status === 409) {
            toast.warning('Транскрипция уже идёт');
        } else {
            toast.error(`Ошибка: ${err.message}`);
        }
    } finally {
        // E109: Release lock
        _startTranscribeLock = false;
    }
}

function startProgressPolling(protocol, taskId) {
    // Clear existing interval (E134: предотвращаем двойной polling)
    if (transcriptionPollInterval) {
        clearInterval(transcriptionPollInterval);
        transcriptionPollInterval = null;
    }

    // E134: защита от двойного запуска
    if (currentTranscriptionTaskId === taskId && _pollingActive) {
        console.warn('Polling already active for taskId:', taskId);
        return;
    }
    _pollingActive = true;

    // E134: сброс счётчика для новой задачи
    let _lastUtteranceCount = 0;
    // E134: максимальный start_sec, который уже отрисован
    let _lastRenderedSec = 0;

    // Poll every 2 seconds
    transcriptionPollInterval = setInterval(async () => {
        try {
            const progress = await api.getTranscriptionProgress(taskId);

            // Update UI with progress
            updateProgressBar(progress);

            // E133: подтягиваем только НОВЫЕ реплики через after_sec
            const segCount = progress.segments_count || 0;
            if (segCount > _lastUtteranceCount) {
                try {
                    // E133: after_sec — запрос вернёт только новые
                    // E134: limit=500 (вместо 1000, чтобы не получать 422)
                    const newOnes = await api.listUtterances(protocol.id, {
                        limit: 500,
                        after_sec: _lastRenderedSec,
                    });
                    const items = Array.isArray(newOnes)
                        ? newOnes
                        : (newOnes && newOnes.items) || [];
                    if (items.length > 0) {
                        await appendUtteranceItems(protocol.id, items);
                        // Обновляем lastRenderedSec до максимального
                        const maxSec = Math.max(
                            ...items.map(u => parseFloat(u.start_sec || 0))
                        );
                        if (maxSec > _lastRenderedSec) {
                            _lastRenderedSec = maxSec;
                        }
                        _lastUtteranceCount = Math.max(_lastUtteranceCount, items.length);
                    }
                } catch (e) {
                    console.warn('Failed to fetch utterances:', e);
                }
            }

            // Check if done
            if (['completed', 'failed', 'cancelled', 'finished', 'done']
                .includes(progress.status?.toLowerCase())) {
                clearInterval(transcriptionPollInterval);
                transcriptionPollInterval = null;
                currentTranscriptionTaskId = null;
                _pollingActive = false;
                updateTranscribeButton(protocol, 'idle');
                hideProgressBar();

                // E134: финальная полная загрузка (на случай если что-то пропустили)
                try {
                    const finalList = await api.listUtterances(protocol.id, {
                        limit: 500,
                        after_sec: 0,
                    });
                    const finalItems = Array.isArray(finalList)
                        ? finalList
                        : (finalList && finalList.items) || [];
                    if (finalItems.length > 0) {
                        const panel = document.getElementById('panel-transcript');
                        if (panel && typeof renderUtteranceItem === 'function') {
                            panel.innerHTML = `
                                <div class="transcript-toolbar">
                                    <span class="text-muted">${finalItems.length} реплик</span>
                                </div>
                                <div class="transcript-list">
                                    ${finalItems.map(u => renderUtteranceItem(u, [])).join('')}
                                </div>
                            `;
                        }
                    }
                } catch (e) {
                    console.warn('Final utterances fetch failed:', e);
                }

                if (progress.status === 'completed' || progress.status === 'finished' || progress.status === 'done') {
                    toast.success('Транскрипция завершена!');
                } else if (progress.status === 'failed') {
                    toast.error(`Транскрипция провалилась: ${progress.message || ''}`);
                } else if (progress.status === 'cancelled') {
                    toast.warning('Транскрипция отменена');
                }
            }
        } catch (e) {
            console.warn('Progress poll error:', e);
        }
    }, 2000);
}

async function appendUtteranceItems(protocolId, items) {
    """E133: append-only — добавляет новые реплики без перерисовки списка."""
    const panel = document.getElementById('panel-transcript');
    if (!panel || typeof renderUtteranceItem !== 'function') return;

    let list = panel.querySelector('.transcript-list');
    if (!list) {
        // Первая инициализация — создаём структуру
        const toolbar = panel.querySelector('.transcript-toolbar');
        panel.innerHTML = `
            <div class="transcript-toolbar">
                <span class="text-muted">0 реплик</span>
            </div>
            <div class="transcript-list"></div>
        `;
        list = panel.querySelector('.transcript-list');
    }

    // Запоминаем был ли пользователь внизу
    const atBottom =
        panel.scrollHeight - panel.scrollTop - panel.clientHeight < 50;

    // Append-only — никаких innerHTML на весь список
    for (const u of items) {
        const html = renderUtteranceItem(u, []);
        list.insertAdjacentHTML('beforeend', html);
    }

    // Обновляем счётчик в toolbar
    const counter = panel.querySelector('.transcript-toolbar .text-muted');
    if (counter) {
        const total = list.children.length;
        counter.textContent = `${total} реплик`;
    }

    // Автоскролл, если был внизу
    if (atBottom) {
        panel.scrollTop = panel.scrollHeight;
    }
}


function updateProgressBar(progress) {
    // E113: Show human-readable message + percent
    let bar = document.getElementById('transcribe-progress');
    const pct = progress.progress_percent !== undefined ? progress.progress_percent : (progress.progress || 0);
    const msg = progress.message || (pct < 5 ? 'Инициализация...' : pct < 95 ? 'Обработка аудио...' : 'Финализация...');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'transcribe-progress';
        bar.className = 'transcribe-progress';
        bar.innerHTML = `
            <div class="progress-info">
                <span class="progress-status">${msg}</span>
                <span class="progress-percent">${pct}%</span>
            </div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${pct}%"></div>
            </div>
        `;
        document.body.appendChild(bar);
    }
    bar.querySelector('.progress-status').textContent = msg;
    bar.querySelector('.progress-percent').textContent = `${pct}%`;
    bar.querySelector('.progress-bar-fill').style.width = `${pct}%`;
}

function hideProgressBar() {
    const bar = document.getElementById('transcribe-progress');
    if (bar) bar.remove();
}

function updateTranscribeButton(protocol, state) {
    const btn = document.getElementById('btn-transcribe');
    if (!btn) return;

    const bottomBtn = document.getElementById('btn-transcribe-bottom');

    if (state === 'running') {
        btn.innerHTML = '<i class="fa-solid fa-stop"></i> Остановить транскрипцию';
        btn.classList.add('btn-danger');
        btn.classList.remove('btn-primary');
        btn.onclick = () => confirmCancelTranscribe(protocol);

        if (bottomBtn) {
            bottomBtn.innerHTML = '<i class="fa-solid fa-stop"></i> Отмен...';
            bottomBtn.disabled = true;
        }
    } else {
        btn.innerHTML = '<i class="fa-solid fa-play"></i> Транскрибировать';
        btn.classList.add('btn-primary');
        btn.classList.remove('btn-danger');
        btn.onclick = () => startTranscribe(protocol);

        if (bottomBtn) {
            bottomBtn.innerHTML = '<i class="fa-solid fa-play"></i> Транскрибировать';
            bottomBtn.disabled = false;
        }
    }
}

async function confirmCancelTranscribe(protocol) {
    // E077: Use try/finally to ALWAYS reset state
    const taskIdToCancel = currentTranscriptionTaskId;

    if (!taskIdToCancel) {
        toast.warning('Нет активной задачи');
        updateTranscribeButton(protocol, 'idle');
        hideProgressBar();
        return;
    }

    if (!confirm('Прервать транскрипцию? Прогресс будет потерян.')) {
        return;
    }

    try {
        await api.cancelTranscription(taskIdToCancel);
        toast.warning('Транскрипция прервана');
    } catch (err) {
        // E077: Special handling for "task not found" - it's stale state
        const errMsg = (err.message || '').toLowerCase();
        if (errMsg.includes('не найдена') || errMsg.includes('not found') || err.status === 404) {
            toast.warning('Задача уже завершена или не существует');
        } else {
            toast.error(`Не удалось отменить: ${err.message}`);
        }
    } finally {
        // E077: ALWAYS reset state in finally block
        if (transcriptionPollInterval) {
            clearInterval(transcriptionPollInterval);
            transcriptionPollInterval = null;
        }
        currentTranscriptionTaskId = null;
        updateTranscribeButton(protocol, 'idle');
        hideProgressBar();
    }
}

async function createSummary(protocol, regenerate = false) {
    try {
        toast.info(regenerate ? 'Регенерация саммари...' : 'Создание саммари...');
        const summary = await api.summarize({
            protocol_id: protocol.id,
            provider: 'hermes',
            style: 'structured',
            max_words: 500,
        });
        toast.success('Саммари готово');
        // Reload tab
        renderSummaryTab(document, protocol, summary);
    } catch (err) {
        toast.error(`Ошибка: ${err.message}`);
    }
}

// ────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────

function setupHotkeys(protocolId) {
    const handler = (e) => {
        // Не перехватываем если фокус в input/textarea (кроме Space)
        if (e.key === ' ' && ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
            return;
        }
        if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;

        if (e.key === 'Escape') {
            window.location.hash = '#/';
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            // Trigger export
            document.getElementById('btn-export')?.click();
        }
    };
    document.addEventListener('keydown', handler);
    // Cleanup when navigating away
    window.addEventListener('hashchange', () => {
        document.removeEventListener('keydown', handler);
    }, { once: true });
}

function formatTimestamp(seconds) {
    if (!seconds) return '0:00';
    return formatTime(seconds);
}

function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '0:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
}

function formatDuration(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h} ч ${m} мин`;
    return `${m} мин`;
}

function formatFileSize(bytes) {
    if (!bytes || bytes === 0) return '--';
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    let size = bytes;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit++;
    }
    return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatPath(fullPath) {
    if (!fullPath) return '';
    const sep = fullPath.includes('/') ? '/' : '\\';
    const parts = fullPath.split(sep).filter(p => p);
    if (parts.length <= 3) return fullPath;
    const last = parts.slice(-2).join(sep);
    return '...' + sep + last;
}

function getStatusBadge(status) {
    const map = {
        ready: { type: 'success', label: 'Готов' },
        transcribed: { type: 'success', label: 'Готов' },
        loaded: { type: 'warning', label: 'Загружен' },
        transcribing: { type: 'warning', label: 'Транскрибируется' },
        diarizing: { type: 'warning', label: 'Диаризация' },
        failed: { type: 'danger', label: 'Ошибка' },
    };
    return map[status] || { type: 'warning', label: status };
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}

function renderMarkdown(text) {
    // Простой Markdown renderer (paragraphs, **bold**, *italic*, # headers)
    if (!text) return '';
    return escapeHtml(text)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/^### (.+)$/gm, '<h4>$1</h4>')
        .replace(/^## (.+)$/gm, '<h3>$1</h3>')
        .replace(/^# (.+)$/gm, '<h2>$1</h2>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>');
}



async function confirmDeleteProtocol(protocol) {
    // Step 1: Show clear warning about what will be deleted
    const fileCount = protocol.audio_file ? 1 : 0;
    const warning = `Удалить протокол "${protocol.title || 'Без названия'}"?\n\n` +
        `Будет удалено ВСЁ:\n` +
        `  • Сам протокол\n` +
        `  • Все реплики и таймкоды\n` +
        `  • Саммари и решения\n` +
        `  • Скриншоты\n` +
        `  • Файл видео\n\n` +
        `Это действие нельзя отменить!`;

    if (!confirm(warning)) {
        return;
    }

    // Step 2: Hard delete via backend
    try {
        const result = await api.deleteProtocolPermanent(protocol.id);
        const counts = result.deleted_counts || {};
        const total = Object.values(counts).reduce((a, b) => a + b, 0);
        toast.success(`Протокол удалён. Удалено записей: ${total}`);
        setTimeout(() => {
            window.location.hash = '#/';
        }, 1000);
    } catch (err) {
        toast.error('Ошибка удаления: ' + err.message);
    }
}
