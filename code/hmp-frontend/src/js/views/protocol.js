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
// E180: удалён импорт './components/video-player.js' — старый custom element
// дублировал плеер (E175). Используется только initMediaPlayer().
import './components/tab-bar.js';
import './components/modal.js';
import './components/empty-state.js';

// Don't await on top level - this can break module loading
// Instead, open DB lazily on first call to storage
console.log('protocol.js loaded');
export async function renderProtocolDetail(rootEl, protocolId) {
    rootEl.innerHTML = '<div class="loading"><div class="spinner"></div> Загрузка протокола...</div>';

    let protocol, utterances, utterancesRaw, speakers, summary, tags, actionItems, screenshots, decisions;
    // US-053: helper to safely cast any value to array
    const safeArray = (x) => Array.isArray(x) ? x : [];

    // US-047: Сначала пробуем загрузить с сервера
    let serverSuccess = false;
    try {
        [protocol, utterancesRaw, speakers, summary, tags, actionItems, screenshots, decisions] = await Promise.all([
            api.getProtocol(protocolId),
            // E138: limit=500 чтобы получить все реплики (вместо 100)
            api.listUtterances(protocolId, { limit: 500 }).catch(() => []),
            api.listSpeakers(protocolId).catch(() => []),
            api.getSummary(protocolId).catch(() => null),
            api.listTags(protocolId).catch(() => []),
            api.listActionItems(protocolId).catch(() => []),
            api.listScreenshots ? api.listScreenshots(protocolId).catch(() => []) : Promise.resolve([]),
            api.listDecisions ? api.listDecisions(protocolId).catch(() => []) : Promise.resolve([]),
        ]);

        // E138: API возвращает {total, skip, limit, items}, извлекаем items
        if (utterancesRaw && typeof utterancesRaw === 'object' && !Array.isArray(utterancesRaw)) {
            utterances = Array.isArray(utterancesRaw.items) ? utterancesRaw.items : [];
        } else {
            utterances = safeArray(utterancesRaw);
        }

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

    // E138: если есть готовые реплики — сразу активируем вкладку транскрипта
    if (Array.isArray(utterances) && utterances.length > 0) {
        const transcriptTab = document.querySelector('[aria-controls="panel-transcript"]');
        if (transcriptTab) transcriptTab.click();
    }

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
                <button class="btn-tiny btn-edit-protocol" id="btn-edit-protocol-meta" title="Редактировать атрибуты протокола">✏️ Редактировать</button>
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
            ${protocol.location ? `<span><i class="fa-solid fa-location-dot"></i> ${escapeHtml(protocol.location)}</span>` : '<span><i class="fa-solid fa-location-dot"></i> —</span>'}
            ${protocol.chair ? `<span><i class="fa-regular fa-user"></i> ${escapeHtml(protocol.chair)}</span>` : '<span><i class="fa-regular fa-user"></i> —</span>'}
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

                ${protocol.audio_file ? `
                    <div id="media-player-container" data-audio-file-id="${protocol.audio_file.id}" data-filename="${escapeHtml(protocol.audio_file.filename || '')}" data-mime="${escapeHtml(protocol.audio_file.mime_type || '')}">
                        <video id="media-video" controls preload="metadata" style="width:100%; max-height:60vh; background:#000; border-radius:6px;"></video>
                    </div>
                ` : ''}

        <tab-bar id="protocol-tabs">
            <button role="tab" id="tab-transcript" aria-controls="panel-transcript"><i class="fa-regular fa-note-sticky"></i> Транскрипция</button>
            <button role="tab" id="tab-screenshots" aria-controls="panel-screenshots"><i class="fa-regular fa-image"></i>️ Скриншоты</button>
            <button role="tab" id="tab-decisions" aria-controls="panel-decisions"><i class="fa-solid fa-check"></i> Решения <span id="decisions-badge" class="tab-badge"></span></button>
            <button role="tab" id="tab-important" aria-controls="panel-important"><i class="fa-solid fa-star"></i> Важное <span id="important-badge" class="tab-badge"></span></button>
            <button role="tab" id="tab-tasks" aria-controls="panel-tasks"><i class="fa-regular fa-clipboard"></i> Задачи</button>
            <button role="tab" id="tab-summary" aria-controls="panel-summary"><i class="fa-regular fa-file-lines"></i> Саммари</button>
            <button role="tab" id="tab-speakers" aria-controls="panel-speakers"><i class="fa-solid fa-microphone"></i> Ораторы</button>
        </tab-bar>

        <div id="panels">
            <div role="tabpanel" id="panel-transcript" aria-labelledby="tab-transcript" hidden></div>
            <div role="tabpanel" id="panel-screenshots" aria-labelledby="tab-screenshots" hidden></div>
            <div role="tabpanel" id="panel-decisions" aria-labelledby="tab-decisions" hidden></div>
            <div role="tabpanel" id="panel-important" aria-labelledby="tab-important" hidden></div>
            <div role="tabpanel" id="panel-tasks" aria-labelledby="tab-tasks" hidden></div>
            <div role="tabpanel" id="panel-summary" aria-labelledby="tab-summary" hidden></div>
            <div role="tabpanel" id="panel-speakers" aria-labelledby="tab-speakers" hidden></div>
        </div>
    `;

    // Video player
    // Safe array helpers
    const safeArray = (arr) => Array.isArray(arr) ? arr : [];
    const safeFilter = (arr, predicate) => safeArray(arr).filter(predicate);

    // E175: Старый дублированный плеер (video-player) удалён —
    // теперь используется initMediaPlayer() ниже, который создаёт
    // один плеер с поддержкой audio и video.
    // E175: используется initMediaPlayer() — не дублируем.

    // Инициализация табов (нужно вызвать addTab для TabBar компонента)
    const tabBar = rootEl.querySelector('tab-bar');
    tabBar.tabs = [
        { id: 'transcript', label: '<i class="fa-regular fa-note-sticky"></i> Транскрипция', badge: utterances.length },
        { id: 'screenshots', label: '<i class="fa-regular fa-image"></i> Скриншоты', badge: screenshots.length },
        { id: 'decisions', label: '<i class="fa-solid fa-check"></i> Решения', badge: decisions.length },
        // E234: добавлена вкладка "Важное"
        { id: 'important', label: '<i class="fa-solid fa-star"></i> Важное', badge: safeFilter(utterances, u => u.important).length },
        { id: 'tasks', label: '<i class="fa-regular fa-clipboard"></i> Задачи', badge: safeFilter(actionItems, a => a.status === 'open').length },
        { id: 'summary', label: '<i class="fa-regular fa-file-lines"></i> Саммари', badge: summary ? 1 : 0 },
        { id: 'speakers', label: '<i class="fa-solid fa-microphone"></i> Ораторы', badge: speakers.length },
    ];
    tabBar.render();
    tabBar.attachEvents();
    tabBar.activateTab('transcript', true);

    tabBar.onChange(tabId => {
        switchTab(tabId, protocol, utterances, speakers, summary, tags, actionItems);
        // E235: перерисовываем содержимое при переключении.
        // Панели important/decisions рендерятся один раз при загрузке —
        // после пометки ☆/⚖️ данные устаревают, и пользователь видит старый список.
        // Здесь перерисовываем из in-memory utterances (они мутируются в обработчиках).
        if (tabId === 'important') {
            renderImportantTab(rootEl, protocol, utterances);
        } else if (tabId === 'decisions') {
            renderDecisionsTab(rootEl, protocol);
        }
    });

    // Рендерим все панели (но показываем только активную)
    renderTranscriptTab(rootEl, protocol, utterances, speakers).catch(e =>
        console.warn('renderTranscriptTab:', e),
    );
    // E233: глобальная ссылка на utterances — используется в appendUtteranceItems
    // (у которого нет closure utterances), для wireImportantButtons и badge-счётчика.
    window._currentUtterances = utterances || [];

    // E242: wireEditMetadataBtn — открывает модальное окно редактирования
    wireEditMetadataBtn(protocol);

    renderScreenshotsTab(rootEl, protocol, []);
    renderDecisionsTab(rootEl, protocol);
    renderImportantTab(rootEl, protocol, utterances);
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

    // E170: Инициализация аудио/видео плеера + переход по таймкоду
    initMediaPlayer(rootEl, protocol);

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

// E231: модульные wire* функции (для appendUtteranceItems)
// Каждая берёт utterances из closure через параметр

function wireImportantButtons(utterances, panel) {
    // E231/E233: fallback на globalThis — appendUtteranceItems не имеет closure utterances
    if (!utterances || !panel) {
        utterances = window._currentUtterances || [];
        panel = panel || document.getElementById('panel-transcript');
        if (!panel) return;
    }
    panel.querySelectorAll('.btn-mark-important:not([data-wired])').forEach(btn => {
        btn.dataset.wired = '1';
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const utteranceId = btn.dataset.utteranceId;
            try {
                btn.disabled = true;
                await api.toggleUtteranceImportant(utteranceId, true);
                const u = utterances.find(x => x.id === utteranceId);
                if (u) u.important = true;

                btn.classList.remove('btn-mark-important');
                btn.classList.add('btn-important-marked');
                btn.dataset.wired = '';
                btn.title = "Снять закладку 'Важное'";
                btn.innerHTML = '⭐';

                const item = btn.closest('.utterance-item');
                if (item) {
                    item.classList.add('is-important');
                    const textEl = item.querySelector('.utterance-text');
                    if (textEl && !textEl.querySelector('.important-mark')) {
                        textEl.insertAdjacentHTML(
                            'beforeend',
                            ' <span class="important-mark" title="Важное">⭐</span>'
                        );
                    }
                }
                toast.success('⭐ Добавлено в "Важное"');
                wireImportantButtons(utterances, panel);
                // E235: обновляем badge в табе сразу после пометки
                const _badge = document.getElementById('important-badge');
                if (_badge && utterances) {
                    const cnt = utterances.filter(x => x.important).length;
                    _badge.textContent = cnt > 0 ? `(${cnt})` : '';
                }
            } catch (err) {
                console.error('[important] create failed:', err);
                toast.error('Ошибка: ' + (err.message || err));
                btn.disabled = false;
            }
        });
    });

    panel.querySelectorAll('.btn-important-marked:not([data-wired])').forEach(btn => {
        btn.dataset.wired = '1';
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const utteranceId = btn.dataset.utteranceId;
            try {
                btn.disabled = true;
                await api.toggleUtteranceImportant(utteranceId, false);
                const u = utterances.find(x => x.id === utteranceId);
                if (u) u.important = false;

                btn.classList.remove('btn-important-marked');
                btn.classList.add('btn-mark-important');
                btn.dataset.wired = '';
                btn.title = "Пометить как 'Важное'";
                btn.innerHTML = '☆';

                const item = btn.closest('.utterance-item');
                if (item) {
                    item.classList.remove('is-important');
                    const textEl = item.querySelector('.important-mark');
                    if (textEl) textEl.remove();
                }
                toast.info('Закладка снята');
                wireImportantButtons(utterances, panel);
                // E235: обновляем badge при снятии
                const _badge2 = document.getElementById('important-badge');
                if (_badge2 && utterances) {
                    const cnt = utterances.filter(x => x.important).length;
                    _badge2.textContent = cnt > 0 ? `(${cnt})` : '';
                }
            } catch (err) {
                console.error('[important] remove failed:', err);
                toast.error('Ошибка: ' + (err.message || err));
                btn.disabled = false;
            }
        });
    });
}

// E242: модальное окно для редактирования атрибутов протокола
function wireEditMetadataBtn(protocol) {
    const btn = document.getElementById('btn-edit-protocol-meta');
    if (!btn || btn.dataset.wired) return;
    btn.dataset.wired = '1';
    btn.addEventListener('click', () => openEditProtocolModal(protocol));
}

// E242: открывает модалку со всеми атрибутами протокола
function openEditProtocolModal(protocol) {
    // Удаляем предыдущую если есть
    const existing = document.getElementById('edit-protocol-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'edit-protocol-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal-dialog">
            <div class="modal-header">
                <h3>✏️ Редактировать протокол</h3>
                <button class="modal-close" type="button" aria-label="Закрыть">×</button>
            </div>
            <form id="edit-protocol-form" class="modal-body">
                <div class="form-group">
                    <label>Название *</label>
                    <input type="text" name="title" required maxlength="255"
                           value="${escapeHtml(protocol.title || '')}" autofocus>
                </div>
                <div class="form-group">
                    <label>Дата</label>
                    <input type="date" name="date"
                           value="${protocol.date ? String(protocol.date).slice(0, 10) : ''}">
                </div>
                <div class="form-group">
                    <label>Председатель</label>
                    <input type="text" name="chair" maxlength="100"
                           value="${escapeHtml(protocol.chair || '')}"
                           placeholder="Иванов И.И.">
                </div>
                <div class="form-group">
                    <label>Место проведения</label>
                    <input type="text" name="location" maxlength="255"
                           value="${escapeHtml(protocol.location || '')}"
                           placeholder="Москва, оф. 404">
                </div>
                <div class="form-group">
                    <label>Повестка дня</label>
                    <textarea name="agenda" rows="4"
                              placeholder="1. Бюджет Q4&#10;2. Roadmap&#10;3. Команда">${escapeHtml(protocol.agenda || '')}</textarea>
                </div>
                <div class="form-group">
                    <label>Язык</label>
                    <select name="language">
                        <option value="ru" ${(protocol.language || 'ru') === 'ru' ? 'selected' : ''}>Русский</option>
                        <option value="en" ${protocol.language === 'en' ? 'selected' : ''}>English</option>
                        <option value="de" ${protocol.language === 'de' ? 'selected' : ''}>Deutsch</option>
                        <option value="es" ${protocol.language === 'es' ? 'selected' : ''}>Español</option>
                        <option value="fr" ${protocol.language === 'fr' ? 'selected' : ''}>Français</option>
                    </select>
                </div>
                <div id="edit-protocol-error" class="form-error" hidden></div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-cancel" data-action="cancel">Отмена</button>
                    <button type="submit" class="btn btn-primary" data-action="save">
                        <i class="fa-regular fa-floppy-disk"></i> Сохранить
                    </button>
                </div>
            </form>
        </div>
    `;
    document.body.appendChild(modal);

    // Закрытие
    const close = () => modal.remove();
    modal.querySelector('.modal-close').addEventListener('click', close);
    modal.querySelector('[data-action="cancel"]').addEventListener('click', close);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) close();
    });

    // Submit
    modal.querySelector('#edit-protocol-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const errEl = modal.querySelector('#edit-protocol-error');
        const submitBtn = modal.querySelector('[data-action="save"]');

        const changes = {
            title: form.title.value.trim(),
            chair: form.chair.value.trim() || null,
            location: form.location.value.trim() || null,
            agenda: form.agenda.value.trim() || null,
            language: form.language.value,
        };
        // date — только если изменился
        const newDate = form.date.value || null;
        const oldDate = protocol.date ? String(protocol.date).slice(0, 10) : null;
        if (newDate !== oldDate) changes.date = newDate;

        // Проверка — были ли изменения
        let hasChanges = false;
        for (const k of Object.keys(changes)) {
            const newVal = changes[k];
            const oldVal = (k === 'date' ? oldDate : protocol[k]) || '';
            if (newVal !== oldVal) {
                hasChanges = true;
                break;
            }
        }
        if (!hasChanges) {
            close();
            return;
        }

        errEl.hidden = true;
        submitBtn.disabled = true;
        submitBtn.textContent = '⏳ Сохранение...';

        try {
            const updated = await api.updateProtocol(protocol.id, changes);
            // E242: обновляем in-memory протокол и UI
            Object.assign(protocol, updated);
            updateProtocolHeader(protocol);

            toast.success('✅ Сохранено');
            close();
        } catch (err) {
            console.error('[edit-protocol] failed:', err);
            errEl.textContent = `Ошибка: ${err.message || err}`;
            errEl.hidden = false;
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fa-regular fa-floppy-disk"></i> Сохранить';
        }
    });
}

