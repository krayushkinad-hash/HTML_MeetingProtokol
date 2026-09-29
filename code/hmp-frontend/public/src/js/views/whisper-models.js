/**
 * Whisper Models Manager — UI для управления моделями Whisper (US-058)
 *
 * Позволяет:
 * - Видеть список всех моделей (size, downloaded, active)
 * - Скачивать модели (с прогрессом)
 * - Переключать активную модель
 * - Удалять модели
 * - Видеть cache directory
 */

// US-058: CSS for this view (injected automatically)
import { toast } from '../utils/toast.js';
import { api } from '../api/client.js';

const WHISPER_MODELS_CSS_URL = 'src/css/whisper-models.css';

let cssInjected = false;
function injectCSS() {
    if (cssInjected) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = WHISPER_MODELS_CSS_URL;
    document.head.appendChild(link);
    cssInjected = true;
}

const POLL_INTERVAL_MS = 1000;
const activePolls = new Map(); // model_name -> setTimeout ID

/**
 * Main render function for Whisper Models view.
 *
 * @param {HTMLElement} rootEl
 */
export async function renderWhisperModelsView(rootEl) {
    injectCSS();

    rootEl.innerHTML = `
        <div class="whisper-models-panel">
            <div class="whisper-models-header">
                <div>
                    <h2><i class="fa-solid fa-microphone"></i> Whisper Models</h2>
                    <p class="text-muted" style="margin: 4px 0 0;">
                        Управление моделями распознавания речи
                    </p>
                </div>
                <button class="whisper-btn" id="btn-refresh-models">
                    <i class="fa-solid fa-rotate"></i> Обновить
                </button>
            </div>

            <div class="whisper-cache-info">
                <strong>Cache directory:</strong>
                <code id="cache-dir">loading...</code>
                <br>
                <strong>Active model:</strong>
                <span class="whisper-badge whisper-badge-active" id="active-badge">—</span>
            </div>

            <div id="models-list" class="whisper-models-list">
                <div class="text-muted" style="grid-column: 1/-1; text-align: center; padding: 40px;">
                    <i class="fa-solid fa-spinner fa-spin"></i> Loading models...
                </div>
            </div>
        </div>
    `;

    document.getElementById('btn-refresh-models').addEventListener('click', () => loadModels(rootEl));

    await loadModels(rootEl);
}

/**
 * Load models from backend and render.
 */
async function loadModels(rootEl) {
    try {
        const data = await api.getWhisperModels();
        const active = data.active;
        document.getElementById('cache-dir').textContent = data.cache_dir;
        document.getElementById('active-badge').textContent = active;

        // Render models
        const listEl = document.getElementById('models-list');
        listEl.innerHTML = data.models.map(model => renderModelCard(model, model.name === active)).join('');

        // Cleanup: hide progress bars for models that are NOT downloaded
        // (E072: stale progress from previous download attempt)
        for (const model of data.models) {
            if (!model.downloaded) {
                hideProgressBar(model.name);
            }
        }

        // Attach handlers
        for (const model of data.models) {
            const card = listEl.querySelector(`[data-model="${model.name}"]`);
            if (!card) continue;

            // Download button
            const dlBtn = card.querySelector('.btn-download');
            if (dlBtn) {
                dlBtn.addEventListener('click', () => downloadModel(model.name, rootEl));
            }

            // Activate button
            const actBtn = card.querySelector('.btn-activate');
            if (actBtn) {
                actBtn.addEventListener('click', () => activateModel(model.name, rootEl));
            }

            // Delete button
            const delBtn = card.querySelector('.btn-delete');
            if (delBtn) {
                delBtn.addEventListener('click', () => deleteModel(model.name, rootEl));
            }
        }
    } catch (err) {
        console.error('Load models failed:', err);
        toast.error('Ошибка загрузки: ' + err.message);
        document.getElementById('models-list').innerHTML = `
            <div class="text-muted" style="grid-column: 1/-1; text-align: center; padding: 40px; color: #dc2626;">
                <i class="fa-solid fa-triangle-exclamation"></i> Ошибка загрузки моделей
            </div>
        `;
    }
}

/**
 * Render a single model card.
 */
