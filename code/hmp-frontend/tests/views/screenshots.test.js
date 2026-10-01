/**
 * Unit-тесты для screenshots UI (встроен в src/js/views/protocol.js
 * как renderScreenshotsTab + обработчик кнопки #btn-synthesize-screenshots).
 *
 * US-019: автоматический сбор скриншотов из видео
 *
 * Тестируем:
 * - Кнопка "Собрать скриншоты" существует
 * - Клик → api.synthesizeScreenshots с правильными параметрами
 * - Reload списка после успешного синтеза
 * - Error handling — toast.error при сбое
 * - Button disabled во время запроса
 * - strategy select и max input работают
 */
import { renderProtocolDetail } from '@views/protocol.js';
import {
    createMockProtocol,
    createMockUtterance,
    createMockResponse,
} from '@tests/setup.js';

jest.mock('@utils/toast.js', () => ({
    toast: {
        success: jest.fn(),
        error: jest.fn(),
        warning: jest.fn(),
        info: jest.fn(),
    },
}));

const { toast } = require('@utils/toast.js');

// IndexedDB мок — factory должна быть автономной (Jest не разрешает
// захват внешних переменных внутри jest.mock factory).
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

describe('screenshots UI (renderScreenshotsTab)', () => {
    let rootEl;
    const PROTOCOL_ID = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';

    beforeEach(() => {
        const { storage } = jest.requireMock('@storage/indexeddb.js');
        storage.put.mockClear();
        storage.get.mockClear();
        storage.getByIndex.mockClear();
        document.body.innerHTML = '<div id="view-root"></div>';
        rootEl = document.getElementById('view-root');
        window.location.hash = '';
        jest.clearAllMocks();
    });

    function setupInitialFetch() {
        global.fetch = jest.fn().mockImplementation((url) => {
            // Initial 8 calls for renderProtocolDetail
            return createMockResponse({}, { status: 200 });
        });
    }

    async function render() {
        global.fetch = jest.fn().mockResolvedValue(
            createMockResponse({ id: PROTOCOL_ID, title: 'Test' }, { status: 200 }),
        );
        await renderProtocolDetail(rootEl, PROTOCOL_ID);
    }

    // ─────────────────────────────────────────────────────────────
    // Toolbar
    // ─────────────────────────────────────────────────────────────

    describe('UI рендеринг', () => {
        test('рендерит кнопку #btn-synthesize-screenshots', async () => {
            await render();
            const btn = rootEl.querySelector('#btn-synthesize-screenshots');
            expect(btn).not.toBeNull();
            expect(btn.textContent).toContain('Собрать');
        });

        test('рендерит select со всеми strategies', async () => {
            await render();
            const sel = rootEl.querySelector('#synthesize-strategy');
            expect(sel).not.toBeNull();
            const options = Array.from(sel.options).map(o => o.value);
            expect(options).toEqual(expect.arrayContaining(['uniform', 'important', 'decisions', 'change_detection']));
        });

        test('рендерит input #synthesize-max с дефолтом 10', async () => {
            await render();
            expect(rootEl.querySelector('#synthesize-max').value).toBe('10');
        });

        test('рендерит file input для upload скриншотов', async () => {
            await render();
            expect(rootEl.querySelector('#screenshot-input')).not.toBeNull();
        });

        test('рендерит кнопку upload', async () => {
            await render();
            const btns = rootEl.querySelectorAll('button');
            const uploadBtn = Array.from(btns).find(b => b.textContent.includes('Загрузить скриншот'));
            expect(uploadBtn).toBeTruthy();
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Synthesize button click
    // ─────────────────────────────────────────────────────────────

    describe('synthesize button click handler', () => {
        test('клик → api.synthesizeScreenshots', async () => {
            await render();
            const btn = rootEl.querySelector('#btn-synthesize-screenshots');

            global.fetch = jest.fn()
                .mockResolvedValueOnce(createMockResponse({ screenshots_created: 5 }))
                .mockResolvedValueOnce(createMockResponse([]));

            btn.click();
            await new Promise(r => setTimeout(r, 50));

            const synthCall = global.fetch.mock.calls.find(([url]) =>
                String(url).includes('/screenshots/synthesize'),
            );
            expect(synthCall).toBeTruthy();
            expect(synthCall[1].method).toBe('POST');
            const body = JSON.parse(synthCall[1].body);
            expect(body.max_screenshots).toBe(10);
            expect(body.strategy).toBe('uniform');
        });

        test('клик → success toast', async () => {
            await render();
            global.fetch = jest.fn()
                .mockResolvedValueOnce(createMockResponse({ screenshots_created: 5 }))
                .mockResolvedValueOnce(createMockResponse([]));

            rootEl.querySelector('#btn-synthesize-screenshots').click();
            await new Promise(r => setTimeout(r, 50));

            expect(toast.success).toHaveBeenCalledWith(
                expect.stringContaining('Создано скриншотов: 5'),
            );
        });

        test('клик → после успеха reload списка', async () => {
            await render();
            global.fetch = jest.fn()
                .mockResolvedValueOnce(createMockResponse({ screenshots_created: 3 }))
                .mockResolvedValueOnce(createMockResponse([{ id: 's1' }]));

            rootEl.querySelector('#btn-synthesize-screenshots').click();
            await new Promise(r => setTimeout(r, 50));

            const listCall = global.fetch.mock.calls.find(([url]) =>
                String(url).includes('/screenshots') &&
                !String(url).includes('/synthesize') &&
                !String(url).includes('/upload'),
            );
            expect(listCall).toBeTruthy();
        });

        test('click → error toast если synthesize fails', async () => {
            await render();
            global.fetch = jest.fn().mockResolvedValueOnce(
                createMockResponse({ status: 500, detail: 'Failed' }, { status: 500 }),
            );

            // Чтобы не зависнуть на retries (synthesize использует request() с retry)
            // подождём дольше
            rootEl.querySelector('#btn-synthesize-screenshots').click();
            await new Promise(r => setTimeout(r, 100));

            expect(toast.error).toHaveBeenCalled();
        }, 10000);

        test('button disabled во время запроса', async () => {
            await render();
            let resolveFetch;
            global.fetch = jest.fn().mockReturnValueOnce(
                new Promise(r => { resolveFetch = r; }),
            );

            const btn = rootEl.querySelector('#btn-synthesize-screenshots');
            btn.click();
            await new Promise(r => setTimeout(r, 10));

            expect(btn.disabled).toBe(true);
            // Текст меняется на "Извлечение кадров..."
            expect(btn.textContent).toMatch(/Извлечение/);

            // Резолвим
            resolveFetch(createMockResponse({ screenshots_created: 1 }));
            await new Promise(r => setTimeout(r, 10));
            expect(btn.disabled).toBe(false);
        });

        test('с кастомными strategy=decisions и max=5', async () => {
            await render();
            rootEl.querySelector('#synthesize-strategy').value = 'decisions';
            rootEl.querySelector('#synthesize-max').value = '5';

            global.fetch = jest.fn()
                .mockResolvedValueOnce(createMockResponse({ screenshots_created: 3 }))
                .mockResolvedValueOnce(createMockResponse([]));

            rootEl.querySelector('#btn-synthesize-screenshots').click();
            await new Promise(r => setTimeout(r, 50));

            const synthCall = global.fetch.mock.calls.find(([url]) =>
                String(url).includes('/screenshots/synthesize'),
            );
            const body = JSON.parse(synthCall[1].body);
            expect(body.strategy).toBe('decisions');
            expect(body.max_screenshots).toBe(5);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Tab badge — показывает количество
    // ─────────────────────────────────────────────────────────────

    describe('badge скриншотов', () => {
        test('badge = 0 если нет скриншотов', async () => {
            await render();
            const tabBar = rootEl.querySelector('tab-bar');
            const screenshotsTab = tabBar.tabs.find(t => t.id === 'screenshots');
            expect(screenshotsTab.badge).toBe(0);
        });

        test('badge обновляется после synthesize', async () => {
            await render();
            global.fetch = jest.fn()
                .mockResolvedValueOnce(createMockResponse({ screenshots_created: 7 }))
                .mockResolvedValueOnce(createMockResponse([
                    { id: 's1' }, { id: 's2' }, { id: 's3' },
                    { id: 's4' }, { id: 's5' }, { id: 's6' }, { id: 's7' },
                ]));

            rootEl.querySelector('#btn-synthesize-screenshots').click();
            await new Promise(r => setTimeout(r, 50));

            const tabBar = rootEl.querySelector('tab-bar');
            const screenshotsTab = tabBar.tabs.find(t => t.id === 'screenshots');
            expect(screenshotsTab.badge).toBe(7);
        });
    });
});