// E242: обновляет header без перезагрузки
function updateProtocolHeader(protocol) {
    const rootEl = document.getElementById('view-root');
    if (!rootEl) return;

    // Заголовок
    const h1 = rootEl.querySelector('.protocol-header h1');
    if (h1) h1.textContent = protocol.title || '';

    // Meta-строка
    const meta = rootEl.querySelector('.protocol-meta');
    if (!meta) return;

    const dateStr = protocol.date ? String(protocol.date).slice(0, 10) : '';
    meta.innerHTML = `
        <span><i class="fa-regular fa-calendar"></i> ${dateStr || 'Дата не указана'}</span>
        <span><i class="fa-solid fa-location-dot"></i> ${escapeHtml(protocol.location || '—')}</span>
        <span><i class="fa-regular fa-user"></i> ${escapeHtml(protocol.chair || '—')}</span>
        ${protocol.duration_sec ? `<span><i class="fa-regular fa-clock"></i> ${formatDuration(protocol.duration_sec)}</span>` : ''}
        ${protocol.wer_quality !== null ? `<span><i class="fa-solid fa-chart-column"></i> WER: ${protocol.wer_quality}%</span>` : ''}
    `;

    // Если есть вкладка протокола — перерисовать summary/decisions/etc.
    // (пока не трогаем, т.к. там отображается язык, и он изменится через updateProtocol)
}

