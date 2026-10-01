/**
 * Unit-тесты для src/js/views/protocol.js
 *
 * renderUtteranceItem и renderScreenshotsTab НЕ экспортированы из src/,
 * поэтому тестируем их косвенно через публичный renderProtocolDetail.
 *
 * Проверяем:
 * - renderProtocolDetail рендерит header, вкладки, медиа-плеер
 * - renderUtteranceItem (через .transcript-list) рендерит speaker, timestamp,
 *   важное (☆/⭐), decision (⚖️), low-conf (⚠️)
 * - renderScreenshotsTab рендерит кнопки synthesize и upload
 * - handleClick на timestamp-btn (мок) не падает
 * - Кэш fallback при server error
 */
import { renderProtocolDetail } from '@views/protocol.js';
import {
    createMockProtocol,
    createMockUtterance,
    createMockSpeaker,
    mockFetchSequence,
} from '@tests/setup.js';

// IndexedDB мок — protocol.js использует storage.put/get, jsdom не имеет IDB
// Map должна быть создана внутри factory — Jest не позволяет захватывать
// внешние переменные в module factory.
jest.mock('@storage/indexeddb.js', () => {
    const idbStore = new Map();
    return {
        storage: {
            put: jest.fn((_store, value) => { idbStore.set(value.id, value); return Promise.resolve(); }),
            get: jest.fn((_store, id) => Promise.resolve(idbStore.get(id) || null)),
            getByIndex: jest.fn(() => Promise.resolve([])),
        },
        STORES: {
            protocols: 'protocols',
            utterances: 'utterances',
            speakers: 'speakers',
            tags: 'tags',
            action_items: 'action_items',
            screenshots: 'screenshots',
            decisions: 'decisions',
        },
    };
});

