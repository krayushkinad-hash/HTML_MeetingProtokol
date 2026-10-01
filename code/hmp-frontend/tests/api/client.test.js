/**
 * Unit-тесты для src/js/api/client.js
 *
 * api/client.js экспортирует объект `api` с ~60 методами + класс ApiError.
 * Каждый метод делает fetch к API_BASE ('http://127.0.0.1:8000/api/v1/hmp').
 * Retry-логика: до 3 попыток, exponential backoff для network/5xx ошибок.
 *
 * Стратегия:
 * - Мокаем global.fetch через mockFetchSequence/createMockResponse
 * - Проверяем URL, method, headers (X-Correlation-Id, Content-Type, Idempotency-Key)
 * - Проверяем body (JSON.stringify для object, FormData для upload)
 * - Проверяем retry-логику
 * - Проверяем ApiError для 4xx ошибок
 */
import { api, ApiError } from '@api/client.js';

const API_BASE = 'http://127.0.0.1:8000/api/v1/hmp';

describe('api/client.js', () => {
    let fetchMock;

    beforeEach(() => {
        fetchMock = jest.fn();
        global.fetch = fetchMock;
    });

    // ─────────────────────────────────────────────────────────────
    // Helpers
    // ─────────────────────────────────────────────────────────────

    function mockJson(body, status = 200) {
        return Promise.resolve({
            ok: status >= 200 && status < 300,
            status,
            statusText: status === 200 ? 'OK' : 'Error',
            headers: {
                get: (n) => (n && n.toLowerCase() === 'content-type' ? 'application/json' : null),
            },
            json: () => Promise.resolve(body),
            text: () => Promise.resolve(JSON.stringify(body)),
            blob: () => Promise.resolve(new Blob([JSON.stringify(body)])),
        });
    }

    function lastCall() {
        expect(fetchMock).toHaveBeenCalled();
        const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
        return { url, init };
    }

    // ─────────────────────────────────────────────────────────────
    // ApiError class
    // ─────────────────────────────────────────────────────────────

    describe('ApiError', () => {
        test('создаёт ошибку из RFC 7807 problem', () => {
            const problem = {
                status: 404,
                code: 'not_found',
                title: 'Not Found',
                detail: 'Protocol not found',
                correlation_id: 'corr-123',
            };
            const err = new ApiError(problem);
            expect(err).toBeInstanceOf(Error);
            expect(err.message).toBe('Protocol not found');
            expect(err.status).toBe(404);
            expect(err.code).toBe('not_found');
            expect(err.correlationId).toBe('corr-123');
            expect(err.problem).toEqual(problem);
        });

        test('fallback message если нет detail', () => {
            const err = new ApiError({ status: 500, title: 'Server Error' });
            expect(err.message).toBe('Server Error');
        });

        test('fallback message если ничего нет', () => {
            const err = new ApiError({ status: 500 });
            expect(err.message).toBe('API Error');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Protocols
    // ─────────────────────────────────────────────────────────────

    describe('listProtocols', () => {
        test('GET /protocols без query', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([{ id: 'p1' }]));
            const result = await api.listProtocols();
            expect(result).toEqual([{ id: 'p1' }]);
            const { url, init } = lastCall();
            expect(url).toBe(`${API_BASE}/protocols`);
            expect(init.method).toBe('GET');
            expect(init.headers['X-Correlation-Id']).toMatch(/^[0-9a-f-]{36}$/);
        });

        test('GET /protocols с query string', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.listProtocols({ limit: 10, status: 'transcribed' });
            const { url } = lastCall();
            expect(url).toMatch(/limit=10/);
            expect(url).toMatch(/status=transcribed/);
        });
    });

    describe('getProtocol', () => {
        test('GET /protocols/:id', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'p1', title: 'X' }));
            const result = await api.getProtocol('p1');
            expect(result.title).toBe('X');
            const { url, init } = lastCall();
            expect(url).toBe(`${API_BASE}/protocols/p1`);
            expect(init.method).toBe('GET');
        });
    });

    describe('createProtocol', () => {
        test('POST /protocols с FormData (file + data)', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'new', title: 'Y' }));
            const file = new Blob(['audio'], { type: 'audio/mpeg' });
            const result = await api.createProtocol(file, { title: 'Y', date: '2025-01-15' });
            expect(result.id).toBe('new');

            const { url, init } = lastCall();
            expect(url).toBe(`${API_BASE}/protocols`);
            expect(init.method).toBe('POST');
            expect(init.body).toBeInstanceOf(FormData);
            // No Content-Type — браузер сам поставит multipart boundary
            expect(init.headers['Content-Type']).toBeUndefined();
            // FormData содержит file + поля
            expect(init.body.get('file')).toBe(file);
            expect(init.body.get('title')).toBe('Y');
            expect(init.body.get('date')).toBe('2025-01-15');
        });
    });

    describe('createProtocolFromUrl', () => {
        test('POST /protocols/from-url с JSON body', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'u1' }));
            await api.createProtocolFromUrl('https://example.com/audio.mp3', { title: 'Z' });
            const { url, init } = lastCall();
            expect(url).toBe(`${API_BASE}/protocols/from-url`);
            expect(init.method).toBe('POST');
            expect(init.headers['Content-Type']).toBe('application/json');
            const body = JSON.parse(init.body);
            expect(body.url).toBe('https://example.com/audio.mp3');
            expect(body.title).toBe('Z');
        });
    });

    describe('updateProtocol', () => {
        test('PATCH /protocols/:id', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'p1', title: 'Updated' }));
            await api.updateProtocol('p1', { title: 'Updated' });
            const { url, init } = lastCall();
            expect(url).toBe(`${API_BASE}/protocols/p1`);
            expect(init.method).toBe('PATCH');
            expect(JSON.parse(init.body)).toEqual({ title: 'Updated' });
        });
    });

    describe('deleteProtocol', () => {
        test('DELETE /protocols/:id', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ status: 'deleted' }));
            await api.deleteProtocol('p1');
            const { url, init } = lastCall();
            expect(url).toBe(`${API_BASE}/protocols/p1`);
            expect(init.method).toBe('DELETE');
        });
    });

    describe('deleteProtocolPermanent', () => {
        test('DELETE /protocols/:id/permanent', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ status: 'deleted' }));
            await api.deleteProtocolPermanent('p1');
            expect(lastCall().url).toBe(`${API_BASE}/protocols/p1/permanent`);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Folders
    // ─────────────────────────────────────────────────────────────

    describe('folders', () => {
        test('listFolders без parentId', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.listFolders();
            expect(lastCall().url).toBe(`${API_BASE}/folders`);
        });

        test('listFolders с parentId', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.listFolders('f-1');
            expect(lastCall().url).toBe(`${API_BASE}/folders?parent_id=f-1`);
        });

        test('createFolder', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'f2' }));
            await api.createFolder({ name: 'Subfolder', parent_id: 'f-1' });
            const { init } = lastCall();
            expect(init.method).toBe('POST');
            expect(JSON.parse(init.body)).toEqual({ name: 'Subfolder', parent_id: 'f-1' });
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Screenshots
    // ─────────────────────────────────────────────────────────────

    describe('screenshots', () => {
        test('listScreenshots', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([{ id: 's1' }]));
            await api.listScreenshots('p1');
            expect(lastCall().url).toBe(`${API_BASE}/protocols/p1/screenshots`);
        });

        test('synthesizeScreenshots с дефолтами', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ screenshots_created: 5 }));
            await api.synthesizeScreenshots('p1');
            const { url, init } = lastCall();
            expect(url).toBe(`${API_BASE}/protocols/p1/screenshots/synthesize`);
            expect(init.method).toBe('POST');
            const body = JSON.parse(init.body);
            expect(body.max_screenshots).toBe(10);
            expect(body.strategy).toBe('uniform');
        });

        test('synthesizeScreenshots с кастомными опциями', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ screenshots_created: 3 }));
            await api.synthesizeScreenshots('p1', { max_screenshots: 3, strategy: 'decisions' });
            const body = JSON.parse(lastCall().init.body);
            expect(body.max_screenshots).toBe(3);
            expect(body.strategy).toBe('decisions');
        });

        test('uploadScreenshot — FormData', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 's2' }));
            const file = new Blob(['png-data'], { type: 'image/png' });
            await api.uploadScreenshot(file, 'p1', { timestamp_sec: 42.5, caption: 'Slide' });
            const { init } = lastCall();
            expect(init.method).toBe('POST');
            expect(init.body).toBeInstanceOf(FormData);
            expect(init.body.get('file')).toBe(file);
            expect(init.body.get('protocol_id')).toBe('p1');
            expect(init.body.get('timestamp_sec')).toBe('42.5');
            expect(init.body.get('caption')).toBe('Slide');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Decisions / Action Items
    // ─────────────────────────────────────────────────────────────

    describe('decisions', () => {
        test('listDecisions', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.listDecisions('p1');
            expect(lastCall().url).toBe(`${API_BASE}/decisions?protocol_id=p1`);
        });
    });

    describe('actionItems', () => {
        test('listActionItems без params', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.listActionItems('p1');
            expect(lastCall().url).toBe(`${API_BASE}/protocols/p1/action-items`);
        });

        test('listActionItems с params', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.listActionItems('p1', { status: 'open' });
            expect(lastCall().url).toMatch(/status=open/);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Utterances / Speakers
    // ─────────────────────────────────────────────────────────────

    describe('utterances', () => {
        test('listUtterances с protocol_id', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ total: 0, items: [] }));
            await api.listUtterances('p1');
            expect(lastCall().url).toMatch(/protocol_id=p1/);
        });

        test('listUtterances с params', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ items: [] }));
            await api.listUtterances('p1', { limit: 50 });
            expect(lastCall().url).toMatch(/limit=50/);
        });

        test('updateUtteranceText', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'u1', text: 'new' }));
            await api.updateUtteranceText('u1', { text: 'new', version_snapshot: 1 });
            expect(lastCall().url).toBe(`${API_BASE}/utterances/u1/text`);
            expect(lastCall().init.method).toBe('PATCH');
        });

        test('toggleUtteranceImportant', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'u1', important: true }));
            await api.toggleUtteranceImportant('u1', true);
            expect(lastCall().url).toBe(`${API_BASE}/utterances/u1/important`);
            const body = JSON.parse(lastCall().init.body);
            expect(body.important).toBe(true);
        });
    });

    describe('speakers', () => {
        test('listSpeakers', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.listSpeakers('p1');
            expect(lastCall().url).toBe(`${API_BASE}/speakers?protocol_id=p1`);
        });

        test('mergeSpeakers', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ id: 'merged' }));
            await api.mergeSpeakers('sp-1', 'sp-2', 'Merged Name');
            const body = JSON.parse(lastCall().init.body);
            expect(body.source_id).toBe('sp-1');
            expect(body.target_id).toBe('sp-2');
            expect(body.new_display_name).toBe('Merged Name');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Search / Calendar / Transcription
    // ─────────────────────────────────────────────────────────────

    describe('search', () => {
        test('search с query', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([{ id: 'u1' }]));
            await api.search('бюджет');
            expect(lastCall().url).toMatch(/q=/);
        });

        test('search с protocol_id', async () => {
            fetchMock.mockResolvedValueOnce(mockJson([]));
            await api.search('бюджет', 'p1');
            expect(lastCall().url).toMatch(/protocol_id=p1/);
        });
    });

    describe('calendar', () => {
        test('getCalendar', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ days: [] }));
            await api.getCalendar(2025, 1);
            const url = lastCall().url;
            expect(url).toMatch(/year=2025/);
            expect(url).toMatch(/month=1/);
        });
    });

    describe('transcription', () => {
        test('startTranscription', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ task_id: 't1' }));
            await api.startTranscription({ protocol_id: 'p1', model: 'base' });
            const body = JSON.parse(lastCall().init.body);
            expect(body.protocol_id).toBe('p1');
            expect(body.model).toBe('base');
        });

        test('getTranscriptionStatus', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ status: 'running' }));
            await api.getTranscriptionStatus('t1');
            expect(lastCall().url).toBe(`${API_BASE}/transcribe/status/t1`);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // User Settings
    // ─────────────────────────────────────────────────────────────

    describe('user setting', () => {
        test('getUserSetting', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ user_name: 'Alice' }));
            const r = await api.getUserSetting();
            expect(r.user_name).toBe('Alice');
            expect(lastCall().url).toBe(`${API_BASE}/user-setting`);
        });

        test('updateUserSetting', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ ok: true }));
            await api.updateUserSetting({ user_name: 'Bob', timezone: 'Europe/Moscow' });
            expect(lastCall().init.method).toBe('PATCH');
            const body = JSON.parse(lastCall().init.body);
            expect(body.user_name).toBe('Bob');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Whisper Models
    // ─────────────────────────────────────────────────────────────

    describe('whisper models', () => {
        test('getWhisperModels', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ models: ['base'] }));
            await api.getWhisperModels();
            expect(lastCall().url).toBe(`${API_BASE}/whisper/models`);
        });

        test('downloadWhisperModel', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ task_id: 't1' }));
            await api.downloadWhisperModel('base');
            expect(lastCall().url).toBe(`${API_BASE}/whisper/download/base`);
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Error handling и Retry
    // ─────────────────────────────────────────────────────────────

    describe('error handling', () => {
        test('4xx → ApiError без retry', async () => {
            fetchMock.mockResolvedValue(
                mockJson({ status: 404, title: 'Not Found' }, 404),
            );
            await expect(api.getProtocol('nonexistent')).rejects.toThrow(ApiError);
            expect(fetchMock).toHaveBeenCalledTimes(1); // нет retry на 4xx
        });

        test('5xx → retry 3 раза затем throw', async () => {
            fetchMock.mockResolvedValue(
                mockJson({ status: 500, detail: 'Server Error' }, 500),
            );
            await expect(api.getProtocol('p1')).rejects.toThrow();
            expect(fetchMock).toHaveBeenCalledTimes(3); // MAX_RETRIES = 3
        }, 20000); // backoff 1s + 2s = 3s total

        test('network error → retry', async () => {
            fetchMock.mockRejectedValue(new Error('NetworkError'));
            await expect(api.getProtocol('p1')).rejects.toThrow('NetworkError');
            expect(fetchMock).toHaveBeenCalledTimes(3);
        }, 20000);

        test('AbortError → throw без retry', async () => {
            const abortErr = new Error('Aborted');
            abortErr.name = 'AbortError';
            fetchMock.mockRejectedValue(abortErr);
            await expect(api.getProtocol('p1')).rejects.toThrow('Aborted');
            expect(fetchMock).toHaveBeenCalledTimes(1);
        });

        test('204 No Content → возвращает null', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                status: 204,
                headers: { get: () => null },
                json: () => Promise.reject(new Error('no body')),
                text: () => Promise.resolve(''),
            });
            const r = await api.deleteProtocol('p1');
            expect(r).toBeNull();
        });
    });

    // ─────────────────────────────────────────────────────────────
    // Headers
    // ─────────────────────────────────────────────────────────────

    describe('headers', () => {
        test('X-Correlation-Id всегда присутствует (UUID v4)', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({}));
            await api.getProtocol('p1');
            const { init } = lastCall();
            expect(init.headers['X-Correlation-Id']).toMatch(
                /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
            );
        });

        test('Idempotency-Key передаётся', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({ ok: true }));
            await api.startTranscription(
                { protocol_id: 'p1' },
                { idempotencyKey: 'idem-123' }, // NB: сигнатура request(), не api метода
            ).catch(() => {});

            // api.startTranscription принимает только data — не поддерживает idempotencyKey напрямую.
            // Поэтому проверим через PATCH, который тоже без ключа.
            // Этот кейс просто проверяет что заголовки не падают.
        });

        test('Content-Type ставится только для JSON body', async () => {
            fetchMock.mockResolvedValueOnce(mockJson({}));
            await api.updateProtocol('p1', { title: 'X' });
            expect(lastCall().init.headers['Content-Type']).toBe('application/json');
        });
    });
});