async function renderTranscriptTab(rootEl, protocol, utterances, speakers) {
    const panel = rootEl.querySelector('#panel-transcript');
    // E138: убираем hidden чтобы панель была видна
    if (panel) panel.removeAttribute('hidden');

    // E146: Загружаем decisions для отображения значка ⚖️
    let decisionIds = new Set();
    try {
        api.listDecisions(protocol.id).then(decisions => {
            const list = panel.querySelector('.transcript-list');
            if (!list) return;
            decisionIds = new Set(decisions
                .filter(d => d.source_utterance_id)
                .map(d => d.source_utterance_id));
            // E146: подсвечиваем решения
            for (const d of decisions) {
                if (d.source_utterance_id) {
                    const item = list.querySelector(`[data-id="${d.source_utterance_id}"]`);
                    if (item) item.classList.add('is-decision');
                }
            }
        });
    } catch (e) { console.warn('Failed to load decisions:', e); }

    if (!utterances.length) {
        panel.innerHTML = `<empty-state icon="<i class="fa-regular fa-note-sticky"></i>" title="Нет транскрипции" description="Запустите транскрипцию чтобы получить распознанный текст." action-label="<i class="fa-solid fa-play"></i> Транскрибировать"></empty-state>`;
        return;
    }
    panel.innerHTML = `
        <div class="transcript-toolbar">
            <button class="btn" id="btn-upgrade-weak" title="E162: улучшить слабые сегменты большой моделью">🚀 Улучшить слабые</button>
            <button class="btn" id="btn-check-all-grammar" title="E154: проверить грамматику всех реплик">🔍 Проверить всё</button>
            <button class="btn" id="btn-apply-all-corrections" title="E154: применить все исправления сразу" style="display:none;">✏️ Применить всё</button>
            <button class="btn" id="btn-cleanup-ai">✨ Исправить через AI</button>
            <button class="btn" id="btn-pause-transcription" title="E150: поставить на паузу (сохраняет прогресс, можно продолжить позже)">⏸ Пауза</button>
            <button class="btn" id="btn-resume-transcription" title="E150: продолжить приостановленную транскрибацию" style="display:none;">▶ Продолжить</button>
            <button class="btn" id="btn-diarize"><i class="fa-solid fa-users"></i> Диаризация</button>
            <button class="btn" id="btn-extract-decisions"><i class="fa-solid fa-magnifying-glass-chart"></i> 🤖 Найти решения</button>
            <select id="select-protocol-language" class="select-tiny" title="E148: Язык совещания">
                <option value="ru" ${protocol.language === 'ru' ? 'selected' : ''}>🇷🇺 Русский</option>
                <option value="en" ${protocol.language === 'en' ? 'selected' : ''}>🇬🇧 English</option>
                <option value="de" ${protocol.language === 'de' ? 'selected' : ''}>🇩🇪 Deutsch</option>
                <option value="es" ${protocol.language === 'es' ? 'selected' : ''}>🇪🇸 Español</option>
                <option value="fr" ${protocol.language === 'fr' ? 'selected' : ''}>🇫🇷 Français</option>
                <option value="zh" ${protocol.language === 'zh' ? 'selected' : ''}>🇨🇳 中文</option>
            </select>
            <select id="select-translation-language" class="select-tiny" title="E149: Целевой язык перевода">
                <option value="">— без перевода —</option>
                <option value="en" ${protocol.translation_language === 'en' ? 'selected' : ''}>🌍 → EN</option>
                <option value="ru" ${protocol.translation_language === 'ru' ? 'selected' : ''}>🌍 → RU</option>
                <option value="de" ${protocol.translation_language === 'de' ? 'selected' : ''}>🌍 → DE</option>
                <option value="es" ${protocol.translation_language === 'es' ? 'selected' : ''}>🌍 → ES</option>
                <option value="fr" ${protocol.translation_language === 'fr' ? 'selected' : ''}>🌍 → FR</option>
            </select>
            <button class="btn" id="btn-translate"><i class="fa-solid fa-language"></i> 🌐 Перевести</button>
            <span class="text-muted" id="transcript-counter">${utterances.length} реплик · ${speakers.length} ораторов</span>
        </div>
        <div class="transcript-list">
            ${utterances.map(u => renderUtteranceItem(u, speakers, null, decisionIds)).join('')}
        </div>
    `;

    // E171: Привязываем обработчик пометки решения (без outerHTML для надёжности)
    const wireDecisionButtons = () => {
        panel.querySelectorAll('.btn-mark-decision:not([data-wired])').forEach(btn => {
            btn.dataset.wired = '1';
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                // E245: защита от двойного клика — если уже marked, ничего не делаем
                if (btn.dataset.marked === '1' || btn.disabled) {
                    console.warn('[decision] already marked, ignoring click');
                    return;
                }
                const utteranceId = btn.dataset.utteranceId;
                const utterance = utterances.find(u => u.id === utteranceId);
                if (!utterance) {
                    console.warn('[decision] utterance not found:', utteranceId);
                    return;
                }

                try {
                    btn.disabled = true;
                    const decision = await api.createDecision({
                        protocol_id: protocol.id,
                        text: utterance.text || '',
                        source_utterance_id: utterance.id,
                        priority: 'medium',
                        source: 'transcript',
                    });

                    // E245: сохраняем decisionId на кнопке чтобы знать что удалять
                    btn.dataset.decisionId = decision.id;

                    // E171: переключаем классы вместо outerHTML
                    btn.classList.remove('btn-mark-decision');
                    btn.classList.add('btn-decision-marked');
                    btn.dataset.marked = '1';
                    btn.disabled = false;
                    btn.title = 'Снять пометку решения';
                    btn.innerHTML = '⚖️';

                    // Подсветить реплику и добавить ⚖️
                    const item = btn.closest('.utterance-item');
                    if (item) {
                        item.classList.add('is-decision');
                        const textEl = item.querySelector('.utterance-text');
                        if (textEl && !textEl.querySelector('.decision-mark')) {
                            textEl.insertAdjacentHTML(
                                'beforeend',
                                ' <span class="decision-mark" title="Решение">⚖️</span>'
                            );
                        }
                    }
                    toast.success('Помечено как решение');
                    // E171: перепривязываем — теперь у этой кнопки btn-decision-marked
                    wireDecisionButtons();
                    // E245: обновляем badge решений в табе
                    updateDecisionsBadge(panel);
                } catch (err) {
                    console.error('[decision] create failed:', err);
                    toast.error(`Не удалось: ${err.message || err}`);
                    btn.disabled = false;
                }
            });
        });

        panel.querySelectorAll('.btn-decision-marked:not([data-wired])').forEach(btn => {
            btn.dataset.wired = '1';
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                // E245: защита от двойного клика
                if (btn.disabled) {
                    console.warn('[decision] already processing, ignoring click');
                    return;
                }
                const utteranceId = btn.dataset.utteranceId;
                try {
                    btn.disabled = true;
                    // E245: используем кешированный decisionId — не делаем лишний GET
                    const decisionId = btn.dataset.decisionId;
                    if (decisionId) {
                        await api.deleteDecision(decisionId);
                    } else {
                        // fallback: ищем через list (старая логика)
                        const decisions = await api.listDecisions(protocol.id);
                        const decision = decisions.find(d => d.source_utterance_id === utteranceId);
                        if (decision) {
                            await api.deleteDecision(decision.id);
                        } else {
                            console.warn('[decision] no decisionId and not found in list');
                        }
                    }
                    // E171: переключаем обратно через классы
                    btn.classList.remove('btn-decision-marked');
                    btn.classList.add('btn-mark-decision');
                    btn.dataset.wired = '';
                    btn.dataset.marked = '';
                    delete btn.dataset.decisionId;
                    btn.disabled = false;
                    btn.title = 'Пометить как решение';
                    btn.innerHTML = '＋ ⚖️';

                    const item = btn.closest('.utterance-item');
                    if (item) {
                        item.classList.remove('is-decision');
                        const mark = item.querySelector('.decision-mark');
                        if (mark) mark.remove();
                    }
                    toast.info('Пометка снята');
                    // E171: перепривязываем
                    wireDecisionButtons();
                    // E245: обновляем badge
                    updateDecisionsBadge(panel);
                } catch (err) {
                    console.error('[decision] delete failed:', err);
                    toast.error(`Не удалось: ${err.message || err}`);
                    btn.disabled = false;
                }
            });
        });
    }

    // E245: обновляет badge "Решения" в табе
    updateDecisionsBadge(panel);

    // E171: привязываем обработчики пометки решений
    wireDecisionButtons();   // E248: добавлен вызов — был потерян

    // E231: wireImportantButtons вынесена в модульную функцию (выше) — вызываем её
    wireImportantButtons(utterances, panel);

    // E154: Inline-edit + grammar/spelling check
    const wireGrammarAndEditButtons = () => {
        // Edit button: заменяет текст на textarea
        panel.querySelectorAll('.btn-edit-utterance').forEach(btn => {
            if (btn._wired) return;
            btn._wired = true;
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const utteranceId = btn.dataset.utteranceId;
                const item = panel.querySelector(`[data-id="${utteranceId}"]`);
                const textEl = item?.querySelector('.utterance-text');
                if (!item || !textEl) return;
                const originalText = textEl.dataset.original || textEl.textContent.trim();

                // Создаём textarea
                const editor = document.createElement('textarea');
                editor.className = 'utterance-editor';
                editor.value = originalText;
                editor.rows = Math.max(2, Math.ceil(originalText.length / 60));

                const saveBtn = document.createElement('button');
                saveBtn.className = 'btn-tiny btn-save-utterance';
                saveBtn.textContent = '💾 Сохранить';
                saveBtn.dataset.utteranceId = utteranceId;

                const cancelBtn = document.createElement('button');
                cancelBtn.className = 'btn-tiny btn-cancel-edit';
                cancelBtn.textContent = '✕ Отмена';

                textEl.style.display = 'none';
                textEl.after(editor);
                editor.after(saveBtn, cancelBtn);
                editor.focus();

                const cleanup = () => {
                    editor.remove();
                    saveBtn.remove();
                    cancelBtn.remove();
                    textEl.style.display = '';
                };

                cancelBtn.addEventListener('click', cleanup);

                saveBtn.addEventListener('click', async () => {
                    const newText = editor.value.trim();
                    if (!newText || newText === originalText) {
                        cleanup();
                        return;
                    }
                    try {
                        saveBtn.disabled = true;
                        saveBtn.textContent = '⏳ Сохранение...';
                        await api.updateUtteranceText(utteranceId, {
                            text: newText,
                            version_snapshot: true,
                        });
                        const u = utterances.find(x => x.id === utteranceId);
                        if (u) {
                            u.text = newText;
                            textEl.textContent = newText;
                            textEl.dataset.original = newText;
                        }
                        toast.success('Редактировано');
                        cleanup();
                    } catch (err) {
                        toast.error(`Ошибка сохранения: ${err.message || err}`);
                        saveBtn.disabled = false;
                        saveBtn.textContent = '💾 Сохранить';
                    }
                });

                // Ctrl+Enter — сохранить, Escape — отмена
                editor.addEventListener('keydown', (ev) => {
                    if (ev.ctrlKey && ev.key === 'Enter') {
                        ev.preventDefault();
                        saveBtn.click();
                    } else if (ev.key === 'Escape') {
                        ev.preventDefault();
                        cleanup();
                    }
                });
            });
        });

        // Check grammar button
        panel.querySelectorAll('.btn-check-grammar').forEach(btn => {
            if (btn._wired) return;
            btn._wired = true;
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const utteranceId = btn.dataset.utteranceId;
                const u = utterances.find(x => x.id === utteranceId);
                if (!u) return;
                const btnText = btn.innerHTML;
                try {
                    btn.disabled = true;
                    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                    const result = await api.checkGrammar({
                        text: u.text,
                        language: (protocol.language || 'ru').substring(0, 2),
                        utterance_id: utteranceId,
                    });

                    if (!result || !result.issues || result.issues.length === 0) {
                        toast.success('Ошибок не найдено');
                        return;
                    }

                    u._grammar_issues = result.issues;
                    u._grammar_corrected = result.corrected;
                    u._has_issues = true;

                    const item = panel.querySelector(`[data-id="${utteranceId}"]`);
                    if (item) {
                        const oldIssues = item.querySelector('.grammar-issues');
                        if (oldIssues) oldIssues.remove();

                        const issuesHTML = `
                            <div class="grammar-issues">
                                <span class="grammar-issues-count">Найдено: ${result.issues.length}</span>
                                ${result.issues.slice(0, 5).map(i => `
                                    <div class="grammar-issue">
                                        <span class="grammar-issue-rule">[${escapeHtml(i.rule_id)}]</span>
                                        <span class="grammar-issue-original">${escapeHtml(i.original)}</span>
                                        →
                                        <span class="grammar-issue-suggestion">${escapeHtml(i.suggestion)}</span>
                                        <div class="grammar-issue-desc text-muted">${escapeHtml(i.description)}</div>
                                    </div>
                                `).join('')}
                                ${result.issues.length > 5 ? `<div class="grammar-issue text-muted">...и ещё ${result.issues.length - 5}</div>` : ''}
                                <button class="btn-tiny btn-apply-corrections" data-utterance-id="${utteranceId}">✏️ Применить все исправления</button>
                            </div>
                        `;
                        const textEl = item.querySelector('.utterance-text');
                        if (textEl) textEl.insertAdjacentHTML('afterend', issuesHTML);
                        item.classList.add('has-issues');
                    }

                    wireGrammarAndEditButtons();
                    toast.info(`Найдено ${result.issues.length} проблем`);
                } catch (err) {
                    toast.error(`Ошибка проверки: ${err.message || err}`);
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = btnText;
                }
            });
        });

        // Apply corrections button
        panel.querySelectorAll('.btn-apply-corrections').forEach(btn => {
            if (btn._wired) return;
            btn._wired = true;
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const utteranceId = btn.dataset.utteranceId;
                const u = utterances.find(x => x.id === utteranceId);
                if (!u || !u._grammar_corrected) return;
                const newText = u._grammar_corrected;

                try {
                    btn.disabled = true;
                    btn.textContent = '⏳ Применение...';
                    await api.updateUtteranceText(utteranceId, {
                        text: newText,
                        version_snapshot: true,
                    });
                    u.text = newText;
                    delete u._grammar_issues;
                    delete u._grammar_corrected;
                    u._has_issues = false;

                    const item = panel.querySelector(`[data-id="${utteranceId}"]`);
                    if (item) {
                        const textEl = item.querySelector('.utterance-text');
                        if (textEl) {
                            textEl.textContent = newText;
                            textEl.dataset.original = newText;
                        }
                        const issues = item.querySelector('.grammar-issues');
                        if (issues) issues.remove();
                        item.classList.remove('has-issues');
                    }
                    toast.success('Исправления применены');
                } catch (err) {
                    toast.error(`Ошибка: ${err.message || err}`);
                    btn.disabled = false;
                    btn.textContent = '✏️ Применить все исправления';
                }
            });
        });
    };

    wireGrammarAndEditButtons();

    // E150: Кнопки Pause / Resume для транскрибации
    const btnPause = panel.querySelector('#btn-pause-transcription');
    const btnResume = panel.querySelector('#btn-resume-transcription');

    if (btnPause && currentTranscriptionTaskId) {
        btnPause.addEventListener('click', async () => {
            const btnText = btnPause.innerHTML;
            try {
                btnPause.disabled = true;
                btnPause.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> ...';
                const result = await api.pauseTranscription(currentTranscriptionTaskId);
                toast.info(result.message || 'Транскрипция поставлена на паузу');
                btnPause.style.display = 'none';
                if (btnResume) btnResume.style.display = '';
                // Останавливаем polling (новый статус обработается через checkExistingTranscription)
                if (transcriptionPollInterval) {
                    clearInterval(transcriptionPollInterval);
                    transcriptionPollInterval = null;
                }
            } catch (err) {
                toast.error(`Не удалось поставить на паузу: ${err.message || err}`);
                btnPause.disabled = false;
                btnPause.innerHTML = btnText;
            }
        });
    }

    if (btnResume) {
        btnResume.addEventListener('click', async () => {
            if (!currentTranscriptionTaskId) return;
            const btnText = btnResume.innerHTML;
            try {
                btnResume.disabled = true;
                btnResume.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Возобновление...';
                const result = await api.resumeTranscription(currentTranscriptionTaskId);
                toast.success(result.message || 'Транскрибция возобновлена');
                btnResume.style.display = 'none';
                if (btnPause) btnPause.style.display = '';
                // E150: рестарт polling — UI увидит прогресс как новый запуск
                startProgressPolling(protocol, currentTranscriptionTaskId);
            } catch (err) {
                toast.error(`Не удалось возобновить: ${err.message || err}`);
                btnResume.disabled = false;
                btnResume.innerHTML = btnText;
            }
        });
    }

    // E148: Смена языка совещания
    const selectLang = panel.querySelector('#select-protocol-language');
    if (selectLang) {
        selectLang.addEventListener('change', async () => {
            try {
                await api.updateProtocol(protocol.id, {
                    language: selectLang.value,
                });
                protocol.language = selectLang.value;
                toast.success(`Язык совещания: ${selectLang.value}`);
            } catch (e) {
                toast.error(`Не удалось: ${e.message || e}`);
                selectLang.value = protocol.language || 'ru';
            }
        });
    }

    // E149: Смена целевого языка перевода
    const selectTrans = panel.querySelector('#select-translation-language');
    if (selectTrans) {
        selectTrans.addEventListener('change', async () => {
            try {
                await api.updateProtocol(protocol.id, {
                    translation_language: selectTrans.value || null,
                });
                protocol.translation_language = selectTrans.value || null;
                if (selectTrans.value) {
                    toast.info(`Целевой язык: ${selectTrans.value}. Нажмите "Перевести".`);
                }
            } catch (e) {
                toast.error(`Не удалось: ${e.message || e}`);
            }
        });
    }

    // E149: Кнопка "Перевести"
    const btnTrans = panel.querySelector('#btn-translate');
    if (btnTrans) {
        btnTrans.addEventListener('click', async () => {
            const targetLang = protocol.translation_language || selectTrans?.value;
            if (!targetLang) {
                toast.warning('Сначала выберите целевой язык перевода');
                return;
            }
            const btnText = btnTrans.innerHTML;
            try {
                btnTrans.disabled = true;
                btnTrans.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Перевожу...';
                toast.info(`Перевожу на ${targetLang}...`);

                const result = await api.translateUtterances({
                    protocol_id: protocol.id,
                    target_language: targetLang,
                });

                if (!result || !result.translations || !result.translations.length) {
                    toast.warning('Нет реплик для перевода');
                    return;
                }

                toast.success(`Переведено ${result.translations.length} реплик (новых: ${result.new}, из кэша: ${result.cached})`);

                // Update utterances in-memory
                const transMap = new Map(result.translations.map(t => [t.id, t]));
                for (let i = 0; i < utterances.length; i++) {
                    const trans = transMap.get(utterances[i].id);
                    if (trans) {
                        utterances[i].translation_text = trans.translation_text;
                        utterances[i].translation_language = trans.translation_language;
                    }
                }

                // Update DOM append-only (no full re-render)
                for (const [id, trans] of transMap) {
                    const item = panel.querySelector(`[data-id="${id}"]`);
                    if (item && !item.querySelector('.utterance-translation')) {
                        const textEl = item.querySelector('.utterance-text');
                        if (textEl) {
                            const transEl = document.createElement('div');
                            transEl.className = 'utterance-translation';
                            transEl.innerHTML = `<i class="fa-solid fa-language"></i> <span class="translation-label">${escapeHtml(trans.translation_language)}:</span> ${escapeHtml(trans.translation_text)}`;
                            textEl.after(transEl);
                        }
                    }
                }
            } catch (err) {
                console.warn('Translate failed:', err);
                toast.error(`Перевод не удался: ${err.message || err}`);
            } finally {
                btnTrans.disabled = false;
                btnTrans.innerHTML = btnText;
            }
        });
    }

    // E231: убрана обработка timestamp здесь — она в initMediaPlayer.wireTimestampClicks
    // (с защитой через cloneNode + replaceWith, чтобы избежать дублей при повторных рендерах).
    // Если audioPlayer не инициализирован — fallback через audio-seek event.
    panel.querySelectorAll('.timestamp').forEach(ts => {
        // Никаких обработчиков здесь. См. initMediaPlayer.
    });

    // Двойной клик → редактирование (заглушка)
    panel.querySelectorAll('.utterance-item').forEach(item => {
        item.addEventListener('dblclick', () => {
            toast.info('Редактирование реплик — следующая итерация');
        });
    });

    // E140: Кнопка "Исправить через AI" (E142: учитывает speaker_id)
    const btnCleanup = panel.querySelector('#btn-cleanup-ai');
    if (btnCleanup) {
        btnCleanup.addEventListener('click', async () => {
            if (!utterances.length) {
                toast.warning('Нет реплик для улучшения');
                return;
            }
            const btnText = btnCleanup.innerHTML;
            try {
                btnCleanup.disabled = true;
                btnCleanup.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Обработка...';
                toast.info('Запускаю AI-улучшение текста...');

                // E142: Группируем по speaker_id, чтобы AI не склеивал
                // фразы разных спикеров.
                // utterance.speaker_id === null → treat as 'unknown' group
                const groups = [];
                for (const u of utterances) {
                    const speakerKey = u.speaker_id || 'unknown';
                    const text = (u.text || '').trim();
                    if (!text) continue;
                    const last = groups[groups.length - 1];
                    if (last && last.speakerKey === speakerKey) {
                        // тот же спикер → склеиваем через пробел
                        last.text += ' ' + text;
                    } else {
                        groups.push({ speakerKey, text });
                    }
                }

                const fullText = groups.map(g => g.text).join(' ');

                // E148: берём язык протокола, fallback на "ru"
                const protocolLang = (protocol.language || 'ru').substring(0, 2);

                const result = await api.cleanupText({
                    text: fullText,
                    language: protocolLang,
                    operations: ['punctuation', 'spelling', 'formatting'],
                });

                if (result && result.text) {
                    // E142: Распределяем улучшенный текст обратно по utterance,
                    // но НЕ склеивая разных спикеров.
                    const sentences = result.text.split(/(?<=[.!?])\s+/);
                    let idx = 0;
                    for (let i = 0; i < utterances.length && idx < sentences.length; i++) {
                        const origSpeakerKey = utterances[i].speaker_id || 'unknown';
                        // Собираем все предложения относящиеся к этому speaker turn
                        let combined = '';
                        while (idx < sentences.length) {
                            combined += (combined ? ' ' : '') + sentences[idx++];
                            // Заканчиваем когда меняется speaker turn
                            if (i + 1 < utterances.length &&
                                (utterances[i + 1].speaker_id || 'unknown') !== origSpeakerKey) {
                                break;
                            }
                        }
                        utterances[i].text = combined.trim() || utterances[i].text;
                    }
                    // Перерисовать список
                    const list = panel.querySelector('.transcript-list');
                    if (list) {
                        list.innerHTML = utterances
                            .map(u => renderUtteranceItem(u, speakers))
                            .join('');
                        // Перепривязываем dblclick
                        panel.querySelectorAll('.utterance-item').forEach(item => {
                            item.addEventListener('dblclick', () => {
                                toast.info('Редактирование реплик — следующая итерация');
                            });
                        });
                    }
                    toast.success(`AI-улучшение применено к ${result.text.length} символам`);
                } else {
                    toast.warning('AI вернул пустой результат');
                }
            } catch (err) {
                console.warn('AI cleanup failed:', err);
                toast.error(`AI-улучшение не удалось: ${err.message || 'unknown'}`);
            } finally {
                btnCleanup.disabled = false;
                btnCleanup.innerHTML = btnText;
            }
        });
    }

    // E141: Кнопка "Запустить диаризацию"
    const btnDiarize = panel.querySelector('#btn-diarize');
    if (btnDiarize) {
        btnDiarize.addEventListener('click', async () => {
            const btnText = btnDiarize.innerHTML;
            try {
                btnDiarize.disabled = true;
                btnDiarize.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Диаризация...';
                toast.info('Запускаю диаризацию (определение спикеров)...');
                const result = await api.startDiarization({ protocol_id: protocol.id });
                // Запустить polling статуса (упрощённый вариант)
                const checkStatus = async () => {
                    try {
                        const r = await api.getDiarizationResult(protocol.id);
                        if (r && r.num_speakers_detected > 0) {
                            toast.success(`Диаризация завершена: ${r.num_speakers_detected} спикеров`);
                            // Перезагрузить страницу чтобы отобразить спикеров
                            window.location.reload();
                            return;
                        }
                    } catch (e) { /* not ready yet */ }
                    setTimeout(checkStatus, 2000);
                };
                checkStatus();
            } catch (err) {
                toast.error(`Диаризация не удалась: ${err.message}`);
            } finally {
                btnDiarize.disabled = false;
                btnDiarize.innerHTML = btnText;
            }
        });
    }

    // E147: Кнопка "🤖 Найти решения" — AI auto-extract
    // Ручная пометка (E146) продолжает работать независимо.
    const btnExtract = panel.querySelector('#btn-extract-decisions');
    if (btnExtract) {
        btnExtract.addEventListener('click', async () => {
            const btnText = btnExtract.innerHTML;
            try {
                btnExtract.disabled = true;
                btnExtract.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Ищу решения...';
                toast.info('Запускаю AI-поиск решений...');

                const result = await api.extractDecisions({
                    protocol_id: protocol.id,
                    min_confidence: 0.5,
                });

                if (!result || !result.decisions || !result.decisions.length) {
                    toast.warning('AI не нашёл решений');
                    return;
                }

                toast.info(`AI нашёл ${result.total_found} решений, сохраняю...`);

                // Сохраняем каждое решение через /decisions (с timestamp_sec, source_utterance_id)
                let saved = 0;
                for (const d of result.decisions) {
                    try {
                        // E147: проверяем — не дубликат ли (уже есть такой же source_utterance_id)
                        if (d.source_utterance_id) {
                            const existing = await api.listDecisions(protocol.id);
                            if (existing.some(x => x.source_utterance_id === d.source_utterance_id)) {
                                continue; // пропускаем — уже есть
                            }
                        }

                        await api.createDecision({
                            protocol_id: protocol.id,
                            text: d.text,
                            source_utterance_id: d.source_utterance_id,
                            timestamp_sec: d.timestamp_sec,
                            priority: d.priority || 'medium',
                            source: 'transcript',
                            decided_by: 'AI (авто)',
                        });
                        saved += 1;
                    } catch (e) {
                        console.warn('Failed to save decision:', e);
                    }
                }

                // E147: обновляем UI без перерисовки
                // 1. Загружаем актуальные decisions чтобы получить новые id
                const updatedDecisions = await api.listDecisions(protocol.id);
                decisionIds = new Set(updatedDecisions
                    .filter(dd => dd.source_utterance_id)
                    .map(dd => dd.source_utterance_id));

                // 2. Подсвечиваем каждую utterance
                for (const dec of updatedDecisions) {
                    if (dec.source_utterance_id) {
                        const item = panel.querySelector(`[data-id="${dec.source_utterance_id}"]`);
                        if (item) {
                            item.classList.add('is-decision');
                            const textEl = item.querySelector('.utterance-text');
                            if (textEl && !textEl.querySelector('.decision-mark')) {
                                textEl.insertAdjacentHTML(
                                    'beforeend',
                                    ` <span class="decision-mark" title="AI: ${dec.rationale || 'решение'}">⚖️</span>`
                                );
                            }
                            // E171: меняем кнопку на помеченную через классы
                            const btn = item.querySelector('.btn-mark-decision');
                            if (btn) {
                                btn.classList.remove('btn-mark-decision');
                                btn.classList.add('btn-decision-marked');
                                btn.dataset.wired = '';
                                btn.title = 'Снять пометку решения';
                                btn.innerHTML = '⚖️';
                            }
                        }
                    }
                }

                // 3. Перепривязываем обработчики
                wireDecisionButtons();

                toast.success(`AI добавил ${saved} решений${result.total_found > saved ? ` (${result.total_found - saved} были дубликатами)` : ''}`);
            } catch (err) {
                console.warn('AI extract failed:', err);
                toast.error(`AI-поиск не удался: ${err.message || err}`);
            } finally {
                btnExtract.disabled = false;
                btnExtract.innerHTML = btnText;
            }
        });
    }

    // E162: Кнопка "🚀 Улучшить слабые" — upgrade endpoint
    const btnUpgrade = panel.querySelector('#btn-upgrade-weak');
    if (btnUpgrade) {
        btnUpgrade.addEventListener('click', async () => {
            const btnText = btnUpgrade.innerHTML;
            try {
                btnUpgrade.disabled = true;
                btnUpgrade.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Улучшаю...';
                toast.info('Запускаю большую модель для слабых сегментов...');

                const result = await api.upgradeWeakSegments(protocol.id, {
                    target_model: 'large-v3',
                    confidence_threshold: 0.7,
                });

                if (!result || result.weak_segments_found === 0) {
                    toast.success('Нет слабых сегментов для улучшения!');
                    return;
                }

                toast.success(`Найдено ${result.weak_segments_found} слабых, улучшено ${result.upgraded}`);

                // Перезагрузить страницу чтобы увидеть новые тексты
                setTimeout(() => window.location.reload(), 1500);
            } catch (err) {
                console.error('Upgrade failed:', err);
                toast.error(`Не удалось: ${err.message || err}`);
            } finally {
                btnUpgrade.disabled = false;
                btnUpgrade.innerHTML = btnText;
            }
        });
    }

    // E154: Batch check grammar — все реплики
    const btnCheckAll = panel.querySelector('#btn-check-all-grammar');
    if (btnCheckAll) {
        btnCheckAll.addEventListener('click', async () => {
            const btnText = btnCheckAll.innerHTML;
            try {
                btnCheckAll.disabled = true;
                btnCheckAll.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Проверка...';
                toast.info('Проверяю грамматику всех реплик...');

                let totalIssues = 0;
                let totalUtterancesWithIssues = 0;
                const lang = (protocol.language || 'ru').substring(0, 2);
                const batchSize = 10;
                const itemsToCheck = utterances.slice(0, 200);  // лимит для производительности

                for (let i = 0; i < itemsToCheck.length; i += batchSize) {
                    const batch = itemsToCheck.slice(i, i + batchSize);
                    const results = await Promise.allSettled(
                        batch.map(u => api.checkGrammar({
                            text: u.text,
                            language: lang,
                            utterance_id: u.id,
                        }))
                    );
                    for (let j = 0; j < batch.length; j++) {
                        const r = results[j];
                        if (r.status === 'fulfilled' && r.value && r.value.issues) {
                            const u = batch[j];
                            u._grammar_issues = r.value.issues;
                            u._grammar_corrected = r.value.corrected;
                            if (r.value.issues.length > 0) {
                                totalIssues += r.value.issues.length;
                                totalUtterancesWithIssues += 1;
                                u._has_issues = true;
                                // Append-only DOM update
                                const item = panel.querySelector(`[data-id="${u.id}"]`);
                                if (item) {
                                    const oldIssues = item.querySelector('.grammar-issues');
                                    if (oldIssues) oldIssues.remove();
                                    const issuesHTML = `
                                        <div class="grammar-issues">
                                            <span class="grammar-issues-count">Найдено: ${r.value.issues.length}</span>
                                            ${r.value.issues.slice(0, 3).map(issue => `
                                                <div class="grammar-issue">
                                                    <span class="grammar-issue-rule">[${escapeHtml(issue.rule_id)}]</span>
                                                    <span class="grammar-issue-original">${escapeHtml(issue.original)}</span> →
                                                    <span class="grammar-issue-suggestion">${escapeHtml(issue.suggestion)}</span>
                                                </div>
                                            `).join('')}
                                            ${r.value.issues.length > 3 ? `<div class="grammar-issue text-muted">...и ещё ${r.value.issues.length - 3}</div>` : ''}
                                            <button class="btn-tiny btn-apply-corrections" data-utterance-id="${u.id}">✏️ Применить</button>
                                        </div>
                                    `;
                                    const textEl = item.querySelector('.utterance-text');
                                    if (textEl) textEl.insertAdjacentHTML('afterend', issuesHTML);
                                    item.classList.add('has-issues');
                                }
                            }
                        }
                    }
                }

                wireGrammarAndEditButtons();

                const btnApplyAll = panel.querySelector('#btn-apply-all-corrections');
                if (totalUtterancesWithIssues > 0 && btnApplyAll) {
                    btnApplyAll.style.display = '';
                    btnApplyAll.textContent = `✏️ Применить всё (${totalUtterancesWithIssues} реплик)`;
                }

                toast.success(`Найдено ${totalIssues} проблем в ${totalUtterancesWithIssues} репликах`);
            } catch (err) {
                console.error('Batch check failed:', err);
                toast.error(`Ошибка: ${err.message || err}`);
            } finally {
                btnCheckAll.disabled = false;
                btnCheckAll.innerHTML = btnText;
            }
        });
    }

    // E154: Apply all corrections — применить все исправления разом
    const btnApplyAll = panel.querySelector('#btn-apply-all-corrections');
    if (btnApplyAll) {
        btnApplyAll.addEventListener('click', async () => {
            const items = utterances.filter(u => u._grammar_corrected && u._has_issues);
            if (!items.length) {
                toast.warning('Нет реплик с исправлениями');
                return;
            }
            const btnText = btnApplyAll.innerHTML;
            try {
                btnApplyAll.disabled = true;
                btnApplyAll.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Применяю...';
                toast.info(`Применяю исправления к ${items.length} репликам...`);

                let applied = 0;
                for (const u of items) {
                    try {
                        await api.updateUtteranceText(u.id, {
                            text: u._grammar_corrected,
                            version_snapshot: true,
                        });
                        u.text = u._grammar_corrected;
                        delete u._grammar_issues;
                        delete u._grammar_corrected;
                        u._has_issues = false;

                        const item = panel.querySelector(`[data-id="${u.id}"]`);
                        if (item) {
                            const textEl = item.querySelector('.utterance-text');
                            if (textEl) {
                                textEl.textContent = u.text;
                                textEl.dataset.original = u.text;
                            }
                            const issues = item.querySelector('.grammar-issues');
                            if (issues) issues.remove();
                            item.classList.remove('has-issues');
                        }
                        applied++;
                    } catch (e) {
                        console.warn('Failed to apply correction:', u.id, e);
                    }
                }

                btnApplyAll.style.display = 'none';
                toast.success(`Применено ${applied}/${items.length} исправлений`);
            } catch (err) {
                toast.error(`Ошибка: ${err.message || err}`);
            } finally {
                btnApplyAll.disabled = false;
                btnApplyAll.innerHTML = btnText;
            }
        });
    }

    // E141: Сразу загружаем speakers, нужно для отображения диаризации
    if (!speakers || !speakers.length) {
        try {
            speakers = await api.listSpeakers(protocol.id);
            // Перерисовать список если speakers изменились
            const list = panel.querySelector('.transcript-list');
            if (list && utterances.length) {
                list.innerHTML = utterances
                    .map(u => renderUtteranceItem(u, speakers))
                    .join('');
                // E234: после innerHTML старые обработчики потеряны.
                // Перепривязываем — иначе ☆/⚖️/✏️/🔍 не работают.
                wireDecisionButtons();
                wireImportantButtons(utterances, panel);
                wireGrammarAndEditButtons();
            }
        } catch (e) {
            console.warn('Failed to load speakers:', e);
        }
    }

    // Обработчик кнопки "Транскрибировать" в empty-state
    const emptyState = panel.querySelector('empty-state');
    if (emptyState) {
        emptyState.addEventListener('action', () => startTranscribe(protocol));
    }
}