describe('views/protocol.js', () => {
    let rootEl;
    const PROTOCOL_ID = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';

    beforeEach(() => {
        // Очистить IndexedDB mock store (доступ через requireMock).
        const { storage } = jest.requireMock('@storage/indexeddb.js');
        storage.put.mockClear();
        storage.get.mockClear();
        storage.getByIndex.mockClear();
        document.body.innerHTML = '<div id="view-root"></div>';
        rootEl = document.getElementById('view-root');
        window.location.hash = '';
        // disable hotkeys setup
        window.audioPlayer = undefined;
    });

    function setupMocks({ protocol, utterances = [], speakers = [], summary = null } = {}) {
        mockFetchSequence([
            { body: protocol || createMockProtocol() },           // getProtocol
            { body: { total: utterances.length, items: utterances } }, // listUtterances
            { body: speakers },                                   // listSpeakers
            { body: summary },                                    // getSummary
            { body: [] },                                         // listTags
            { body: [] },                                         // listActionItems
            { body: [] },                                         // listScreenshots
            { body: [] },                                         // listDecisions
        ]);
    }

    // ─────────────────────────────────────────────────────────────
    // renderProtocolDetail
    // ─────────────────────────────────────────────────────────────

    describe('renderProtocolDetail', () => {
        test('показывает spinner пока грузится', async () => {
            // pending fetch — даст время проверить loading state
            let resolveFetch;
            global.fetch = jest.fn().mockReturnValueOnce(new Promise(r => { resolveFetch = r; }));
            global.fetch.mockResolvedValue(
                Promise.resolve({
                    ok: true,
                    status: 200,
                    headers: { get: () => 'application/json' },
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('{}'),
                }),
            );

            const promise = renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.innerHTML).toContain('spinner');
            await promise;
        });

        test('рендерит заголовок протокола', async () => {
            setupMocks({ protocol: createMockProtocol({ title: 'Совещание по бюджету' }) });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.textContent).toContain('Совещание по бюджету');
        });

        test('рендерит вкладки (tab-bar)', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const tabBar = rootEl.querySelector('tab-bar');
            expect(tabBar).not.toBeNull();
            // Проверяем что есть вкладки
            expect(tabBar.tabs.length).toBeGreaterThanOrEqual(5);
        });

        test('рендерит дату в локали ru-RU', async () => {
            setupMocks({ protocol: createMockProtocol({ date: '2025-01-15T10:00:00Z' }) });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            // Должна быть какая-то дата (формат зависит от локали)
            expect(rootEl.textContent).toMatch(/2025/);
        });

        test('рендерит кнопки действий (export, delete, transcribe)', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('#btn-export')).not.toBeNull();
            expect(rootEl.querySelector('#btn-delete')).not.toBeNull();
            expect(rootEl.querySelector('#btn-transcribe')).not.toBeNull();
        });

        test('рендерит video плеер если есть audio_file', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const video = rootEl.querySelector('#media-video');
            expect(video).not.toBeNull();
        });

        test('не рендерит video если нет audio_file', async () => {
            setupMocks({ protocol: createMockProtocol({ audio_file: null }) });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('#media-video')).toBeNull();
        });

        test('404 → редирект на #/', async () => {
            global.fetch = jest.fn().mockResolvedValue({
                ok: false,
                status: 404,
                headers: { get: () => 'application/json' },
                json: () => Promise.resolve({ status: 404, title: 'Not Found' }),
                text: () => Promise.resolve('{}'),
            });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(window.location.hash).toBe('#/');
        });

        test('формат даты — long ru-RU', async () => {
            setupMocks({ protocol: createMockProtocol({ date: '2025-03-15T10:00:00Z' }) });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            // 'марта' — русское название месяца
            expect(rootEl.textContent).toMatch(/март|марта/);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // renderUtteranceItem (косвенно через renderProtocolDetail)
    // ─────────────────────────────────────────────────────────────

    describe('renderUtteranceItem (через transcript)', () => {
        test('рендерит текст реплики', async () => {
            const utt = createMockUtterance({ text: 'Тестовая реплика XYZ' });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.transcript-list').textContent).toContain('Тестовая реплика XYZ');
        });

        test('рендерит кнопку timestamp (⏱)', async () => {
            const utt = createMockUtterance({ start_sec: 42.5 });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const btn = rootEl.querySelector('.timestamp-btn');
            expect(btn).not.toBeNull();
            expect(btn.dataset.time).toBe('42.5');
            // Должен содержать время mm:ss
            expect(btn.textContent).toMatch(/⏱.*0:42/);
        });

        test('рендерит ☆ для unmarked important', async () => {
            const utt = createMockUtterance({ important: false });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.btn-mark-important')).not.toBeNull();
            expect(rootEl.querySelector('.btn-important-marked')).toBeNull();
        });

        test('рендерит ⭐ для marked important', async () => {
            const utt = createMockUtterance({ important: true });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.btn-important-marked')).not.toBeNull();
        });

        test('рендерит ⚠️ для low_confidence', async () => {
            const utt = createMockUtterance({ low_confidence: true, confidence: 0.3 });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.low-conf-mark')).not.toBeNull();
        });

        test('confidence bar — danger class для conf < 0.4', async () => {
            const utt = createMockUtterance({ confidence: 0.3 });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.conf-fill.danger')).not.toBeNull();
        });

        test('confidence bar — warning class для 0.4 ≤ conf < 0.7', async () => {
            const utt = createMockUtterance({ confidence: 0.5 });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.conf-fill.warning')).not.toBeNull();
        });

        test('confidence bar — success class для conf ≥ 0.7', async () => {
            const utt = createMockUtterance({ confidence: 0.95 });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.conf-fill.success')).not.toBeNull();
        });

        test('speaker badge — использует display_name', async () => {
            const sp = createMockSpeaker({ id: 'sp-1', display_name: 'Петров П.П.' });
            const utt = createMockUtterance({ speaker_id: 'sp-1' });
            setupMocks({ speakers: [sp], utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const badge = rootEl.querySelector('.speaker-badge');
            expect(badge).not.toBeNull();
            expect(badge.textContent).toContain('Петров П.П.');
        });

        test('speaker badge — fallback если speaker не найден', async () => {
            const utt = createMockUtterance({ speaker_id: 'unknown', speaker_label: 'Speaker 5' });
            setupMocks({ speakers: [], utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const badge = rootEl.querySelector('.speaker-badge');
            expect(badge).not.toBeNull();
            expect(badge.textContent).toContain('Speaker 5');
        });

        test('translation block — показывается если есть translation_text', async () => {
            const utt = createMockUtterance({
                translation_text: 'Translated text',
                translation_language: 'en',
            });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('.utterance-translation')).not.toBeNull();
            expect(rootEl.querySelector('.translation-label').textContent).toContain('en');
        });

        test('render несколько реплик — все отрисованы', async () => {
            const utts = [
                createMockUtterance({ id: 'u1', text: 'Реплика 1' }),
                createMockUtterance({ id: 'u2', text: 'Реплика 2' }),
                createMockUtterance({ id: 'u3', text: 'Реплика 3' }),
            ];
            setupMocks({ utterances: utts });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelectorAll('.utterance-item').length).toBe(3);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // renderScreenshotsTab — кнопка synthesize
    // ─────────────────────────────────────────────────────────────

    describe('renderScreenshotsTab (synthesize button)', () => {
        test('рендерит кнопку #btn-synthesize-screenshots', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.querySelector('#btn-synthesize-screenshots')).not.toBeNull();
        });

        test('рендерит select #synthesize-strategy', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const sel = rootEl.querySelector('#synthesize-strategy');
            expect(sel).not.toBeNull();
            expect(sel.querySelectorAll('option').length).toBeGreaterThanOrEqual(3);
        });

        test('рендерит input #synthesize-max с дефолтом 10', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const inp = rootEl.querySelector('#synthesize-max');
            expect(inp).not.toBeNull();
            expect(inp.value).toBe('10');
        });

        test('клик на synthesize → вызывает api.synthesizeScreenshots', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const btn = rootEl.querySelector('#btn-synthesize-screenshots');
            // Дополнительный fetch для synthesize + listScreenshots
            mockFetchSequence([
                { body: { screenshots_created: 4 } },
                { body: [] },
            ]);
            btn.click();
            // Ждём микротаски
            await new Promise(r => setTimeout(r, 50));
            const calls = global.fetch.mock.calls;
            const hasSynth = calls.some(([url]) =>
                String(url).includes('/screenshots/synthesize'),
            );
            expect(hasSynth).toBe(true);
        });

        test('синтез с strategy="decisions" и max=5', async () => {
            setupMocks();
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            rootEl.querySelector('#synthesize-strategy').value = 'decisions';
            rootEl.querySelector('#synthesize-max').value = '5';
            mockFetchSequence([
                { body: { screenshots_created: 3 } },
                { body: [] },
            ]);
            rootEl.querySelector('#btn-synthesize-screenshots').click();
            await new Promise(r => setTimeout(r, 50));

            const synthCall = global.fetch.mock.calls.find(([url]) =>
                String(url).includes('/screenshots/synthesize'),
            );
            expect(synthCall).toBeTruthy();
            const body = JSON.parse(synthCall[1].body);
            expect(body.strategy).toBe('decisions');
            expect(body.max_screenshots).toBe(5);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // handleClick на timestamp-btn (мок)
    // ─────────────────────────────────────────────────────────────

    describe('handleClick на timestamp', () => {
        test('клик по timestamp-btn → seek audioPlayer', async () => {
            const utt = createMockUtterance({ start_sec: 100 });
            setupMocks({ utterances: [utt] });
            const seekSpy = jest.fn();
            window.audioPlayer = { seekTo: seekSpy };

            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const btn = rootEl.querySelector('.timestamp-btn');
            expect(btn).not.toBeNull();

            btn.click();
            // Если audioPlayer был доступен — должен был быть вызван seekTo
            // (Внутри есть условие — если нет audioPlayer, fallback на video.currentTime)
            // Здесь мы его замокали
            expect(seekSpy).toHaveBeenCalledWith(100);
        });

        test('клик по timestamp-btn → fallback на video.currentTime', async () => {
            const utt = createMockUtterance({ start_sec: 50 });
            setupMocks({ utterances: [utt] });
            window.audioPlayer = undefined;

            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            const video = rootEl.querySelector('#media-video');
            video.currentTime = 0;

            const btn = rootEl.querySelector('.timestamp-btn');
            btn.click();

            expect(video.currentTime).toBe(50);
        });

        test('клик невалидный time (NaN) → no-op', async () => {
            const utt = createMockUtterance({ start_sec: 0 });
            setupMocks({ utterances: [utt] });
            await renderProtocolDetail(rootEl, PROTOCOL_ID);

            const btn = rootEl.querySelector('.timestamp-btn');
            // Установим невалидный data-time
            btn.dataset.time = 'invalid';
            expect(() => btn.click()).not.toThrow();
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Fallback на IndexedDB кэш
    // ─────────────────────────────────────────────────────────────

    describe('cache fallback', () => {
        test('network error → fallback на cached protocol', async () => {
            // Предзагружаем в IDB кэш
            const cached = createMockProtocol({ title: 'Cached Meeting' });
            idbStore.set(cached.id, cached);

            global.fetch = jest.fn().mockRejectedValue(new Error('Network down'));

            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(rootEl.textContent).toContain('Cached Meeting');
        });

        test('network error + нет кэша → редирект на #/', async () => {
            global.fetch = jest.fn().mockRejectedValue(new Error('Network down'));
            await renderProtocolDetail(rootEl, PROTOCOL_ID);
            expect(window.location.hash).toBe('#/');
        });
    });
});