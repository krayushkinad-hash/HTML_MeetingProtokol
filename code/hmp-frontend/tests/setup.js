/**
 * Jest setup — общая конфигурация перед каждым тестом.
 *
 * - Мокает fetch через global.fetch (api/client.js использует fetch)
 * - Мокает localStorage (на случай если не инициализирован в jsdom)
 * - Мокает window.matchMedia (для media queries в CSS)
 * - Мокает navigator.clipboard (используется в views/protocol.js)
 * - Экспортирует helpers: createMockResponse, createMockProtocol, createMockUtterance
 *
 * Подключается через jest.config.js -> setupFiles.
 */

// === Глобальные моки браузерного API ===

// localStorage — в jsdom есть, но обнуляем перед каждым тестом
beforeEach(() => {
    if (typeof localStorage !== 'undefined') {
        localStorage.clear();
    }
});

// matchMedia — для CSS @media (prefers-color-scheme и т.п.)
if (typeof window !== 'undefined' && !window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: jest.fn().mockImplementation(query => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: jest.fn(),
            removeListener: jest.fn(),
            addEventListener: jest.fn(),
            removeEventListener: jest.fn(),
            dispatchEvent: jest.fn(),
        })),
    });
}

// navigator.clipboard — writeText для кнопок "copy path"
if (typeof navigator !== 'undefined' && !navigator.clipboard) {
    Object.defineProperty(navigator, 'clipboard', {
        writable: true,
        value: {
            writeText: jest.fn().mockResolvedValue(undefined),
            readText: jest.fn().mockResolvedValue(''),
        },
    });
}

// AbortSignal.timeout — для settings.js (проверка remote whisper)
if (typeof AbortSignal !== 'undefined' && !AbortSignal.timeout) {
    AbortSignal.timeout = (ms) => {
        const ctrl = new AbortController();
        setTimeout(() => ctrl.abort(), ms);
        return ctrl.signal;
    };
}

// === jsdom FormData fix ===
//
// В jsdom + Node 22 FormData.get() падает с
// "Cannot read private member #channel from an object whose class did not declare it"
// потому что jsdom создаёт FormData в одном realm, а .get() вызывается в другом.
// Решение: подменить FormData на полностью рабочую реализацию из Node built-in
// (глобальные FormData/Blob/File доступны в Node 18+).

(function patchFormData() {
    // Берём «чистую» реализацию из нового realm — Node built-in FormData.
    const BuiltInFormData = globalThis.FormData;
    const BuiltInBlob = globalThis.Blob;
    const BuiltInFile = globalThis.File;

    function isBroken(Clazz) {
        try {
            const inst = new Clazz();
            if (Clazz === BuiltInFormData) {
                inst.append('x', 'y');
                return inst.get('x') !== 'y';
            }
            return false;
        } catch (e) {
            return true;
        }
    }

    // jsdom может переопределить эти глобалы — нужно вернуть «правильные».
    if (typeof BuiltInFormData === 'function' && typeof BuiltInBlob === 'function') {
        globalThis.FormData = BuiltInFormData;
        globalThis.Blob = BuiltInBlob;
        globalThis.File = BuiltInFile;
        if (typeof window !== 'undefined') {
            window.FormData = BuiltInFormData;
            window.Blob = BuiltInBlob;
            window.File = BuiltInFile;
        }
    }
})();

// === Helpers для тестов ===

/**
 * Создаёт mock Response объект для fetch.
 *
 * @param {*} body — тело ответа (object -> JSON.stringify, string -> as-is)
 * @param {object} options
 * @param {number} options.status — HTTP статус (default 200)
 * @param {string} options.contentType — Content-Type (default 'application/json')
 * @returns {Promise<Response>}
 */