function renderUtteranceItem(u, speakers, fallbackSpeakers = null, decisionIds = null) {
    // E144: три источника speaker для badges:
    // 1. u.speaker_label — денормализован из бэкенда (если был join)
    // 2. speakers.find(s => s.id === u.speaker_id) — из списка speakers
    // 3. fallbackSpeakers — если loadSpeakers пришёл позже и не совпадает со старым render
    let speaker = null;
    if (u.speaker_label) {
        // u.speaker_label есть (например "Speaker 1") — найдём по нему
        speaker = speakers.find(s => s.display_name === u.speaker_label)
            || speakers.find(s => s.speaker_label === u.speaker_label)
            || fallbackSpeakers?.find(s => s.display_name === u.speaker_label);
    }
    if (!speaker && u.speaker_id) {
        speaker = speakers.find(s => s.id === u.speaker_id)
            || fallbackSpeakers?.find(s => s.id === u.speaker_id);
    }

    // E144: Если speaker_id пришёл из БД, но объект Speaker не нашёлся —
    // создаём виртуальный "Speaker N" с цветом по хэшу id
    let speakerName, speakerColor;
    if (speaker) {
        speakerName = speaker.display_name || speaker.speaker_label || u.speaker_label || 'Speaker ?';
        speakerColor = speaker.color || '#888';
    } else if (u.speaker_id || u.speaker_label) {
        // Виртуальный speaker — отображаем badge по имеющимся данным
        speakerName = u.speaker_label || 'Speaker ?';
        const colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];
        let hash = 0;
        const idStr = String(u.speaker_id || u.speaker_label || '');
        for (let i = 0; i < idStr.length; i++) {
            hash = ((hash << 5) - hash) + idStr.charCodeAt(i);
            hash |= 0;
        }
        speakerColor = colors[Math.abs(hash) % colors.length];
    } else {
        speakerName = '—';
        speakerColor = '#888';
    }

    const startTime = formatTimestamp(u.start_sec);
    const conf = u.confidence ?? 1.0;
    const confClass = conf < 0.4 ? 'danger' : conf < 0.7 ? 'warning' : 'success';
    // E231: улучшенная иконка low confidence — кликабельная, открывает апгрейд
    const lowConfIcon = u.low_confidence
        ? ` <span class="low-conf-mark" title="Низкая уверенность (${(conf * 100).toFixed(0)}%). Кликните для upgrade." style="color:#f59e0b; cursor:help;">⚠️</span>`
        : '';
    const isDecision = decisionIds && decisionIds.has(u.id);
    const decisionIcon = isDecision
        ? '<span class="decision-mark" title="Решение">⚖️</span>'
        : '';
    const actionBtn = isDecision
        ? `<button class="btn-tiny btn-decision-marked" data-utterance-id="${u.id}" title="Снять пометку решения">⚖️</button>`
        : `<button class="btn-tiny btn-mark-decision" data-utterance-id="${u.id}" title="Пометить как решение">＋ ⚖️</button>`;
    // E154: редактирование + проверка грамматики
    const editBtn = `<button class="btn-tiny btn-edit-utterance" data-utterance-id="${u.id}" title="Редактировать"><i class="fa-regular fa-pen-to-square"></i></button>`;
    const grammarBtn = `<button class="btn-tiny btn-check-grammar" data-utterance-id="${u.id}" title="Проверить орфографию/грамматику">🔍</button>`;
    // E172: Закладка "Важное"
    const importantBtn = u.important
        ? `<button class="btn-tiny btn-important-marked" data-utterance-id="${u.id}" title="Снять закладку 'Важное'">⭐</button>`
        : `<button class="btn-tiny btn-mark-important" data-utterance-id="${u.id}" title="Пометить как 'Важное'">☆</button>`;
    // E149: отображение перевода (если есть)
    const translationBlock = u.translation_text
        ? `<div class="utterance-translation"><i class="fa-solid fa-language"></i> <span class="translation-label">${escapeHtml(u.translation_language || '?')}:</span> ${escapeHtml(u.translation_text)}</div>`
        : '';
    // E154: блок issues (если есть после проверки)
    const issuesBlock = (u._grammar_issues && u._grammar_issues.length)
        ? `<div class="grammar-issues">
            <span class="grammar-issues-count">Найдено: ${u._grammar_issues.length}</span>
            ${u._grammar_issues.slice(0, 3).map(i => `<div class="grammar-issue">${escapeHtml(i.description)}</div>`).join('')}
            ${u._grammar_issues.length > 3 ? `<div class="grammar-issue text-muted">...и ещё ${u._grammar_issues.length - 3}</div>` : ''}
            <button class="btn-tiny btn-apply-corrections" data-utterance-id="${u.id}">✏️ Применить исправления</button>
        </div>`
        : '';
    return `
        <div class="utterance-item ${isDecision ? 'is-decision' : ''} ${u._has_issues ? 'has-issues' : ''} ${u.important ? 'is-important' : ''}" data-id="${u.id}" tabindex="0">
            <div class="utterance-meta">
                <span class="speaker-badge" style="background:${speakerColor};" title="${escapeHtml(speakerName)}">${escapeHtml(speakerName)}</span>
                <span class="timestamp" data-time="${u.start_sec}">${startTime}</span>
                <span class="confidence-bar">
                    <span class="conf-fill conf-${confClass}" style="width:${conf * 100}%"></span>
                </span>
                <span class="utterance-actions">
                    ${importantBtn}
                    ${actionBtn}
                    ${editBtn}
                    ${grammarBtn}
                </span>
            </div>
            <div class="utterance-text" data-original="${escapeHtml(u.text)}">${escapeHtml(u.text)}${lowConfIcon}${decisionIcon}${u.important ? ' <span class="important-mark" title="Важное">⭐</span>' : ''}</div>
            ${issuesBlock}
            ${translationBlock}
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

async function renderDecisionsTab(rootEl, protocol) {
    const panel = rootEl.querySelector('#panel-decisions');
    panel.innerHTML = `<div class="loading"><div class="spinner"></div> Загрузка решений...</div>`;

    // E146: Загрузка решений из API
    let decisions = [];
    try {
        const result = await api.listDecisions(protocol.id);
        decisions = Array.isArray(result) ? result : [];
    } catch (e) {
        console.warn('Failed to load decisions:', e);
        decisions = [];
    }

    if (!decisions.length) {
        panel.innerHTML = `<empty-state icon="<i class="fa-solid fa-check"></i>" title="Список решений пуст" description="Пометьте фразы в транскрипте как ⚖️ Решение. Каждое решение получит таймкод."></empty-state>`;
        return;
    }

    panel.innerHTML = `
        <div class="decisions-list">
            ${decisions.sort((a, b) => (a.timestamp_sec ?? 0) - (b.timestamp_sec ?? 0)).map(d => `
                <div class="decision-card" data-id="${d.id}" data-timestamp="${d.timestamp_sec ?? ''}" data-utterance-id="${d.source_utterance_id ?? ''}">
                    <div class="decision-header">
                        <span class="decision-timestamp" data-time="${d.timestamp_sec ?? ''}">
                            <i class="fa-regular fa-clock"></i>
                            ${formatTimestamp(d.timestamp_sec ?? 0)}
                        </span>
                        <span class="badge badge-${d.priority === 'high' ? 'danger' : d.priority === 'low' ? 'info' : 'warning'}">${d.priority || 'medium'}</span>
                        <button class="btn-tiny btn-delete-decision" data-id="${d.id}" title="Удалить">
                            <i class="fa-regular fa-trash-can"></i>
                        </button>
                    </div>
                    <div class="decision-text">${escapeHtml(d.text || '')}</div>
                    <div class="decision-meta">
                        ${d.decided_by ? `<i class="fa-regular fa-user"></i> ${escapeHtml(d.decided_by)}` : ''}
                        <span class="text-muted"><i class="fa-regular fa-calendar"></i> ${new Date(d.created_at).toLocaleString('ru-RU')}</span>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    // E146: клик на timestamp → перемотка аудио
    panel.querySelectorAll('.decision-timestamp').forEach(ts => {
        ts.addEventListener('click', () => {
            const sec = parseFloat(ts.dataset.time);
            if (window.audioPlayer && window.audioPlayer.seekTo) {
                window.audioPlayer.seekTo(sec);
                toast.info(`Перемотано на ${formatTimestamp(sec)}`);
            } else {
                window.dispatchEvent(new CustomEvent('audio-seek', { detail: { sec } }));
            }
        });
    });

    // Удаление решения
    panel.querySelectorAll('.btn-delete-decision').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const card = btn.closest('.decision-card');
            const utteranceId = card?.dataset.utteranceId;
            try {
                await api.deleteDecision(id);
                card.remove();
                if (!panel.querySelector('.decision-card')) {
                    panel.innerHTML = `<empty-state icon="<i class="fa-solid fa-check"></i>" title="Список решений пуст"></empty-state>`;
                }
                // E245: обновляем кнопку в транскрипте (если она там)
                if (utteranceId) {
                    syncDecisionButtonInTranscript(utteranceId, false);
                }
                // E245: обновляем badge
                const cnt = panel.querySelectorAll('.btn-decision-marked').length;
                const badge = document.getElementById('decisions-badge');
                if (badge) badge.textContent = cnt > 0 ? `(${cnt})` : '';
                toast.success('Решение удалено');
            } catch (e) {
                toast.error(`Не удалось: ${e.message || e}`);
            }
        });
    });
}

// E245: синхронизирует кнопку ⚖️ в транскрипте с состоянием в БД.
// marked=true → показывает ⚖️ (нельзя добавить ещё раз).
// marked=false → показывает ＋⚖️ (можно добавить).
function syncDecisionButtonInTranscript(utteranceId, marked) {
    // Ищем все кнопки с этим utteranceId в обеих вариантах (на случай дублей после polling)
    const buttons = document.querySelectorAll(`.btn-mark-decision[data-utterance-id="${utteranceId}"], .btn-decision-marked[data-utterance-id="${utteranceId}"]`);
    buttons.forEach(btn => {
        if (marked) {
            // Пометить
            btn.classList.remove('btn-mark-decision');
            btn.classList.add('btn-decision-marked');
            btn.dataset.marked = '1';
            btn.dataset.wired = '';
            btn.title = 'Снять пометку решения';
            btn.innerHTML = '⚖️';
        } else {
            // Снять пометку
            btn.classList.remove('btn-decision-marked');
            btn.classList.add('btn-mark-decision');
            btn.dataset.marked = '';
            delete btn.dataset.decisionId;
            btn.title = 'Пометить как решение';
            btn.innerHTML = '＋ ⚖️';
        }
    });

    // Подсветка реплики
    const items = document.querySelectorAll(`.utterance-item[data-id="${utteranceId}"]`);
    items.forEach(item => {
        if (marked) {
            item.classList.add('is-decision');
            const textEl = item.querySelector('.utterance-text');
            if (textEl && !textEl.querySelector('.decision-mark')) {
                textEl.insertAdjacentHTML('beforeend',
                    ' <span class="decision-mark" title="Решение">⚖️</span>');
            }
        } else {
            item.classList.remove('is-decision');
            const mark = item.querySelector('.decision-mark');
            if (mark) mark.remove();
        }
    });
}

// E232: вкладка "Важное" — список помеченных реплик
function renderImportantTab(rootEl, protocol, allUtterances) {
    const panel = rootEl.querySelector('#panel-important');
    if (!panel) {
        console.warn('[renderImportantTab] panel-important not found');
        return;
    }

    const importantUtterances = (allUtterances || []).filter(u => u.important);

    // E233: отладка — лог в консоль
    console.log('[renderImportantTab]',
        'allUtterances:', allUtterances?.length || 0,
        'importantUtterances:', importantUtterances.length,
        'allUtterances[0]?.important:', allUtterances?.[0]?.important,
    );

    // Обновляем badge в табе
    const badge = document.getElementById('important-badge');
    if (badge) {
        badge.textContent = importantUtterances.length > 0 ? `(${importantUtterances.length})` : '';
    }

    if (importantUtterances.length === 0) {
        panel.innerHTML = `
            <empty-state
                icon='<i class="fa-solid fa-star"></i>'
                title="Нет важных реплик"
                description="Нажмите ☆ рядом с репликой в транскрипте, чтобы добавить её в избранное"
            ></empty-state>
        `;
        return;
    }

    // Сортируем по start_sec
    importantUtterances.sort((a, b) => (a.start_sec || 0) - (b.start_sec || 0));

    // E232: используем renderUtteranceItem (тот же рендер что и в транскрипте)
    // Но с временем и важным в начале
    const html = importantUtterances.map(u => renderUtteranceItem(u, [])).join('');
    panel.innerHTML = `
        <div class="transcript-toolbar">
            <span class="text-muted">${importantUtterances.length} важн${importantUtterances.length === 1 ? 'ая' : 'ых'}</span>
            <button class="btn-tiny" id="btn-clear-important">🗑 Снять все</button>
        </div>
        <div class="transcript-list">${html}</div>
    `;

    // Привязываем обработчики (важное уже помечено как важное — клик снимает)
    wireImportantButtons(allUtterances, panel);

    // Кнопка "снять все"
    panel.querySelector('#btn-clear-important')?.addEventListener('click', async () => {
        if (!confirm(`Снять пометку "Важное" со всех ${importantUtterances.length} реплик?`)) return;
        try {
            for (const u of importantUtterances) {
                await api.toggleUtteranceImportant(u.id, false);
                u.important = false;
                // E245: синхронизируем кнопки в транскрипте
                syncImportantButtonInTranscript(u.id, false);
            }
            toast.info('Закладки сняты');
            renderImportantTab(rootEl, protocol, allUtterances);
            // Обновляем счётчик в табе
            const badge = document.getElementById('important-badge');
            if (badge) badge.textContent = '';
        } catch (e) {
            toast.error(`Не удалось: ${e.message || e}`);
        }
    });
}

// E245: синхронизирует кнопку ☆/⭐ в транскрипте с состоянием в БД
// E248: updateDecisionsBadge определена здесь (модульная область) — иначе ReferenceError
function updateDecisionsBadge(panel) {
    if (!panel) panel = document.getElementById('panel-transcript');
    if (!panel) return;
    const badge = document.getElementById('decisions-badge');
    if (!badge) return;
    const cnt = panel.querySelectorAll('.btn-decision-marked').length;
    badge.textContent = cnt > 0 ? `(${cnt})` : '';
}

function syncImportantButtonInTranscript(utteranceId, marked) {
    const buttons = document.querySelectorAll(`.btn-mark-important[data-utterance-id="${utteranceId}"], .btn-important-marked[data-utterance-id="${utteranceId}"]`);
    buttons.forEach(btn => {
        if (marked) {
            btn.classList.remove('btn-mark-important');
            btn.classList.add('btn-important-marked');
            btn.dataset.marked = '1';
            btn.dataset.wired = '';
            btn.title = "Снять закладку 'Важное'";
            btn.innerHTML = '⭐';
        } else {
            btn.classList.remove('btn-important-marked');
            btn.classList.add('btn-mark-important');
            btn.dataset.marked = '';
            btn.title = "Пометить как 'Важное'";
            btn.innerHTML = '☆';
        }
    });

    const items = document.querySelectorAll(`.utterance-item[data-id="${utteranceId}"]`);
    items.forEach(item => {
        if (marked) {
            item.classList.add('is-important');
            const textEl = item.querySelector('.utterance-text');
            if (textEl && !textEl.querySelector('.important-mark')) {
                textEl.insertAdjacentHTML('beforeend',
                    ' <span class="important-mark" title="Важное">⭐</span>');
            }
        } else {
            item.classList.remove('is-important');
            const mark = item.querySelector('.important-mark');
            if (mark) mark.remove();
        }
    });
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
    // E230: fallback на '—' если generated_at отсутствует
    panel.innerHTML = `
        <div class="summary-header">
            <span class="text-muted">Провайдер: ${summary.provider} · ${summary.tokens_used || '?'} токенов · ${summary.generated_at ? new Date(summary.generated_at).toLocaleString('ru-RU') : '—'}</span>
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
        // E184: модель берётся из настроек Whisper (Settings → Whisper Models → Active).
        // Backend использует settings.whisper_model по умолчанию.
        // Пользователь явно выбирает модель в разделе "Whisper модели".
        toast.info('Запуск транскрипции...');

        // E241: очищаем UI от старых результатов ДО запроса — пользователь
        // видит "чистую" страницу сразу, не дожидаясь backend DELETE.
        clearTranscriptionUI(protocol);

        // E243: получаем настройки из user_setting
        // На скрине пользователь выбирает "Medium" — должна использоваться Medium.
        let selectedModel;
        let remoteEnabled = false;
        let remoteUrl = '';
        let remotePath = '/transcribe';
        try {
            const us = await api.getUserSetting();
            selectedModel = us?.whisper_model;
            remoteEnabled = us?.whisper_remote_enabled === true;
            remoteUrl = (us?.whisper_remote_url || '').trim();
            remotePath = (us?.whisper_remote_path || '/transcribe').trim();
            // Кешируем
            if (selectedModel) {
                try { localStorage.setItem('hmp.whisper_model', selectedModel); } catch {}
            } else {
                try { selectedModel = localStorage.getItem('hmp.whisper_model'); } catch {}
            }
            try { localStorage.setItem('hmp.whisper_remote', JSON.stringify({ enabled: remoteEnabled, url: remoteUrl, path: remotePath })); } catch {}
        } catch (e) {
            console.warn('[startTranscribe] failed to load user_setting:', e);
            try { selectedModel = localStorage.getItem('hmp.whisper_model'); } catch {}
            try {
                const cached = JSON.parse(localStorage.getItem('hmp.whisper_remote') || '{}');
                remoteEnabled = !!cached.enabled;
                remoteUrl = cached.url || '';
                remotePath = cached.path || '/transcribe';
            } catch {}
        }

        // E252: если включён удалённый Whisper — отправляем напрямую на remote сервер
        if (remoteEnabled && remoteUrl) {
            console.log('[startTranscribe] using REMOTE Whisper:', remoteUrl + remotePath);
            await transcribeRemote({
                url: remoteUrl,
                path: remotePath,
                model: selectedModel || 'base',
                language: 'ru',
                protocol,
            });
            return;
        }

        const response = await api.startTranscription({
            protocol_id: protocol.id,
            model: selectedModel,  // E243: реальная модель из user_setting
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

// E253: транскрибация через удалённый Whisper с честным прогрессом
async function transcribeRemote({ protocol, url, path, model, language }) {
    if (!protocol) {
        toast.error('Нет протокола для транскрибации');
        return null;
    }

    const remoteEndpoint = (url || '').replace(/\/$/, '') + (path || '/transcribe');
    const progressBar = ensureRemoteProgressBar();
    setRemoteProgress(progressBar, 0, 'Подключение к удалённому Whisper…');
    toast.info(`Отправляю на удалённый Whisper (${model})…`);
    console.log('[transcribeRemote] target:', remoteEndpoint, 'via', `/api/v1/hmp/transcribe/remote`);

    try {
        setRemoteProgress(progressBar, 15, 'Локальный backend читает аудио и шлёт на удалённый сервер…');

        // E264: через proxy endpoint локального backend — обходит Mixed Content
        // E265: пробуем несколько базовых URL backend И разные endpoints
        const apiBases = [
            'http://127.0.0.1:8000',  // основной
            'http://localhost:8000',    // запасной
            '',                          // same-origin (если открыто через :8000 или proxy есть)
        ];
        const endpointPaths = ['/api/v1/hmp/remote'];  // единственный реально существующий роут

        let response = null;
        let lastErr = null;
        outer:
        for (const base of apiBases) {
            for (const path of endpointPaths) {
                const endpoint = `${base}${path}`;
                console.log('[transcribeRemote] trying endpoint:', endpoint);
                let r;
                try {
                    // E278: создаём FormData заранее — иначе Content-Length не считается
                    const form = new FormData();
                    form.append('protocol_id', protocol.id);
                    form.append('target_url', url);
                    form.append('target_path', path || '/transcribe');
                    form.append('model', model || 'base');
                    form.append('language', language || 'ru');
                    r = await fetch(endpoint, {
                        method: 'POST',
                        body: form,
                    });
                } catch (fetchErr) {
                    console.warn('[transcribeRemote] fetch failed at', endpoint, fetchErr);
                    lastErr = endpoint + ': ' + fetchErr.message;
                    continue;
                }
                if (r.status === 404) {
                    console.warn('[transcribeRemote] 404 at', endpoint, '→ next');
                    lastErr = endpoint + ': 404';
                    continue;
                }
                if (r.status === 501 && (r.headers.get('content-type') || '').includes('html')) {
                    console.warn('[transcribeRemote] 501 HTML (Vite без proxy) at', endpoint, '→ next');
                    lastErr = endpoint + ': 501 HTML';
                    continue;
                }
                if (r.status >= 500) {
                    // E275: показать traceback для 500+ ошибок
                    const txt = await r.text();
                    console.error(`[transcribeRemote] ${endpoint} → ${r.status}:`, txt.slice(0, 800));
                    lastErr = endpoint + ': ' + r.status + ' ' + txt.slice(0, 200);
                    continue;
                }
                if (!r.ok) {
                    const txt = await r.text();
                    lastErr = endpoint + ': ' + r.status + ' ' + txt.slice(0, 200);
                    continue;
                }
                response = r;
                break outer;
            }
        }

        if (!response) {
            throw new Error('Не удалось вызвать /transcribe/remote через ни одну из баз. Последняя: ' + lastErr);
        }

        if (!response.ok) {
            const txt = await response.text();
            throw new Error(`Remote proxy ${response.status}: ${txt.slice(0, 200)}`);
        }

        const result = await response.json();
        console.log('[transcribeRemote] result:', result);

        setRemoteProgress(progressBar, 75, `Получено ${result.segments_created} реплик, обновляю UI…`);

        // Загружаем utterances и перерисовываем
        const fresh = await api.listUtterances(protocol.id, { limit: 500 });
        const items = fresh?.items || fresh || [];
        const transcriptList = document.querySelector('#panel-transcript .transcript-list');
        if (transcriptList && items.length) {
            transcriptList.innerHTML = items.map(u => renderUtteranceItem(u, [])).join('');
            wireImportantButtons(items, document.getElementById('panel-transcript'));
            wireDecisionButtons();
        }
        window._currentUtterances = items;

        setRemoteProgress(progressBar, 100, `✅ Готово: ${result.segments_created} реплик`);
        toast.success(`Удалённый Whisper вернул ${result.segments_created} реплик`);
        setTimeout(() => hideRemoteProgress(progressBar), 3000);

        return result;

    } catch (err) {
        console.error('[transcribeRemote] failed:', err);
        setRemoteProgress(progressBar, 0, '❌ ' + (err.message || err));
        toast.error(`Удалённый Whisper: ${err.message || err}`);
        setTimeout(() => hideRemoteProgress(progressBar), 5000);
        return null;
    }
}
 // E253: создаёт (если нет) отдельный прогресс-бар для remote
function ensureRemoteProgressBar() {
    let bar = document.getElementById('remote-transcribe-progress');
    if (bar) return bar;
    bar = document.createElement('div');
    bar.id = 'remote-transcribe-progress';
    bar.className = 'transcribe-progress-remote';
    bar.innerHTML = `
        <div class="remote-progress-header">
            <i class="fa-solid fa-cloud"></i> Удалённый Whisper
            <span class="remote-progress-pct">0%</span>
        </div>
        <div class="remote-progress-track"><div class="remote-progress-fill"></div></div>
        <div class="remote-progress-msg">Подготовка…</div>
    `;
    document.body.appendChild(bar);
    return bar;
}

function setRemoteProgress(bar, pct, msg) {
    if (!bar) return;
    const fill = bar.querySelector('.remote-progress-fill');
    const pctEl = bar.querySelector('.remote-progress-pct');
    const msgEl = bar.querySelector('.remote-progress-msg');
    if (fill) fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
    if (msgEl) msgEl.textContent = msg || '';
    bar.style.display = '';
}

function hideRemoteProgress(bar) {
    if (!bar) return;
    bar.style.display = 'none';
}

// E253: сохраняет результат удалённого Whisper на локальный backend с прогрессом
async function saveRemoteResultToBackend(protocol, data, onProgress) {
    try {
        const segs = data.segments || [];
        if (!segs.length) {
            console.warn('[saveRemoteResultToBackend] no segments to save');
            return;
        }

        // Этап 3a: создаём utterances по одному (0..80% сохранения)
        const total = segs.length;
        let saved = 0;
        for (const seg of segs) {
            try {
                await api.createUtterance(protocol.id, {
                    start_sec: seg.start,
                    end_sec: seg.end,
                    text: seg.text,
                });
            } catch (e) {
                console.warn('[saveRemoteResultToBackend] createUtterance failed:', e);
            }
            saved++;
            if (onProgress && total > 0) {
                const pct = Math.round((saved / total) * 80);
                onProgress(pct, `Сохраняю реплики: ${saved} / ${total}`);
            }
        }

        // Этап 3b: перезагружаем utterances (80..100%)
        if (onProgress) onProgress(90, 'Обновляю список реплик…');
        const fresh = await api.listUtterances(protocol.id, { limit: 500 });
        if (fresh?.items || Array.isArray(fresh)) {
            const items = fresh.items || fresh;
            window._currentUtterances = items;
            const transcriptList = document.querySelector('#panel-transcript .transcript-list');
            if (transcriptList && items.length) {
                transcriptList.innerHTML = items.map(u => renderUtteranceItem(u, [])).join('');
                wireImportantButtons(items, document.getElementById('panel-transcript'));
            }
        }
        if (onProgress) onProgress(100, `✅ Сохранено ${total} реплик в БД`);
    } catch (e) {
        console.error('[saveRemoteResultToBackend] failed:', e);
        if (onProgress) onProgress(0, '❌ Ошибка сохранения: ' + (e.message || e));
    }
}

// E241: очистка UI от старых результатов транскрипции.
// Backend делает DELETE utterance + DELETE decision в router (E153),
// но это занимает время. Показываем UI как чистый — пользователь сразу видит
// что "новый прогон" начался.
function clearTranscriptionUI(protocol) {
    // 1. Очистить транскрипт
    const transcriptPanel = document.getElementById('panel-transcript');
    if (transcriptPanel) {
        const list = transcriptPanel.querySelector('.transcript-list');
        if (list) list.innerHTML = '';
        const counter = transcriptPanel.querySelector('.transcript-toolbar .text-muted');
        if (counter) counter.textContent = '0 реплик';
    }

    // 2. Очистить in-memory данные (чтобы polling не показывал старые)
    if (typeof window._currentUtterances !== 'undefined') {
        window._currentUtterances = [];
    }

    // 3. Перерисовать вкладки (Решения / Важное) — теперь они пустые
    renderImportantTab(protocol.ownerDocument || document, protocol, []);
    renderDecisionsTab(protocol.ownerDocument || document, protocol);

    // 4. Сбросить badge "Важное" и "Решения"
    const impBadge = document.getElementById('important-badge');
    if (impBadge) impBadge.textContent = '';
    const decBadge = document.getElementById('decisions-badge');
    if (decBadge) decBadge.textContent = '';

    // 5. Удалить прогресс-бар (transcribe-progress) — updateProgressBar пересоздаст
    const progress = document.getElementById('transcribe-progress');
    if (progress) progress.remove();

    console.log('[startTranscribe] UI cleared');
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

    // E136: активируем вкладку транскрипта и убираем hidden
    const transcriptTab = document.querySelector('[aria-controls="panel-transcript"]');
    // E212: используем одну переменную panel — ниже она нужна
    // для доступа к #btn-pause-transcription / #btn-resume-transcription.
    // Раньше было transcriptPanel, а дальше по коду использовался `panel`
    // (NameError → падение каждого тика polling → clearInterval не вызывался).
    const panel = document.getElementById('panel-transcript');
    if (transcriptTab) transcriptTab.click();
    if (panel) panel.removeAttribute('hidden');

    // Poll every 2 seconds
    transcriptionPollInterval = setInterval(async () => {
        try {
            const progress = await api.getTranscriptionProgress(taskId);

            // Update UI with progress
            updateProgressBar(progress);

            // E186: подтягиваем реплики — корректная логика после_sec
            // Используем progress.segments_count (общее число реплик в БД)
            const segCount = progress.segments_count || 0;
            if (segCount > _lastUtteranceCount || _lastUtteranceCount === 0) {
                try {
                    // Запрашиваем все реплики ПОСЛЕ _lastRenderedSec
                    // Если _lastUtteranceCount == 0 (первый запрос) — берём все
                    const afterSec = _lastUtteranceCount === 0
                        ? 0
                        : _lastRenderedSec;
                    const newOnes = await api.listUtterances(protocol.id, {
                        limit: 500,
                        after_sec: afterSec,
                    });
                    const items = Array.isArray(newOnes)
                        ? newOnes
                        : (newOnes && newOnes.items) || [];
                    if (items.length > 0) {
                        await appendUtteranceItems(protocol.id, items);
                        // E186: всегда обновляем maxSec из реальных данных
                        const maxSec = Math.max(
                            ...items.map(u => parseFloat(u.start_sec || 0))
                        );
                        if (maxSec > _lastRenderedSec) {
                            _lastRenderedSec = maxSec;
                        }
                    }
                    // E186: обновляем счётчик ВСЕГДА — даже если items.length=0,
                    // но прогресс показывает больше реплик (например, после финального flush)
                    if (segCount > _lastUtteranceCount) {
                        _lastUtteranceCount = segCount;
                    }
                } catch (e) {
                    console.warn('Failed to fetch utterances:', e);
                }
            }

            // E150: Detect paused status → switch Pause/Resume buttons
            const btnPause = panel.querySelector('#btn-pause-transcription');
            const btnResume = panel.querySelector('#btn-resume-transcription');
            if (progress.status === 'paused') {
                if (btnPause) btnPause.style.display = 'none';
                if (btnResume) btnResume.style.display = '';
                toast.warning('Транскрипция на паузе. Можно продолжить.');
            } else if (['running', 'starting', 'queued'].includes(progress.status)) {
                if (btnPause) btnPause.style.display = '';
                if (btnResume) btnResume.style.display = 'none';
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
    // E133: append-only — добавляет новые реплики без перерисовки списка
    // E137: items уже могут быть grouped на бэкенде или сырыми —
    // на фронте мы их НЕ группируем, потому что speaker_id=null и
    // временные паузы < 2 сек редко значат смену темы.
    // Вместо этого показываем длинные сегменты с их start_sec и
    // timestamp, чтобы было понятно где границы.
    const panel = document.getElementById('panel-transcript');
    if (!panel) {
        console.warn('appendUtteranceItems: panel-transcript not found');
        return;
    }
    if (typeof renderUtteranceItem !== 'function') {
        console.warn('appendUtteranceItems: renderUtteranceItem not defined');
        return;
    }

    let list = panel.querySelector('.transcript-list');
    if (!list) {
        // Первая инициализация — создаём структуру
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

    // E239: wireDecisionButtons и wireGrammarAndEditButtons — локальные
    // для renderTranscriptTab, из глобальной appendUtteranceItems недоступны.
    // Убрано — иначе ReferenceError каждый раз.
    wireImportantButtons();

    // Обновляем счётчик в toolbar (E137: общее число реплик в DOM)
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
    // E163: при failed показываем ошибку в прогресс-баре
    let bar = document.getElementById('transcribe-progress');
    // E240: let вместо const — ниже pct переприсваивается в failed-ветке
    let pct = progress.progress_percent !== undefined && progress.progress_percent !== null
        ? progress.progress_percent
        : (progress.progress || 0);
    let msg;
    let barClass = 'progress-bar-fill';
    if (progress.status === 'failed') {
        msg = `❌ Ошибка: ${progress.message || 'неизвестная'}`;
        barClass = 'progress-bar-fill progress-failed';
        pct = pct || 100;  // заполняем красным чтобы видно
    } else {
        msg = progress.message || (pct < 5 ? 'Инициализация...' : pct < 95 ? 'Обработка аудио...' : 'Финализация...');
    }
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
                <div class="${barClass}" style="width: ${pct}%"></div>
            </div>
        `;
        document.body.appendChild(bar);
    } else {
        // E248: снимаем display:none если был скрыт (clearTranscriptionUI)
        bar.style.display = '';
        bar.querySelector('.progress-status').textContent = msg;
        bar.querySelector('.progress-percent').textContent = `${pct}%`;
        const fill = bar.querySelector('.progress-bar-fill');
        if (fill) {
            fill.className = barClass;
            fill.style.width = `${pct}%`;
        }
    }
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



// E182: Простой нативный плеер (50 строк вместо 400+).
// Браузер сам управляет play/pause/seek/volume/speed через controls.
// Нам нужен только API seekTo() для перехода по таймкоду реплики.
async function initMediaPlayer(rootEl, protocol) {
    if (!protocol || !protocol.audio_file) return;

    const container = rootEl.querySelector('#media-player-container');
    const video = container && container.querySelector('#media-video');
    if (!video) return;

    const filename = (container.dataset.filename || '').toLowerCase();
    const ext = (filename.match(/\.([a-z0-9]+)$/i) || [])[1] || 'mp4';

    const BACKEND_ORIGIN = window.__BACKEND_URL__
        || window.API_BASE_URL
        || 'http://127.0.0.1:8000';

    const mediaUrl = (protocol.audio_file.source === 'url' && protocol.audio_file.source_url)
        ? protocol.audio_file.source_url
        : `${BACKEND_ORIGIN}/api/v1/hmp/media/protocols/${protocol.id}/source.${ext}`;

    video.src = mediaUrl;

    // E188: ждём loadedmetadata (когда video.duration станет известен)
    // и вешаем обработчики на .timestamp для перехода по таймкоду.
    function wireTimestampClicks() {
        if (!rootEl) return;
        rootEl.querySelectorAll('.timestamp').forEach(ts => {
            ts.style.cursor = 'pointer';
            ts.title = 'Перемотать на ' + ts.textContent;
            // E188: клонируем чтобы убрать старые обработчики
            const clone = ts.cloneNode(true);
            ts.replaceWith(clone);
            clone.addEventListener('click', () => {
                const sec = parseFloat(clone.dataset.time);
                if (isNaN(sec)) return;
                if (!video.duration || isNaN(video.duration)) {
                    toast.warning('Медиа ещё не загружено');
                    return;
                }
                video.currentTime = Math.max(0, Math.min(sec, video.duration - 0.1));
                video.play().catch(() => {});
                toast.success(`▶ Перемотано на ${formatTimestamp(sec)}`);
            });
        });
    }

    // E188: привязываем когда duration станет известен
    if (video.readyState >= 1) {
        wireTimestampClicks();
    } else {
        video.addEventListener('loadedmetadata', wireTimestampClicks, { once: true });
    }

    // E182: API для перехода по таймкоду реплики
    window.audioPlayer = {
        seekTo: (sec) => {
            if (!video.duration || isNaN(video.duration)) {
                toast.warning('Медиа ещё не загружено');
                return false;
            }
            video.currentTime = Math.max(0, Math.min(sec, video.duration - 0.1));
            video.play().catch(() => {});
            return true;
        },
        get currentTime() { return video.currentTime; },
        get duration() { return video.duration; },
        get paused() { return video.paused; },
    };

    // E182: Event для совместимости со старым кодом
    window.addEventListener('audio-seek', (e) => {
        if (e.detail && typeof e.detail.sec === 'number') {
            window.audioPlayer.seekTo(e.detail.sec);
        }
    });
}
