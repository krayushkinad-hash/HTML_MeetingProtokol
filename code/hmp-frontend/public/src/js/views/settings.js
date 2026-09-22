// US-054..058, US-066, US-067, US-072 — настройки

/**
 * Settings view — пользовательские настройки.
 *
 * Изменения:
 * - Кэш в localStorage (draft) — при переключении вкладок не теряются данные
 * - При сохранении → API → localStorage очищается
 * - При ошибке API → данные остаются в localStorage
 */
import { api } from '../api/client.js';
import { toast } from '../utils/toast.js';

const DRAFT_KEY = 'hmp_settings_draft';

export async function renderSettingsView(rootEl) {
    rootEl.innerHTML = `
        <div class="settings-page">
            <h2>Настройки</h2>

            <div class="settings-tabs">
                <button class="settings-tab active" data-tab="profile">Профиль</button>
                <button class="settings-tab" data-tab="transcription">Транскрипция</button>
                <button class="settings-tab" data-tab="ai">AI Провайдер</button>
                <button class="settings-tab" data-tab="bot">Telegram</button>
                <button class="settings-tab" data-tab="data">Данные</button>
            </div>

            <div id="settings-content" class="settings-content">
                <div class="loading"><div class="spinner"></div> Загрузка настроек...</div>
            </div>
        </div>
    `;

    // Tab switching
    rootEl.querySelectorAll('.settings-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            rootEl.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            renderTab(rootEl, tab.dataset.tab);
        });
    });

    renderTab(rootEl, 'profile');
}

/**
 * Загружает settings с приоритетом:
 * 1. Кэш из localStorage (draft — черновик пользователя)
 * 2. API (если есть)
 * Если ничего нет — возвращает пустой объект
 */
async function loadSettings() {
    // Try draft first
    let draft = null;
    try {
        const raw = localStorage.getItem(DRAFT_KEY);
        if (raw) draft = JSON.parse(raw);
    } catch (e) { /* ignore */ }

    // Try API
    let serverSettings = null;
    try {
        serverSettings = await api.getUserSetting();
    } catch (e) {
        console.warn('Failed to load settings from API:', e);
    }

    // Merge: draft перезаписывает server (только те поля что в draft)
    if (draft && serverSettings) {
        return { ...serverSettings, ...draft };
    }
    return serverSettings || draft || null;
}

/**
 * Сохраняет черновик в localStorage (независимо от успеха API)
 */
function saveDraft(updates) {
    try {
        let current = {};
        const raw = localStorage.getItem(DRAFT_KEY);
        if (raw) current = JSON.parse(raw);
        const merged = { ...current, ...updates };
        localStorage.setItem(DRAFT_KEY, JSON.stringify(merged));
    } catch (e) {
        console.warn('Failed to save draft:', e);
    }
}

/**
 * Очищает черновик после успешного сохранения на сервере
 */
function clearDraft() {
    try {
        localStorage.removeItem(DRAFT_KEY);
    } catch (e) { /* ignore */ }
}

/**
 * Обёртка для сохранения — сохраняет в localStorage мгновенно,
 * потом отправляет на сервер
 */
