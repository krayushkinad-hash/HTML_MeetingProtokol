// US-001 — загрузка файла; US-002 — HTTPS URL; US-018 — drag-and-drop

/**
 * Upload view (F-HMP-1, US-001..004).
 *
 * Drag-and-drop + выбор файла, два таба: локальный файл и HTTPS ссылка.
 */
import { api } from '../api/client.js';
import { toast } from '../utils/toast.js';

// E173: webm, opus, avi, mov, 3gp, mka — теперь поддерживаются
const ALLOWED_EXTENSIONS = [
    // Аудио
    'mp3', 'wav', 'm4a', 'ogg', 'flac', 'opus', 'webm', 'aac', 'mka',
    // Видео
    'mp4', 'mkv', 'webm', 'mov', 'avi', '3gp', 'ogv',
];
const MAX_SIZE_MB = 10240; // 10 GB

export function renderUploadView(rootEl) {
    rootEl.innerHTML = `
        <h2><i class="fa-regular fa-folder"></i> Загрузка файла</h2>

        <div class="toolbar" role="tablist" style="margin-bottom:24px;">
            <button class="btn" id="tab-local" role="tab" aria-selected="true"><i class="fa-regular fa-file-lines"></i> Локальный файл</button>
            <button class="btn" id="tab-url" role="tab" aria-selected="false"><i class="fa-solid fa-link"></i> По ссылке</button>
        </div>

        <div id="tab-local-panel">
            <div class="upload-zone" id="drop-zone" tabindex="0" role="button" aria-label="Загрузить файл">
                <div class="upload-zone-icon"><i class="fa-regular fa-folder-open"></i></div>
                <div>Перетащите файл сюда или кликните для выбора</div>
                <div class="text-muted" style="margin-top:8px;">mp3, wav, mp4, mkv до ${MAX_SIZE_MB / 1024} ГБ</div>
                <input type="file" id="file-input" accept=".${ALLOWED_EXTENSIONS.join(',.')}" style="display:none">
            </div>
            <div id="file-info" class="hidden" style="margin-top:16px;"></div>
        </div>

        <div id="tab-url-panel" class="hidden">
            <div class="card">
                <label class="text-muted">Ссылка из облака (Яндекс.Диск, Google Drive, Mail.ru)</label>
                <input type="url" class="input" id="url-input" placeholder="https://drive.google.com/...">
            </div>
        </div>

        <div class="card" style="margin-top:24px;">
            <h3>Параметры встречи</h3>
            <div class="flex-col" style="gap:12px;">
                <input class="input" id="title-input" placeholder="Название встречи *" required>
                <input class="input" id="date-input" type="date" required>
                <input class="input" id="location-input" placeholder="Место (опционально)">
                <input class="input" id="chair-input" placeholder="Председатель (опционально)">
                <textarea class="textarea" id="agenda-input" placeholder="Повестка (опционально)"></textarea>
            </div>
        </div>

        <div class="toolbar" style="margin-top:24px;">
            <button class="btn btn-primary" id="submit-btn">⬆ Загрузить</button>
            <button class="btn" onclick="window.location.hash='#/'">Отмена</button>
        </div>

        <div id="progress" class="hidden" style="margin-top:16px;">
            <div class="spinner"></div>
            <span id="progress-text">Загрузка...</span>
            <progress id="progress-bar" max="100" value="0" style="width:100%;"></progress>
        </div>
    `;

    // Tab switching
    const tabLocal = document.getElementById('tab-local');
    const tabUrl = document.getElementById('tab-url');
    const localPanel = document.getElementById('tab-local-panel');
    const urlPanel = document.getElementById('tab-url-panel');

    tabLocal.addEventListener('click', () => {
        tabLocal.setAttribute('aria-selected', 'true');
        tabUrl.setAttribute('aria-selected', 'false');
        localPanel.classList.remove('hidden');
        urlPanel.classList.add('hidden');
    });
    tabUrl.addEventListener('click', () => {
        tabUrl.setAttribute('aria-selected', 'true');
        tabLocal.setAttribute('aria-selected', 'false');
        urlPanel.classList.remove('hidden');
        localPanel.classList.add('hidden');
    });

    // Default date = today
    document.getElementById('date-input').valueAsDate = new Date();

    // File selection
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const fileInfo = document.getElementById('file-info');
    let selectedFile = null;

    function selectFile(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (!ALLOWED_EXTENSIONS.includes(ext)) {
            toast.error(`Формат .${ext} не поддерживается. Допустимо: ${ALLOWED_EXTENSIONS.join(', ')}`);
            return;
        }
        if (file.size > MAX_SIZE_MB * 1024 * 1024) {
            toast.error(`Файл слишком большой (${(file.size / 1024 / 1024 / 1024).toFixed(2)} ГБ). Максимум: ${MAX_SIZE_MB / 1024} ГБ`);
            return;
        }
        selectedFile = file;
        fileInfo.innerHTML = `
            <div class="card">
                <div><strong>${escapeHtml(file.name)}</strong></div>
                <div class="text-muted">${(file.size / 1024 / 1024).toFixed(2)} МБ · ${ext.toUpperCase()}</div>
            </div>
        `;
        fileInfo.classList.remove('hidden');
    }

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileInput.click();
        }
    });
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) selectFile(e.target.files[0]);
    });

    // Submit
    document.getElementById('submit-btn').addEventListener('click', async () => {
        const title = document.getElementById('title-input').value.trim();
        const date = document.getElementById('date-input').value;
        if (!title || !date) {
            toast.error('Заполните название и дату');
            return;
        }

        const isLocal = !document.getElementById('tab-local-panel').classList.contains('hidden');
        const url = document.getElementById('url-input').value.trim();

        if (isLocal && !selectedFile) {
            toast.error('Выберите файл');
            return;
        }
        if (!isLocal && !url) {
            toast.error('Введите ссылку');
            return;
        }

        const progressEl = document.getElementById('progress');
        const progressBar = document.getElementById('progress-bar');
        const progressText = document.getElementById('progress-text');
        progressEl.classList.remove('hidden');
        progressBar.value = 0;

        try {
            const data = {
                title,
                date,
                location: document.getElementById('location-input').value || null,
                chair: document.getElementById('chair-input').value || null,
                agenda: document.getElementById('agenda-input').value || null,
            };

            if (isLocal) {
                progressText.textContent = 'Загрузка файла...';
                const protocol = await api.createProtocol(selectedFile, data);
                progressBar.value = 100;
                toast.success(`Протокол создан: ${protocol.title}`);
                setTimeout(() => window.location.hash = `#/protocols/${protocol.id}`, 500);
            } else {
                progressText.textContent = 'Скачивание по ссылке...';
                progressBar.value = 30;
                const protocol = await api.createProtocolFromUrl(url, data);
                progressBar.value = 100;
                toast.success(`Протокол создан: ${protocol.title}`);
                setTimeout(() => window.location.hash = `#/protocols/${protocol.id}`, 500);
            }
        } catch (err) {
            toast.error(`Ошибка: ${err.message}`);
            progressEl.classList.add('hidden');
        }
    });
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}