function renderModelCard(model, isActive) {
    const statusClass = model.downloaded ? 'downloaded' : 'not-downloaded';
    const sizeMB = model.size_on_disk_mb ? `${model.size_on_disk_mb.toFixed(0)} MB` : '—';

    return `
        <div class="whisper-model-card ${statusClass} ${isActive ? 'active' : ''}" data-model="${model.name}">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div class="whisper-model-name">${model.name}</div>
                ${isActive ? '<span class="whisper-badge whisper-badge-active">ACTIVE</span>' : ''}
                ${model.downloaded ? '<span class="whisper-badge whisper-badge-downloaded">CACHED</span>' : '<span class="whisper-badge whisper-badge-not-downloaded">NOT CACHED</span>'}
            </div>
            <div class="whisper-model-meta">
                <div><strong>HF repo:</strong> <code>${model.repo}</code></div>
                <div><strong>Expected size:</strong> ${model.size_mb} MB</div>
                <div><strong>On disk:</strong> ${sizeMB}</div>
                ${model.path ? `<div style="word-break: break-all;"><strong>Path:</strong> <code style="font-size: 10px;">${model.path}</code></div>` : ''}
            </div>

            <!-- Progress container (shown only during download) -->
            <div class="whisper-progress-container" id="progress-container-${model.name}" style="display: none;">
                <div class="whisper-progress">
                    <div class="whisper-progress-bar" style="width: 0%"></div>
                </div>
                <div class="whisper-progress-info" id="progress-info-${model.name}"></div>
            </div>

            <div class="whisper-model-actions">
                ${!model.downloaded ? `
                    <button class="whisper-btn whisper-btn-primary btn-download">
                        <i class="fa-solid fa-download"></i> Скачать
                    </button>
                ` : ''}
                ${model.downloaded && !isActive ? `
                    <button class="whisper-btn whisper-btn-success btn-activate">
                        <i class="fa-solid fa-check"></i> Сделать активной
                    </button>
                ` : ''}
                ${model.downloaded ? `
                    <button class="whisper-btn whisper-btn-danger btn-delete">
                        <i class="fa-solid fa-trash"></i> Удалить
                    </button>
                ` : ''}
            </div>
        </div>
    `;
}

/**
 * Download model with progress polling.
 */
async function downloadModel(name, rootEl) {
    try {
        // Clean up any previous polling for this model
        if (activePolls.has(name)) {
            clearInterval(activePolls.get(name));
            activePolls.delete(name);
        }

        // Hide any stale progress from previous download
        hideProgressBar(name);

        toast.info(`Загрузка ${name}...`);
        const result = await api.downloadWhisperModel(name);
        toast.success(result.message || `Загрузка ${name} запущена`);

        // Show progress bar
        showProgressBar(name, 0);

        // Start polling (with safety: hide progress if poll fails repeatedly)
        let pollFailures = 0;
        const pollId = setInterval(async () => {
            try {
                const progress = await api.getWhisperModelProgress(name);
                pollFailures = 0;  // reset on success

                // E073: percent may be 0..1 (decimal) or 0..100
                // Detect format and normalize to 0..100
                let percent = progress.percent || 0;
                if (percent > 0 && percent <= 1) {
                    // Decimal format (0.05 = 5%)
                    percent = percent * 100;
                }
                percent = Math.min(100, percent);

                // DEBUG
                if (window.location.search.includes("debug")) {
                    console.log(`[poll ${name}] raw.percent=${progress.percent} -> ${percent.toFixed(2)}%, downloaded=${progress.downloaded_bytes}/${progress.total_bytes}, success=${progress.success}`);
                }

                showProgressBar(name, percent, progress);

                if (progress.success === true || progress.success === false || percent >= 100) {
                    clearInterval(pollId);
                    activePolls.delete(name);
                    if (progress.success) {
                        toast.success(`${name} загружена!`);
                        await loadModels(rootEl);
                    } else if (progress.success === false) {
                        toast.error(`Ошибка загрузки ${name}: ${progress.error || 'unknown'}`);
                        hideProgressBar(name);
                    }
                }
            } catch (err) {
                pollFailures++;
                console.error('Progress poll failed:', err);
                // After 3 failures, stop polling and hide stale progress
                if (pollFailures >= 3) {
                    clearInterval(pollId);
                    activePolls.delete(name);
                    hideProgressBar(name);
                    toast.error(`Потеряна связь с сервером при загрузке ${name}`);
                }
            }
        }, POLL_INTERVAL_MS);

        activePolls.set(name, pollId);
    } catch (err) {
        toast.error(`Ошибка: ${err.message}`);
    }
}

/**
 * Set active model.
 */