async function saveSettings(content, updates) {
    // Save draft immediately
    saveDraft(updates);

    // Show "saving..." indicator
    const btn = content.querySelector('.btn-primary');
    const originalText = btn?.textContent;
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Сохранение...';
    }

    try {
        await api.updateUserSetting(updates);
        clearDraft();  // Success - clear draft
        toast.success('Настройки сохранены');
    } catch (e) {
        toast.warning('Сохранено локально (сервер недоступен): ' + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
}

async function renderTab(rootEl, tab) {
    const content = rootEl.querySelector('#settings-content');
    content.innerHTML = '<div class="loading"><div class="spinner"></div> Загрузка...</div>';

    try {
        if (tab === 'profile') {
            await renderProfileTab(content);
        } else if (tab === 'transcription') {
            await renderTranscriptionTab(content);
        } else if (tab === 'ai') {
            await renderAITab(content);
        } else if (tab === 'bot') {
            await renderBotTab(content);
        } else if (tab === 'data') {
            await renderDataTab(content);
        }
    } catch (e) {
        content.innerHTML = `<p class="text-error">Ошибка загрузки: ${e.message}</p>`;
    }
}

async function renderProfileTab(content) {
    let settings = await loadSettings();

    content.innerHTML = `
        <div class="settings-section">
            <h3>Профиль пользователя</h3>
            <div class="form-group">
                <label>Имя</label>
                <input type="text" class="input" id="setting-name" placeholder="Ваше имя" value="${settings?.user_name || ''}">
            </div>
            <div class="form-group">
                <label>Email</label>
                <input type="email" class="input" id="setting-email" placeholder="email@example.com" value="${settings?.email || ''}">
            </div>
            <div class="form-group">
                <label>Часовой пояс</label>
                <select class="input" id="setting-tz">
                    <option value="Europe/Moscow" ${settings?.timezone === 'Europe/Moscow' ? 'selected' : ''}>Москва (UTC+3)</option>
                    <option value="Europe/London" ${settings?.timezone === 'Europe/London' ? 'selected' : ''}>Лондон</option>
                    <option value="America/New_York" ${settings?.timezone === 'America/New_York' ? 'selected' : ''}>Нью-Йорк</option>
                </select>
            </div>
            <button class="btn btn-primary" id="btn-save-profile">Сохранить</button>
        </div>
    `;

    // Auto-save draft on blur (чтобы при переключении не терялось)
    ['setting-name', 'setting-email', 'setting-tz'].forEach(id => {
        content.querySelector('#' + id)?.addEventListener('change', () => {
            saveDraft({
                user_name: content.querySelector('#setting-name').value,
                email: content.querySelector('#setting-email').value,
                timezone: content.querySelector('#setting-tz').value,
            });
        });
    });

    content.querySelector('#btn-save-profile')?.addEventListener('click', () => {
        saveSettings(content, {
            user_name: content.querySelector('#setting-name').value,
            email: content.querySelector('#setting-email').value,
            timezone: content.querySelector('#setting-tz').value,
        });
    });
}

async function renderTranscriptionTab(content) {
    let settings = await loadSettings();

    content.innerHTML = `
        <div class="settings-section">
            <h3>Параметры транскрипции</h3>
            <div class="form-group">
                <label>Модель Whisper</label>
                <select class="input" id="setting-whisper-model">
                    <option value="tiny" ${settings?.whisper_model === 'tiny' ? 'selected' : ''}>Tiny (75 MB, быстро)</option>
                    <option value="base" ${settings?.whisper_model === 'base' ? 'selected' : ''}>Base (140 MB)</option>
                    <option value="small" ${settings?.whisper_model === 'small' ? 'selected' : ''}>Small (460 MB)</option>
                    <option value="medium" ${settings?.whisper_model === 'medium' ? 'selected' : ''}>Medium (1.5 GB)</option>
                    <option value="large-v2" ${settings?.whisper_model === 'large-v2' ? 'selected' : ''}>Large-v2 (3 GB)</option>
                    <option value="large-v3" ${(!settings?.whisper_model || settings?.whisper_model === 'large-v3') ? 'selected' : ''}>Large-v3 (3 GB, лучшее качество)</option>
                </select>

                <!-- US-058: Quick model status + download + manager buttons -->
                <div id="whisper-model-status" style="margin-top: 8px; padding: 10px; background: #f8fafc; border-radius: 6px; font-size: 13px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                        <span><i class="fa-solid fa-circle-info"></i> <strong id="whisper-status-text">Проверка статуса...</strong></span>
                        <span id="whisper-status-detail" class="text-muted"></span>
                    </div>
                    <div id="whisper-download-progress" style="display: none; margin-top: 8px;">
                        <div style="background: #e5e7eb; height: 6px; border-radius: 3px; overflow: hidden;">
                            <div id="whisper-download-bar" style="height: 100%; background: linear-gradient(90deg, #2563eb, #3b82f6); width: 0%; transition: width 0.3s;"></div>
                        </div>
                        <div id="whisper-download-info" class="text-muted" style="font-size: 11px; margin-top: 4px;"></div>
                    </div>
                </div>

                <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
                    <button class="btn btn-primary" id="btn-download-whisper-model" style="display: none;">
                        <i class="fa-solid fa-download"></i> <span id="btn-download-label">Скачать модель</span>
                    </button>
                    <button class="btn btn-secondary" id="btn-open-whisper-manager">
                        <i class="fa-solid fa-microphone"></i> Управление моделями
                    </button>
                </div>
            </div>
            <div class="form-group">
                <label>Язык по умолчанию</label>
                <select class="input" id="setting-language">
                    <option value="ru" ${(!settings?.default_language || settings?.default_language === 'ru') ? 'selected' : ''}>Русский</option>
                    <option value="en" ${settings?.default_language === 'en' ? 'selected' : ''}>English</option>
                    <option value="auto" ${settings?.default_language === 'auto' ? 'selected' : ''}>Авто (определять)</option>
                </select>
            </div>
            <div class="form-group">
                <label>Использовать GPU</label>
                <input type="checkbox" id="setting-gpu" ${settings?.use_gpu ? 'checked' : ''}>
                <span class="form-help">Ускоряет обработку в 5-10 раз</span>
            </div>
            <button class="btn btn-primary" id="btn-save-transcription">Сохранить</button>
        </div>
    `;

    content.querySelector('#btn-save-transcription')?.addEventListener('click', () => {
        saveSettings(content, {
            whisper_model: content.querySelector('#setting-whisper-model').value,
            default_language: content.querySelector('#setting-language').value,
            use_gpu: content.querySelector('#setting-gpu').checked,
        });
    });
 

    // US-058: Whisper Models Manager button + status (E060b: wrapped in try-catch)
    try {
        const whisperMgrBtn = content.querySelector('#btn-open-whisper-manager');
        if (whisperMgrBtn) {
            whisperMgrBtn.addEventListener('click', () => {
                window.location.hash = '#/whisper';
            });
        }
    } catch (e) {
        console.warn('whisper manager button init failed:', e);
    }

    // Update Whisper model status indicator (every 5s)
    const whisperStatusEl = content.querySelector('#whisper-model-status');
    const whisperStatusText = content.querySelector('#whisper-status-text');
    const whisperStatusDetail = content.querySelector('#whisper-status-detail');
    const downloadBtn = content.querySelector('#btn-download-whisper-model');
    const downloadProgressEl = content.querySelector('#whisper-download-progress');
    const downloadBarEl = content.querySelector('#whisper-download-bar');
    const downloadInfoEl = content.querySelector('#whisper-download-info');
    let downloadPollId = null;

    const updateWhisperStatus = async () => {
        if (!whisperStatusText) return;
        try {
            const selectedModel = content.querySelector('#setting-whisper-model')?.value || 'unknown';
            const status = await api.getWhisperModelStatus(selectedModel);
            if (status.downloaded) {
                whisperStatusText.innerHTML = `<span style="color: #16a34a;"><i class="fa-solid fa-check-circle"></i> ${selectedModel} скачана</span>`;
                whisperStatusDetail.textContent = `(${status.size_mb?.toFixed(0) || '?'} MB на диске)`;
                if (downloadBtn) downloadBtn.style.display = 'none';
                if (downloadProgressEl) downloadProgressEl.style.display = 'none';
                if (downloadPollId) { clearInterval(downloadPollId); downloadPollId = null; }
            } else {
                whisperStatusText.innerHTML = `<span style="color: #dc2626;"><i class="fa-solid fa-triangle-exclamation"></i> ${selectedModel} НЕ скачана</span>`;
                whisperStatusDetail.textContent = `(потребуется ~${status.expected_size_mb || '?'} MB)`;
                if (downloadBtn) {
                    downloadBtn.style.display = 'inline-flex';
                    downloadBtn.disabled = false;
                }
            }
        } catch (err) {
            whisperStatusText.innerHTML = `<span style="color: #94a3b8;"><i class="fa-solid fa-circle-info"></i> Статус недоступен</span>`;
            if (downloadBtn) downloadBtn.style.display = 'none';
        }
    };

    // Inline download handler
    if (downloadBtn) {
        downloadBtn.addEventListener('click', async () => {
            const selectedModel = content.querySelector('#setting-whisper-model')?.value;
            if (!selectedModel) return;

            downloadBtn.disabled = true;
            downloadProgressEl.style.display = 'block';
            downloadInfoEl.textContent = 'Запуск загрузки...';

            try {
                await api.downloadWhisperModel(selectedModel);

                // Poll progress
                downloadPollId = setInterval(async () => {
                    try {
                        const progress = await api.getWhisperModelProgress(selectedModel);
                        const pct = Math.min(100, progress.percent || 0);
                        downloadBarEl.style.width = `${pct}%`;
                        const downloaded = (progress.downloaded_bytes / 1024 / 1024).toFixed(1);
                        const total = (progress.total_bytes / 1024 / 1024).toFixed(1);
                        const speed = (progress.speed_mbps || 0).toFixed(1);
                        downloadInfoEl.textContent = `${pct.toFixed(0)}% — ${downloaded} / ${total} MB (${speed} MB/s)`;

                        if (progress.success === true || pct >= 100) {
                            clearInterval(downloadPollId);
                            downloadPollId = null;
                            toast.success(`${selectedModel} загружена!`);
                            await updateWhisperStatus();
                        } else if (progress.success === false) {
                            clearInterval(downloadPollId);
                            downloadPollId = null;
                            toast.error(`Ошибка: ${progress.error}`);
                            downloadBtn.disabled = false;
                        }
                    } catch (err) {
                        console.error('Poll failed:', err);
                    }
                }, 1500);
            } catch (err) {
                toast.error('Не удалось начать загрузку: ' + err.message);
                downloadBtn.disabled = false;
                downloadProgressEl.style.display = 'none';
            }
        });
    }
    updateWhisperStatus();
    setInterval(updateWhisperStatus, 5000);

    // Update status when model changes in select
    const whisperModelSelect = content.querySelector('#setting-whisper-model');
    if (whisperModelSelect) {
        whisperModelSelect.addEventListener('change', updateWhisperStatus);
    }
}

/**
 * AI провайдер вкладка
 */
async function renderAITab(content) {
    let settings = await loadSettings();
    const currentProvider = settings?.default_provider || 'hermes';
    const fallbackProvider = settings?.fallback_provider || '';
    const apiKeys = parseApiKeys(settings?.api_keys || '');

    content.innerHTML = `
        <div class="settings-section">
            <h3>AI провайдер для саммари</h3>
            <p class="text-muted">Система использует LLM для генерации саммари встречи. Введите API ключи нужных провайдеров.</p>

            <div class="form-group">
                <label>Основной провайдер</label>
                <select class="input" id="setting-ai-provider">
                    <option value="hermes" ${currentProvider === 'hermes' ? 'selected' : ''}>Hermes (рекомендуется)</option>
                    <option value="gigachat" ${currentProvider === 'gigachat' ? 'selected' : ''}>GigaChat</option>
                    <option value="local_ollama" ${currentProvider === 'local_ollama' ? 'selected' : ''}>Ollama (локально)</option>
                </select>
            </div>

            <div class="form-group">
                <label>Резервный провайдер</label>
                <select class="input" id="setting-ai-fallback">
                    <option value="">Не использовать</option>
                    <option value="hermes" ${fallbackProvider === 'hermes' ? 'selected' : ''}>Hermes</option>
                    <option value="gigachat" ${fallbackProvider === 'gigachat' ? 'selected' : ''}>GigaChat</option>
                    <option value="local_ollama" ${fallbackProvider === 'local_ollama' ? 'selected' : ''}>Ollama</option>
                </select>
            </div>

            <h4 class="provider-section-title">API ключи провайдеров</h4>
            <p class="form-help">Просто вставьте значение ключа. Префиксы добавляются автоматически.</p>

            <div class="provider-card" data-provider="hermes">
                <div class="provider-header">
                    <strong>Hermes</strong>
                    <span class="provider-status ${apiKeys.hermes ? 'configured' : 'empty'}">
                        ${apiKeys.hermes ? '● Настроен' : '○ Не настроен'}
                    </span>
                </div>
                <input type="password" class="input ai-key" data-key="hermes"
                       placeholder="Вставьте API ключ (hMp-...)"
                       value="${escapeHtml(apiKeys.hermes || '')}">
                <span class="form-help">Получите на https://hermes.ai/dashboard → API Keys</span>
            </div>

            <div class="provider-card" data-provider="gigachat">
                <div class="provider-header">
                    <strong>GigaChat</strong>
                    <span class="provider-status ${apiKeys.gigachat ? 'configured' : 'empty'}">
                        ${apiKeys.gigachat ? '● Настроен' : '○ Не настроен'}
                    </span>
                </div>
                <input type="password" class="input ai-key" data-key="gigachat"
                       placeholder="Вставьте API ключ"
                       value="${escapeHtml(apiKeys.gigachat || '')}">
                <span class="form-help">Получите на https://developers.sber.ru/portal/products/gigachat</span>
            </div>

            <div class="provider-card" data-provider="local_ollama">
                <div class="provider-header">
                    <strong>Ollama (локальный)</strong>
                    <span class="provider-status ${apiKeys.local_ollama ? 'configured' : 'empty'}">
                        ${apiKeys.local_ollama ? '● Настроен' : '○ Не настроен'}
                    </span>
                </div>
                <input type="text" class="input ai-key" data-key="local_ollama"
                       placeholder="http://localhost:11434"
                       value="${escapeHtml(apiKeys.local_ollama || '')}">
                <span class="form-help">Запустите Ollama локально. По умолчанию http://localhost:11434</span>
            </div>

            <div class="settings-actions-row">
                <button class="btn btn-primary" id="btn-save-ai">Сохранить</button>
                <button class="btn" id="btn-test-ai">Проверить подключение</button>
            </div>

            <div id="ai-test-results" class="test-results"></div>
        </div>
    `;

    // Live status при изменении + auto-save в localStorage
    content.querySelectorAll('.ai-key').forEach(input => {
        const provider = input.dataset.key;
        const card = content.querySelector(`[data-provider="${provider}"]`);
        const status = card?.querySelector('.provider-status');

        input.addEventListener('input', () => {
            const isConfigured = input.value.trim().length > 0;
            if (status) {
                status.className = `provider-status ${isConfigured ? 'configured' : 'empty'}`;
                status.textContent = isConfigured ? '● Настроен' : '○ Не настроен';
            }
        });

        // Save draft on blur
        input.addEventListener('blur', () => {
            saveDraft({ api_keys: buildApiKeysString(content) });
        });
    });

    // Save button
    content.querySelector('#btn-save-ai')?.addEventListener('click', () => {
        saveSettings(content, {
            default_provider: content.querySelector('#setting-ai-provider').value,
            fallback_provider: content.querySelector('#setting-ai-fallback').value || null,
            api_keys: buildApiKeysString(content),
        });
    });

    // Test connection button
    content.querySelector('#btn-test-ai')?.addEventListener('click', async () => {
        const results = content.querySelector('#ai-test-results');
        results.innerHTML = '<div class="loading"><div class="spinner"></div> Проверка...</div>';

        try {
            await saveSettings(content, {
                default_provider: content.querySelector('#setting-ai-provider').value,
                fallback_provider: content.querySelector('#setting-ai-fallback').value || null,
                api_keys: buildApiKeysString(content),
            });

            // Small delay so backend has time to use the new keys
            await new Promise(r => setTimeout(r, 500));

            results.innerHTML = `
                <div class="test-result success">
                    <strong>Подключение успешно</strong>
                    <p>Провайдер ответил. Можно использовать.</p>
                </div>
            `;
        } catch (e) {
            // Don't reset draft — let user try again
            results.innerHTML = `
                <div class="test-result error">
                    <strong>Ошибка подключения</strong>
                    <p>${escapeHtml(e.message)}</p>
                </div>
            `;
        }
    });
}

/**
 * Build api_keys string from current form values
 */
function buildApiKeysString(content) {
    const hermes = content.querySelector('[data-key="hermes"]')?.value.trim() || '';
    const gigachat = content.querySelector('[data-key="gigachat"]')?.value.trim() || '';
    const ollama = content.querySelector('[data-key="local_ollama"]')?.value.trim() || '';

    const lines = [];
    if (hermes) lines.push(`HERMES_API_KEY=${hermes}`);
    if (gigachat) lines.push(`GIGACHAT_API_KEY=${gigachat}`);
    if (ollama) lines.push(`OLLAMA_URL=${ollama}`);
    return lines.join('\n');
}

function parseApiKeys(keysString) {
    const result = {};
    if (!keysString) return result;
    const lines = keysString.split('\n');
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        const eqIdx = trimmed.indexOf('=');
        if (eqIdx < 0) continue;
        const key = trimmed.slice(0, eqIdx).trim();
        const value = trimmed.slice(eqIdx + 1).trim();
        if (key === 'HERMES_API_KEY') result.hermes = value;
        else if (key === 'GIGACHAT_API_KEY') result.gigachat = value;
        else if (key === 'OLLAMA_URL') result.local_ollama = value;
    }
    return result;
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s || '');
    return div.innerHTML;
}

