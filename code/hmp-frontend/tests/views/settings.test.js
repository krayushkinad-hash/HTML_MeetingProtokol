/**
 * Unit-тесты для src/js/views/settings.js
 *
 * renderSettingsView рендерит 5 вкладок (profile, transcription, ai, bot, data)
 * с формой и кнопкой сохранения. saveSettings (внутри модуля, не экспортирована)
 * — сохраняет draft в localStorage мгновенно, затем отправляет на API.
 *
 * Тестируем:
 * - renderSettingsView рендерит все 5 вкладок
 * - Активна вкладка profile по умолчанию
 * - Клик по вкладке transcription делает её активной
 * - renderSettingsView вызывает api.getUserSetting
 * - saveSettings: успех → toast.success, draft удаляется
 * - saveSettings: ошибка API → draft остаётся, toast.warning
 * - Кнопка "Сохранить" вызывает updateUserSetting
 */
import { renderSettingsView } from '@views/settings.js';

// toast.js использует DOM — замокаем
jest.mock('@utils/toast.js', () => ({
    toast: {
        success: jest.fn(),
        error: jest.fn(),
        warning: jest.fn(),
        info: jest.fn(),
    },
}));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { toast } = require('@utils/toast.js');

import {
    createMockResponse,
} from '@tests/setup.js';