async function activateModel(name, rootEl) {
    try {
        await api.setActiveWhisperModel(name);
        toast.success(`Активная модель: ${name}`);
        await loadModels(rootEl);
    } catch (err) {
        toast.error(`Ошибка: ${err.message}`);
    }
}

/**
 * Delete model from cache.
 */
async function deleteModel(name, rootEl) {
    if (!confirm(`Удалить модель ${name} из кэша?\n\nФайл больше не сэкономит ~${name}MB диска.`)) {
        return;
    }
    try {
        const result = await api.deleteWhisperModel(name);
        if (result.deleted) {
            toast.success(`${name} удалена из кэша`);
        } else {
            toast.info(`${name} не была загружена`);
        }
        await loadModels(rootEl);
    } catch (err) {
        toast.error(`Ошибка: ${err.message}`);
    }
}

/**
 * Show progress bar for a model.
 */
function showProgressBar(name, percent, progress) {
    // Find by data-model attribute (more robust than id)
    const card = document.querySelector(`[data-model="${name}"]`);
    if (!card) {
        // Card not rendered yet — try id fallback
        const container = document.getElementById(`progress-container-${name}`);
        if (!container) {
            return;
        }
        return showProgressBarInContainer(container, percent, progress);
    }

    const container = card.querySelector(`#progress-container-${name}`);
    if (!container) {
        return;
    }
    return showProgressBarInContainer(container, percent, progress);
}

/**
 * Apply progress to existing container element.
 */
function showProgressBarInContainer(container, percent, progress) {
    container.style.display = "block";

    const bar = container.querySelector(".whisper-progress-bar");
    const info = container.querySelector(".whisper-progress-info");
    if (!bar || !info) {
        return;
    }

    // E073: Compute display percent from RAW bytes (not the percent value!).
    // percent may be 0..1 (decimal) or 0..100 (already multiplied).
    // Use raw bytes to avoid ambiguity.
    let displayPercent = 0;
    if (progress && progress.total_bytes > 0) {
        // Most reliable: calculate from downloaded_bytes / total_bytes
        displayPercent = (progress.downloaded_bytes / progress.total_bytes) * 100;
        // DEBUG: log to verify format
        if (window.location.search.includes("debug")) {
            console.log(`[progress] ${percent.toFixed(4)} raw=${progress.downloaded_bytes}/${progress.total_bytes} -> ${displayPercent.toFixed(2)}%`);
        }
    } else if (percent > 0) {
        // Fallback: detect format (0..1 vs 0..100)
        displayPercent = percent <= 1 ? percent * 100 : percent;
        if (window.location.search.includes("debug")) {
            console.log(`[progress fallback] percent=${percent} -> ${displayPercent}%`);
        }
    }
    displayPercent = Math.max(0, Math.min(100, displayPercent));

    // Direct inline style - takes priority over external CSS
    bar.style.width = displayPercent + "%";

    if (progress) {
        const downloadedMB = (progress.downloaded_bytes / 1024 / 1024).toFixed(1);
        const totalMB = (progress.total_bytes / 1024 / 1024).toFixed(0);
        const speed = (progress.speed_mbps || 0);
        const etaSec = (progress.eta_sec || 0);

        // Format speed: show "X MB/s" or "<0.1 MB/s" if very slow
        const speedStr = speed > 0.1 ? `${speed.toFixed(1)} MB/s` :
                          speed > 0.01 ? `${(speed * 1024).toFixed(0)} KB/s` :
                          `—`;

        // Format ETA: show "Xm Ys" or "Xs" or "—"
        let etaStr = "—";
        if (etaSec > 0 && etaSec < 86400) {
            if (etaSec > 3600) {
                const hours = Math.floor(etaSec / 3600);
                const mins = Math.floor((etaSec % 3600) / 60);
                etaStr = `${hours}h ${mins}m`;
            } else if (etaSec > 60) {
                const mins = Math.floor(etaSec / 60);
                const secs = Math.floor(etaSec % 60);
                etaStr = `${mins}m ${secs}s`;
            } else {
                etaStr = `${Math.floor(etaSec)}s`;
            }
        }

        info.innerHTML =
            `<span>${downloadedMB} / ${totalMB} MB</span>` +
            `<span>${displayPercent.toFixed(1)}% • ${speedStr} • ETA ${etaStr}</span>`;
    } else {
        info.innerHTML = `<span>Запуск загрузки...</span>`;
    }
}

/**
 * Hide progress bar.
 */
function hideProgressBar(name) {
    const container = document.getElementById(`progress-container-${name}`);
    if (container) container.style.display = "none";
}