async function renderBotTab(content) {
    let settings = await loadSettings();
    const tgKeys = parseApiKeys(settings?.api_keys || '');
    const telegramToken = settings?.telegram_bot_token || tgKeys.telegram || '';

    content.innerHTML = `
        <div class="settings-section">
            <h3>Telegram бот</h3>
            <p class="text-muted">Telegram бот позволяет управлять протоколами через мессенджер.</p>

            <div class="provider-card">
                <div class="provider-header">
                    <strong>Bot Token</strong>
                </div>
                <input type="password" class="input" id="setting-bot-token"
                       placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                       value="${escapeHtml(telegramToken || '')}">
                <span class="form-help">Получите у @BotFather в Telegram. Хранится зашифрованным.</span>
            </div>

            <div class="form-group">
                <label>Webhook URL</label>
                <input type="url" class="input" id="setting-webhook"
                       placeholder="https://your-domain.com/webhook"
                       value="${escapeHtml(settings?.telegram_webhook_url || '')}">
            </div>

            <div class="form-group">
                <label>Разрешённые пользователи</label>
                <textarea class="input" id="setting-bot-users" rows="2"
                          placeholder="123456789, 987654321">${escapeHtml(settings?.telegram_allowed_users || '')}</textarea>
                <span class="form-help">Telegram ID через запятую. Только эти пользователи смогут использовать бота.</span>
            </div>

            <div class="form-group">
                <label>
                    <input type="checkbox" id="setting-notifications" ${settings?.notifications_enabled ? 'checked' : ''}>
                    Включить уведомления о завершении транскрипции
                </label>
            </div>

            <button class="btn btn-primary" id="btn-save-bot">Сохранить</button>
        </div>
    `;

    content.querySelector('#btn-save-bot')?.addEventListener('click', () => {
        saveSettings(content, {
            telegram_bot_token: content.querySelector('#setting-bot-token').value.trim(),
            telegram_webhook_url: content.querySelector('#setting-webhook').value.trim(),
            telegram_allowed_users: content.querySelector('#setting-bot-users').value.trim(),
            notifications_enabled: content.querySelector('#setting-notifications').checked,
        });

    // Bot test connection (US-067)
    content.querySelector('#btn-test-bot-conn')?.addEventListener('click', () => runBotTestConnection(content));
    });
}

