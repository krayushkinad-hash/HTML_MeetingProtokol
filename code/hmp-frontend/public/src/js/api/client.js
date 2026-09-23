/**
 * API Client — типизированная обёртка над fetch.
 *
 * US-001..US-072 — все API методы
 *
 * Автоматически:
 * - пробрасывает X-Correlation-Id (NFR §5.9)
 * - обрабатывает RFC 7807 Problem Details (NFR §5.4)
 * - retry с exponential backoff для network errors
 */

const API_BASE = 'http://127.0.0.1:8000/api/v1/hmp';
const MAX_RETRIES = 3;
const INITIAL_BACKOFF_MS = 1000;

export class ApiError extends Error {
    constructor(problem) {
        super(problem.detail || problem.title || 'API Error');
        this.status = problem.status;
        this.code = problem.code;
        this.problem = problem;
        this.correlationId = problem.correlation_id;
    }
}

function uuidv4() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
        const r = (Math.random() * 16) | 0;
        return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
}

async function request(method, path, { body, formData, headers, idempotencyKey, signal } = {}) {
    const url = `${API_BASE}${path}`;
    const finalHeaders = {
        'X-Correlation-Id': uuidv4(),
        ...headers,
    };

    let payload;
    if (formData) {
        payload = formData;
    } else if (body !== undefined) {
        payload = JSON.stringify(body);
        finalHeaders['Content-Type'] = 'application/json';
    }

    if (idempotencyKey) {
        finalHeaders['Idempotency-Key'] = idempotencyKey;
    }

    let lastError;
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        try {
            const response = await fetch(url, {
                method,
                headers: finalHeaders,
                body: payload,
                signal,  // E083: support abort signal
            });

            if (response.status === 204) return null;

            const contentType = response.headers.get('content-type') || '';
            const isJson = contentType.includes('application/json');
            const data = isJson ? await response.json() : await response.text();

            if (!response.ok) {
                throw new ApiError(data);
            }
            return data;
        } catch (err) {
            lastError = err;
            // E088: AbortError — user cancelled, no retry
            if (err.name === 'AbortError') {
                throw err;
            }
            if (err instanceof ApiError && err.status < 500) {
                throw err;
            }
            if (attempt < MAX_RETRIES - 1) {
                const backoff = INITIAL_BACKOFF_MS * 2 ** attempt;
                await new Promise(r => setTimeout(r, backoff));
            }
        }
    }
    throw lastError;
}