describe('views/settings.js', () => {
    let rootEl;

    beforeEach(() => {
        document.body.innerHTML = '<div id="view-root"></div>';
        rootEl = document.getElementById('view-root');
        localStorage.clear();
        jest.clearAllMocks();
    });

    function mockFetchOk(body = {}) {
        global.fetch = jest.fn().mockResolvedValue(
            createMockResponse(body, { status: 200 }),
        );
    }

    function mockFetchFail(message = 'Server Error', status = 500) {
        global.fetch = jest.fn().mockResolvedValue(
            createMockResponse({ status, title: message }, { status }),
        );
    }

    // ─────────────────────────────────────────────────────────────
    // renderSettingsView
    // ─────────────────────────────────────────────────────────────

    describe('renderSettingsView', () => {
        test('рендерит заголовок "Настройки"', async () => {
            mockFetchOk({ user_name: 'Alice' });
            await renderSettingsView(rootEl);
            expect(rootEl.textContent).toContain('Настройки');
        });

        test('рендерит все 5 вкладок', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);
            const tabs = rootEl.querySelectorAll('.settings-tab');
            expect(tabs.length).toBe(5);
            const labels = Array.from(tabs).map(t => t.dataset.tab);
            expect(labels).toEqual(['profile', 'transcription', 'ai', 'bot', 'data']);
        });

        test('profile активна по умолчанию', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);
            const active = rootEl.querySelector('.settings-tab.active');
            expect(active).not.toBeNull();
            expect(active.dataset.tab).toBe('profile');
        });

        test('загружает user settings через api.getUserSetting', async () => {
            mockFetchOk({ user_name: 'Test User' });
            await renderSettingsView(rootEl);
            const input = rootEl.querySelector('#setting-name');
            expect(input).not.toBeNull();
            expect(input.value).toBe('Test User');
        });

        test('показывает email в форме profile', async () => {
            mockFetchOk({ email: 'test@example.com' });
            await renderSettingsView(rootEl);
            expect(rootEl.querySelector('#setting-email').value).toBe('test@example.com');
        });

        test('показывает timezone', async () => {
            mockFetchOk({ timezone: 'Europe/London' });
            await renderSettingsView(rootEl);
            const sel = rootEl.querySelector('#setting-tz');
            expect(sel.value).toBe('Europe/London');
        });

        test('fallback если API недоступен — рендерит пустые поля', async () => {
            // settings.js: loadSettings использует try/catch — не падает
            // saveDraft тоже try/catch
            // renderSettingsView должен отрендерить пустую форму
            global.fetch = jest.fn().mockRejectedValue(new Error('Network'));
            await expect(renderSettingsView(rootEl)).resolves.toBeUndefined();
            expect(rootEl.querySelector('#setting-name').value).toBe('');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Tab switching
    // ─────────────────────────────────────────────────────────────

    describe('переключение вкладок', () => {
        test('клик на transcription делает её активной', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            const transcriptionTab = rootEl.querySelector('.settings-tab[data-tab="transcription"]');
            transcriptionTab.click();

            expect(transcriptionTab.classList.contains('active')).toBe(true);
            // profile больше не активна
            const profileTab = rootEl.querySelector('.settings-tab[data-tab="profile"]');
            expect(profileTab.classList.contains('active')).toBe(false);
        });

        test('переключение на transcription рендерит whisper model select', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            rootEl.querySelector('.settings-tab[data-tab="transcription"]').click();
            // Ждём async рендер
            await new Promise(r => setTimeout(r, 10));

            expect(rootEl.querySelector('#setting-whisper-model')).not.toBeNull();
        });

        test('переключение на ai рендерит форму AI', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);
            rootEl.querySelector('.settings-tab[data-tab="ai"]').click();
            await new Promise(r => setTimeout(r, 10));
            // ai секция должна быть (любая разметка внутри #settings-content)
            const content = rootEl.querySelector('#settings-content');
            expect(content.textContent.length).toBeGreaterThan(20);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // saveSettings (через клик по "Сохранить")
    // ─────────────────────────────────────────────────────────────

    describe('saveSettings', () => {
        test('успешный save → toast.success, draft удаляется', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            // Установим значение
            rootEl.querySelector('#setting-name').value = 'New Name';
            rootEl.querySelector('#setting-email').value = 'new@example.com';

            // save → mock успешный updateUserSetting
            mockFetchOk({ ok: true });
            rootEl.querySelector('#btn-save-profile').click();

            // Ждём async
            await new Promise(r => setTimeout(r, 50));

            expect(toast.success).toHaveBeenCalled();
            // draft удалён после успешного API save
            expect(localStorage.getItem('hmp_settings_draft')).toBeNull();
        });

        test('failed save → toast.warning, draft остаётся', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            rootEl.querySelector('#setting-name').value = 'Offline User';

            mockFetchFail('Server Error');
            rootEl.querySelector('#btn-save-profile').click();
            await new Promise(r => setTimeout(r, 50));

            expect(toast.warning).toHaveBeenCalled();
            // Draft сохранён (т.к. saveDraft вызывается до API)
            const draft = localStorage.getItem('hmp_settings_draft');
            expect(draft).not.toBeNull();
            expect(JSON.parse(draft).user_name).toBe('Offline User');
        });

        test('save отправляет PATCH /user-setting', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            rootEl.querySelector('#setting-name').value = 'Patched User';
            rootEl.querySelector('#setting-email').value = 'patched@example.com';

            let patchCalled = null;
            global.fetch = jest.fn().mockImplementation((url, init) => {
                if (init.method === 'PATCH') {
                    patchCalled = { url, init };
                }
                return createMockResponse({}, { status: 200 });
            });

            rootEl.querySelector('#btn-save-profile').click();
            await new Promise(r => setTimeout(r, 50));

            expect(patchCalled).not.toBeNull();
            expect(patchCalled.url).toContain('/user-setting');
            expect(patchCalled.init.method).toBe('PATCH');
            const body = JSON.parse(patchCalled.init.body);
            expect(body.user_name).toBe('Patched User');
        });

        test('save draft немедленно (до API ответа)', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            rootEl.querySelector('#setting-name').value = 'Immediately Saved';
            // pending fetch
            let resolveFetch;
            global.fetch = jest.fn().mockReturnValueOnce(
                new Promise(r => { resolveFetch = r; }),
            );

            rootEl.querySelector('#btn-save-profile').click();
            // Без await — draft уже должен быть в localStorage
            await new Promise(r => setTimeout(r, 5));

            const draft = JSON.parse(localStorage.getItem('hmp_settings_draft') || '{}');
            expect(draft.user_name).toBe('Immediately Saved');

            // Резолвим fetch чтобы тест завершился
            resolveFetch(createMockResponse({}, { status: 200 }));
        });

        test('кнопка показывает "Сохранение..." во время запроса', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            // pending fetch
            let resolveFetch;
            global.fetch = jest.fn().mockReturnValueOnce(
                new Promise(r => { resolveFetch = r; }),
            );

            rootEl.querySelector('#btn-save-profile').click();
            await new Promise(r => setTimeout(r, 5));

            const btn = rootEl.querySelector('#btn-save-profile');
            expect(btn.disabled).toBe(true);
            expect(btn.textContent).toContain('Сохранение');

            // Резолвим
            resolveFetch(createMockResponse({}, { status: 200 }));
            await new Promise(r => setTimeout(r, 10));
            expect(btn.disabled).toBe(false);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Draft restore (если есть draft в localStorage)
    // ─────────────────────────────────────────────────────────────

    describe('draft restore', () => {
        test('draft перезаписывает server значения', async () => {
            localStorage.setItem('hmp_settings_draft', JSON.stringify({
                user_name: 'Draft Name',
                email: 'draft@example.com',
            }));
            mockFetchOk({ user_name: 'Server Name', email: 'server@example.com' });
            await renderSettingsView(rootEl);

            // draft должен выиграть
            expect(rootEl.querySelector('#setting-name').value).toBe('Draft Name');
            expect(rootEl.querySelector('#setting-email').value).toBe('draft@example.com');
        });

        test('change в input → saveDraft', async () => {
            mockFetchOk({});
            await renderSettingsView(rootEl);

            const nameInput = rootEl.querySelector('#setting-name');
            nameInput.value = 'Changed via blur';
            nameInput.dispatchEvent(new Event('change'));

            const draft = JSON.parse(localStorage.getItem('hmp_settings_draft') || '{}');
            expect(draft.user_name).toBe('Changed via blur');
        });
    });
});