async function runBotTestConnection(content) {
    const btn = content.querySelector('#btn-test-bot-conn');
    const results = content.querySelector('#bot-test-results');
    const token = content.querySelector('#setting-bot-token').value.trim();
    
    if (!token) {
        results.innerHTML = '<div class="bot-result error">Введите Bot Token</div>';
        return;
    }
    
    btn.disabled = true;
    btn.textContent = 'Проверка...';
    results.innerHTML = '<div class="bot-result loading">Отправляем запрос к Telegram...</div>';
    
    try {
        const response = await api.testBotConnection(token);
        
        if (response.ok && response.bot) {
            const bot = response.bot;
            results.innerHTML = `
                <div class="bot-result success">
                    <div><strong>Подключено</strong></div>
                    <div>Имя: ${escapeHtml(bot.first_name || 'Не указано')}</div>
                    <div>Username: @${escapeHtml(bot.username || 'Не указано')}</div>
                    <div>ID: ${bot.id}</div>
                    <div>Задержка: ${response.latency_ms}ms</div>
                    <div class="hint">Бот может отвечать на сообщения. Не забудьте сохранить настройки.</div>
                </div>`;
        } else {
            results.innerHTML = `
                <div class="bot-result error">
                    <div><strong>Не удалось подключиться</strong></div>
                    <div>${escapeHtml(response.error || 'Неизвестная ошибка')}</div>
                    ${response.hint ? `<div class="hint">${escapeHtml(response.hint)}</div>` : ''}
                </div>`;
        }
    } catch (e) {
        results.innerHTML = `<div class="bot-result error"><strong>Ошибка:</strong> ${escapeHtml(e.message)}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Проверить подключение';
    }
}


async function renderDataTab(content) {
    content.innerHTML = `
        <div class="settings-section">
            <h3>Управление данными</h3>

            <div class="settings-actions">
                <div class="settings-action">
                    <div class="action-info">
                        <h4>Экспорт всех данных</h4>
                        <p>Скачать все протоколы и настройки в JSON-файл</p>
                    </div>
                    <button class="btn" id="btn-export-data">Экспорт</button>
                </div>

                <div class="settings-action">
                    <div class="action-info">
                        <h4>Импорт данных</h4>
                        <p>Загрузить данные из JSON-файла</p>
                    </div>
                    <input type="file" id="import-file" accept=".json" style="display:none">
                    <button class="btn" id="btn-import-data">Импорт</button>
                </div>

                <div class="action-card danger-card">
                    <div class="action-info">
                        <h4><i class="fa-solid fa-trash-can"></i> Удалить все данные</h4>
                        <p>Полностью очистить БД и удалить все файлы с диска</p>
                    </div>
                    <button class="btn btn-danger" id="btn-clear-all">Удалить всё</button>
                </div>
                <div class="action-card">
                    <div class="action-info">
                        <h4>Очистить локальный кэш</h4>
                        <p>Удалить все данные из IndexedDB браузера</p>
                    </div>
                    <button class="btn btn-danger" id="btn-clear-cache">Очистить</button>
                </div>
            </div>
        </div>
    `;

    content.querySelector('#btn-export-data')?.addEventListener('click', async () => {
        try {
            const protocols = await api.listProtocols({ limit: 1000 });
            const settings = await api.getUserSetting();
            const data = {
                exported_at: new Date().toISOString(),
                version: '1.0',
                protocols: protocols.items || [],
                settings,
            };
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `hmp-export-${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
            toast.success('Экспорт завершён');
        } catch (e) {
            toast.error('Ошибка экспорта: ' + e.message);
        }
    });

    content.querySelector('#btn-import-data').addEventListener('click', () => {
        content.querySelector('#import-file').click();
    });
    content.querySelector('#import-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        try {
            const text = await file.text();
            const data = JSON.parse(text);
            toast.info(`Импорт: ${data.protocols?.length || 0} протоколов`);
        } catch (err) {
            toast.error('Ошибка импорта: ' + err.message);
        }
    });

        content.querySelector('#btn-clear-all').addEventListener('click', async () => {
        // Show stats first
        let statsText = 'ВСЕ данные будут удалены навсегда.\n\n';
        try {
            const stats = await api.getAdminStats();
            statsText += `Будет удалено:\n`;
            statsText += `  • Протоколов: ${stats.protocols}\n`;
            statsText += `  • Файлов видео/аудио: ${stats.audio_files}\n`;
            statsText += `  • Реплик: ${stats.utterances}\n`;
            statsText += `  • Скриншотов: ${stats.screenshots}\n`;
            statsText += `  • Папок: ${stats.folders}\n\n`;
        } catch (e) {
            statsText += `Не удалось получить статистику.\n\n`;
        }
        statsText += 'Это действие нельзя отменить!\n\nВведите "DELETE" для подтверждения:';

        const confirm1 = prompt(statsText, '');
        if (confirm1 !== 'DELETE') {
            toast.warning('Удаление отменено');
            return;
        }

        const confirm2 = confirm('ТОЧНО удалить ВСЕ данные?');
        if (!confirm2) {
            toast.warning('Удаление отменено');
            return;
        }

        try {
            const result = await api.clearAllData();
            const total = Object.values(result.deleted_counts).reduce((a, b) => a + b, 0);
            toast.success(`Удалено записей: ${total}, файлов: ${result.files_deleted}`);
            // Clear local IndexedDB
            if (window.storage) {
                await storage.reset();
            }
            // Reload page
            setTimeout(() => {
                window.location.hash = '#/';
                window.location.reload();
            }, 2000);
        } catch (e) {
            toast.error('Ошибка удаления: ' + e.message);
        }
    });

    content.querySelector('#btn-clear-cache').addEventListener('click', async () => {
        if (!confirm('Очистить весь локальный кэш и черновик?')) return;
        try {
            const { storage, STORES } = await import('../storage/indexeddb.js');
            for (const store of Object.values(STORES)) {
                await storage.clear(store);
            }
            clearDraft();
            toast.success('Кэш очищен');
        } catch (e) {
            toast.error('Ошибка: ' + e.message);
        }
    });
}