function createMockResponse(body, options = {}) {
    const { status = 200, contentType = 'application/json' } = options;
    const isJson = contentType.includes('json');
    const text = isJson && typeof body !== 'string' ? JSON.stringify(body) : String(body ?? '');

    return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        statusText: status === 200 ? 'OK' : 'Error',
        headers: {
            get: (name) => {
                if (name && name.toLowerCase() === 'content-type') return contentType;
                return null;
            },
        },
        json: () => Promise.resolve(isJson ? (typeof body === 'string' ? JSON.parse(body || 'null') : body) : null),
        text: () => Promise.resolve(text),
        blob: () => Promise.resolve(new Blob([text])),
        arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    });
}

/**
 * Создаёт mock protocol объект для тестов.
 *
 * @param {object} overrides — поля, которые нужно переопределить
 * @returns {object}
 */
function createMockProtocol(overrides = {}) {
    return {
        id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        title: 'Test Meeting 2025-01-15',
        date: '2025-01-15T10:00:00Z',
        status: 'transcribed',
        location: 'Москва, оф. 404',
        chair: 'Иванов И.И.',
        agenda: '1. Бюджет\n2. Roadmap',
        language: 'ru',
        duration_sec: 3600,
        wer_quality: null,
        audio_file: {
            id: 'audio-1',
            filename: 'meeting.mp3',
            size_bytes: 10485760, // 10 MB
            mime_type: 'audio/mpeg',
            source: 'upload',
            file_path: '/tmp/meeting.mp3',
        },
        ...overrides,
    };
}

/**
 * Создаёт mock utterance (реплика) объект для тестов.
 *
 * @param {object} overrides — поля для переопределения
 * @returns {object}
 */
function createMockUtterance(overrides = {}) {
    return {
        id: 'u1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5e',
        protocol_id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        speaker_id: 'sp-1',
        speaker_label: 'Иванов И.И.',
        text: 'Здравствуйте, коллеги. Сегодня обсудим бюджет.',
        start_time: 0.0,
        end_time: 5.5,
        confidence: 0.95,
        important: false,
        version: 1,
        ...overrides,
    };
}

/**
 * Создаёт mock speaker объект.
 */
function createMockSpeaker(overrides = {}) {
    return {
        id: 'sp-1',
        protocol_id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        display_name: 'Иванов И.И.',
        gender: 'male',
        total_speaking_time: 1800.0,
        utterance_count: 25,
        ...overrides,
    };
}

/**
 * Хелпер: замокать fetch с заранее заданной последовательностью ответов.
 * Каждый вызов fetch() будет возвращать следующий mock из массива.
 *
 * @param {Array<{body: any, status?: number, contentType?: string}>} responses
 * @returns {jest.Mock}
 */
function mockFetchSequence(responses) {
    let i = 0;
    const fn = jest.fn().mockImplementation((url, init) => {
        if (i >= responses.length) {
            return createMockResponse({ error: 'No more mock responses' }, { status: 500 });
        }
        const r = responses[i++];
        return createMockResponse(r.body, { status: r.status, contentType: r.contentType });
    });
    global.fetch = fn;
    return fn;
}

/**
 * Хелпер: замокать fetch на один ответ для конкретного URL.
 *
 * @param {string|RegExp} urlPattern
 * @param {*} body
 * @param {object} options
 */
function mockFetchUrl(urlPattern, body, options = {}) {
    const fn = jest.fn().mockImplementation((url) => {
        const matches = typeof urlPattern === 'string'
            ? url === urlPattern
            : urlPattern.test(url);
        if (matches) {
            return createMockResponse(body, options);
        }
        return createMockResponse({ error: 'URL mismatch' }, { status: 404 });
    });
    global.fetch = fn;
    return fn;
}

// === Экспорт ===

// Для CommonJS-контекста (jest использует CJS по умолчанию в тестах)
global.__TEST_HELPERS__ = {
    createMockResponse,
    createMockProtocol,
    createMockUtterance,
    createMockSpeaker,
    mockFetchSequence,
    mockFetchUrl,
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        createMockResponse,
        createMockProtocol,
        createMockUtterance,
        createMockSpeaker,
        mockFetchSequence,
        mockFetchUrl,
    };
}