export const api = {
    // === Protocols ===
    listProtocols: (params = {}) => {
        const qs = new URLSearchParams(params).toString();
        return request('GET', `/protocols${qs ? `?${qs}` : ''}`);
    },
    getProtocol: (id) => request('GET', `/protocols/${id}`),
    createProtocol: (file, data) => {
        const fd = new FormData();
        fd.append('file', file);
        Object.entries(data).forEach(([k, v]) => fd.append(k, v));
        return request('POST', '/protocols', { formData: fd });
    },
    createProtocolFromUrl: (url, data) =>
        request('POST', '/protocols/from-url', { body: { url, ...data } }),
    updateProtocol: (id, data) => request('PATCH', `/protocols/${id}`, { body: data }),
    deleteProtocol: (id) => request('DELETE', `/protocols/${id}`),
    deleteProtocolPermanent: (id) => request('DELETE', `/protocols/${id}/permanent`),

    // === Folders ===
    listFolders: (parentId) =>
        request('GET', `/folders${parentId ? '?parent_id=' + parentId : ''}`),
    createFolder: (data) => request('POST', '/folders', { body: data }),
    getFolder: (id) => request('GET', '/folders/' + id),
    updateFolder: (id, data) => request('PATCH', '/folders/' + id, { body: data }),
    deleteFolder: (id) => request('DELETE', '/folders/' + id),
    moveProtocolToFolder: (protocolId, folderId) =>
        request('PUT', '/protocols/' + protocolId + '/folder', { body: { folder_id: folderId } }),
    addProtocolToFolder: (folderId, protocolId) =>
        request('POST', '/folders/' + folderId + '/protocols/' + protocolId),
    removeProtocolFromFolder: (folderId, protocolId) =>
        request('DELETE', '/folders/' + folderId + '/protocols/' + protocolId),
    batchMoveProtocols: (protocolIds, folderId) =>
        request('POST', '/protocols/batch-move', { body: { protocol_ids: protocolIds, folder_id: folderId } }),

    // === Screenshots ===
    listScreenshots: (protocolId) =>
        request('GET', `/protocols/${protocolId}/screenshots`),
    createScreenshot: (data) => request('POST', '/screenshots', { body: data }),
    uploadScreenshot: (file, protocolId, options = {}) => {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('protocol_id', protocolId);
        if (options.timestamp_sec !== undefined) {
            fd.append('timestamp_sec', options.timestamp_sec);
        }
        if (options.caption) {
            fd.append('caption', options.caption);
        }
        return request('POST', '/screenshots/upload', { formData: fd });
    },
    getScreenshot: (id) => request('GET', '/screenshots/' + id),
    deleteScreenshot: (id) => request('DELETE', '/screenshots/' + id),

    // === Decisions ===
    listDecisions: (protocolId) =>
        request('GET', `/decisions?protocol_id=${protocolId}`),
    createDecision: (data) => request('POST', '/decisions', { body: data }),
    getDecision: (id) => request('GET', '/decisions/' + id),
    deleteDecision: (id) => request('DELETE', '/decisions/' + id),

    // === Calendar ===
    getCalendar: (year, month) => request('GET', `/calendar?year=${year}&month=${month}`),

    // === Audio ===
    getAudioFile: (id) => request('GET', `/audio-files/${id}`),
    openAudioFolder: (id) => request('POST', `/audio-files/${id}/open-folder`),

    // === Transcription ===
    startTranscription: (data) => request('POST', '/transcribe/run', { body: data }),
    getTranscriptionStatus: (taskId) => request('GET', `/transcribe/status/${taskId}`),
    cancelTranscription: (taskId) => request('POST', `/transcribe/cancel/${taskId}`),
    getTranscriptionProgress: (taskId) => request('GET', `/transcribe/progress/${taskId}`),
    getTranscriptionProgressByProtocol: (protocolId) =>
        request('GET', `/transcribe/progress-by-protocol/${protocolId}`),

    // E216: дубликат startDiarization убран — ниже единственное объявление в секции Summary/AI
    getDiarizationResult: (protocolId) =>
        request('GET', `/diarize/result/${protocolId}`),

    // === Utterances ===
    listUtterances: (protocolId, params = {}) => {
        const allParams = { protocol_id: protocolId, ...params };
        const qs = new URLSearchParams(allParams).toString();
        return request('GET', `/utterances?${qs}`);
    },
    // E189: обновлён — теперь принимает (id, data) целиком.
    // Передаёт data как есть (text + version_snapshot).
    updateUtteranceText: (id, data) =>
        request('PATCH', `/utterances/${id}/text`, { body: data }),
    updateUtteranceSpeaker: (id, speakerId) =>
        request('PATCH', `/utterances/${id}/speaker`, { body: { speaker_id: speakerId } }),

    // === Speakers ===
    listSpeakers: (protocolId) => request('GET', `/speakers?protocol_id=${protocolId}`),
    updateSpeaker: (id, data) => request('PATCH', `/speakers/${id}`, { body: data }),
    // E217: добавлено — edit-speakers.js раньше вызывал fetch напрямую
    deleteSpeaker: (id) => request('DELETE', `/speakers/${id}`),
    mergeSpeakers: (sourceId, targetId, newDisplayName) =>
        request('POST', '/speakers/merge', {
            body: { source_id: sourceId, target_id: targetId, new_display_name: newDisplayName },
        }),

    // === Action Items ===
    listActionItems: (protocolId, params = {}) =>
        request('GET', `/protocols/${protocolId}/action-items${Object.keys(params).length ? '?' + new URLSearchParams(params) : ''}`),
    createActionItem: (data) => request('POST', '/action-items', { body: data }),
    updateActionItem: (id, data) => request('PATCH', `/action-items/${id}`, { body: data }),
    deleteActionItem: (id) => request('DELETE', `/action-items/${id}`),
    extractActions: (data) => request('POST', '/ai/extract-actions', { body: data }),

    // === Search ===
    search: (q, protocolId) =>
        request('GET', `/search?q=${encodeURIComponent(q)}${protocolId ? `&protocol_id=${protocolId}` : ''}`),

    // === Tags ===
    listTags: (protocolId) => request('GET', `/protocols/${protocolId}/tags`),
    createTag: (data) => request('POST', '/tags', { body: data }),
    deleteTag: (id) => request('DELETE', `/tags/${id}`),

    // === Summary / AI ===
    getSummary: (protocolId) => request('GET', `/protocols/${protocolId}/summary`),
    summarize: (data) => request('POST', '/ai/summarize', { body: data }),
    cleanupText: (data) => request('POST', '/ai/cleanup-text', { body: data }),
    restorePunctuation: (data) => request('POST', '/ai/restore-punctuation', { body: data }),
    // E141: Диаризация
    startDiarization: (data) => request('POST', '/diarize/run', { body: data }),
    getDiarizationResult: (protocolId) => request('GET', `/diarize/result/${protocolId}`),
    testBotConnection: (bot_token) => request('POST', '/bot/test-connection', { body: { bot_token } }),

    // === Export ===
    startExport: (data) => request('POST', '/export/docx', { body: data }),
    getExportStatus: (taskId) => request('GET', `/export/status/${taskId}`),
    downloadExport: (taskId) => {
        const url = `${API_BASE}/export/download/${taskId}`;
        return fetch(url).then(r => r.blob());
    },

    // === Dictionary ===
    listDictionary: () => request('GET', '/dictionary'),
    addDictionaryTerm: (data) => request('POST', '/dictionary', { body: data }),
    deleteDictionaryTerm: (id) => request('DELETE', `/dictionary/${id}`),

    // === User Settings ===
    getUserSetting: () => request('GET', '/user-setting'),
    updateUserSetting: (data) => request('PATCH', '/user-setting', { body: data }),

    // === Bot (admin) ===
    getBotSettings: () => request('GET', '/bot/settings'),
    updateBotSettings: (data) => request('PATCH', '/bot/settings', { body: data }),
    listBotUsers: () => request('GET', '/bot/users'),
    addBotUser: (data) => request('POST', '/bot/users', { body: data }),
    deleteBotUser: (id) => request('DELETE', `/bot/users/${id}`),

    // === Live Mode ===
    startLive: (data) => request('POST', '/live/start', { body: data }),
    stopLive: (protocolId) => request('POST', `/live/${protocolId}/stop`),

    // === Admin (US-072) ===
    clearAllData: () => request('DELETE', '/admin/clear-data'),
    getAdminStats: () => request('GET', '/admin/stats'),

    // ============================================================================
    // Whisper Models Management (US-058)
    // ============================================================================
    getWhisperModels: () => request('GET', '/whisper/models'),
    getWhisperModelInfo: (name) => request('GET', `/whisper/models/${name}`),
    downloadWhisperModel: (name) => request('POST', `/whisper/download/${name}`),
    getWhisperModelProgress: (name) => request('GET', `/whisper/progress/${name}`),
    setActiveWhisperModel: (name) => request('POST', `/whisper/active/${name}`),
    getWhisperModelStatus: (name) => request('GET', `/whisper/status/${name}`),
    deleteWhisperModel: (name) => request('DELETE', `/whisper/models/${name}`),
    // E147: AI auto-extract decisions
    extractDecisions: (data) => request('POST', '/ai/extract-decisions', { body: data }),
    // E149: AI translation
    translateUtterances: (data) => request('POST', '/ai/translate', { body: data }),
    // E150: Pause / Resume transcription
    pauseTranscription: (taskId) => request('POST', `/transcribe/pause/${taskId}`),
    resumeTranscription: (taskId) => request('POST', `/transcribe/resume/${taskId}`),
    // E154: Grammar/spelling check
    checkGrammar: (data) => request('POST', '/ai/check-grammar', { body: data }),
    // E162: Upgrade low-confidence segments
    upgradeWeakSegments: (protocolId, data = {}) => request('POST', `/transcribe/upgrade/${protocolId}`, { body: data }),
    // E172: Toggle "important" bookmark
    toggleUtteranceImportant: (id, important) => request('PATCH', `/utterances/${id}/important`, { body: { important } }),


};