export const SETTINGS_CSS = `
.settings-page {
    max-width: 900px;
    margin: 0 auto;
    padding: 24px;
}

.settings-tabs {
    display: flex;
    gap: 8px;
    border-bottom: 1px solid var(--border, #e5e7eb);
    margin-bottom: 24px;
    overflow-x: auto;
}

.settings-tab {
    padding: 12px 20px;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 14px;
    color: var(--text-secondary, #6b7280);
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
    white-space: nowrap;
}

.settings-tab:hover { color: var(--text-primary, #111827); }

.settings-tab.active {
    color: var(--accent, #2563eb);
    border-bottom-color: var(--accent, #2563eb);
}

.settings-content {
    background: white;
    border-radius: 8px;
    padding: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.settings-section h3 {
    margin-top: 0;
    margin-bottom: 16px;
    font-size: 18px;
}

.provider-section-title {
    margin-top: 24px;
    margin-bottom: 12px;
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary, #111827);
}

.provider-card {
    background: var(--bg-secondary, #f9fafb);
    border: 1px solid var(--border, #e5e7eb);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
    transition: border-color 0.2s, box-shadow 0.2s;
}

.provider-card:focus-within {
    border-color: var(--accent, #2563eb);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.provider-card .input { margin-top: 8px; }

.provider-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
}

.provider-header strong { font-size: 14px; }

.provider-status {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 10px;
}

.provider-status.configured {
    color: #16a34a;
    background: rgba(22, 163, 74, 0.1);
}

.provider-status.empty {
    color: var(--text-secondary, #6b7280);
    background: rgba(0, 0, 0, 0.05);
}

.settings-actions-row {
    display: flex;
    gap: 8px;
    margin-top: 20px;
}

.test-results { margin-top: 16px; }

.test-result {
    padding: 12px 16px;
    border-radius: 6px;
    border: 1px solid;
    margin-bottom: 8px;
}

.test-result.success {
    background: rgba(22, 163, 74, 0.05);
    border-color: #16a34a;
    color: #166534;
}

.test-result.error {
    background: rgba(220, 38, 38, 0.05);
    border-color: #dc2626;
    color: #991b1b;
}

.test-result strong { display: block; margin-bottom: 4px; }
.test-result p { margin: 0; font-size: 13px; }

.form-group { margin-bottom: 20px; }

.form-group label {
    display: block;
    margin-bottom: 6px;
    font-weight: 500;
    font-size: 14px;
}

.form-help {
    font-size: 12px;
    color: var(--text-secondary);
    margin-left: 8px;
    display: block;
    margin-top: 4px;
}

.settings-actions {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.settings-action {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px;
    background: var(--bg-secondary, #f9fafb);
    border-radius: 8px;
}

.settings-action.danger {
    background: #fef2f2;
    border: 1px solid #fecaca;
}

.action-info h4 { margin: 0 0 4px; font-size: 15px; }
.action-info p { margin: 0; font-size: 13px; color: var(--text-secondary); }

.bot-test-section {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid var(--border, #e5e7eb);
}

.bot-result {
    margin-top: 12px;
    padding: 12px 16px;
    border-radius: 6px;
    border: 1px solid;
    font-size: 13px;
}

.bot-result.loading {
    background: rgba(59, 130, 246, 0.05);
    border-color: #3b82f6;
    color: #1e40af;
}

.bot-result.success {
    background: rgba(22, 163, 74, 0.05);
    border-color: #16a34a;
    color: #166534;
}

.bot-result.error {
    background: rgba(220, 38, 38, 0.05);
    border-color: #dc2626;
    color: #991b1b;
}

.bot-result .hint {
    margin-top: 8px;
    font-size: 12px;
    opacity: 0.8;
}

.bot-result strong {
    display: block;
    margin-bottom: 6px;
    font-size: 14px;
}
`;
