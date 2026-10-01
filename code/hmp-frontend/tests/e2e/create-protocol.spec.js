/**
 * E2E create protocol: заполнить форму на /#/upload, отправить.
 *
 * Требования:
 * - Backend запущен (api.createProtocol должен вернуть 200/201)
 * - Тест использует File fixture (fixtures/test.mp3 если есть, либо synthetic)
 */
const { test, expect } = require('@playwright/test');

test.describe('Create protocol', () => {
    test('форма загружена с полями', async ({ page }) => {
        await page.goto('/#/upload');

        await expect(page.locator('#title-input')).toBeVisible();
        await expect(page.locator('#date-input')).toBeVisible();
        await expect(page.locator('#location-input')).toBeVisible();
        await expect(page.locator('#chair-input')).toBeVisible();
        await expect(page.locator('#agenda-input')).toBeVisible();
        await expect(page.locator('#submit-btn')).toBeVisible();
    });

    test('date по умолчанию = сегодня', async ({ page }) => {
        await page.goto('/#/upload');

        const dateValue = await page.locator('#date-input').inputValue();
        const today = new Date().toISOString().slice(0, 10);
        expect(dateValue).toBe(today);
    });

    test('заполнение формы title/location/chair/agenda', async ({ page }) => {
        await page.goto('/#/upload');

        await page.fill('#title-input', 'E2E Test Meeting');
        await page.fill('#location-input', 'Москва, оф. 404');
        await page.fill('#chair-input', 'Иванов И.И.');
        await page.fill('#agenda-input', '1. Тестирование E2E\n2. Автоматизация');

        await expect(page.locator('#title-input')).toHaveValue('E2E Test Meeting');
        await expect(page.locator('#location-input')).toHaveValue('Москва, оф. 404');
        await expect(page.locator('#chair-input')).toHaveValue('Иванов И.И.');
        await expect(page.locator('#agenda-input')).toHaveValue(/Тестирование E2E/);
    });

    test('submit без файла → ошибка валидации', async ({ page }) => {
        await page.goto('/#/upload');

        await page.fill('#title-input', 'Test');

        // Подготовим перехват API
        let createCalled = false;
        await page.route('**/api/v1/hmp/protocols', (route) => {
            if (route.request().method() === 'POST') {
                createCalled = true;
            }
            route.continue();
        });

        await page.click('#submit-btn');
        // Подождём немного
        await page.waitForTimeout(500);

        // Create НЕ должен был быть вызван без файла
        expect(createCalled).toBe(false);
    });

    test('переключение на URL-таб', async ({ page }) => {
        await page.goto('/#/upload');

        await page.click('#tab-url');
        await expect(page.locator('#tab-url')).toHaveAttribute('aria-selected', 'true');
        await expect(page.locator('#url-input')).toBeVisible();
        await expect(page.locator('#file-input')).toBeHidden();

        await page.click('#tab-local');
        await expect(page.locator('#tab-local')).toHaveAttribute('aria-selected', 'true');
    });

    test('submit с файлом → POST /protocols', async ({ page }) => {
        await page.goto('/#/upload');

        // Загрузим файл через setInputFiles
        await page.setInputFiles('#file-input', {
            name: 'test.mp3',
            mimeType: 'audio/mpeg',
            buffer: Buffer.from('fake-mp3-content'),
        });

        await page.fill('#title-input', 'Test With File');

        // Перехватим запрос
        const requestPromise = page.waitForRequest(
            (req) => req.url().includes('/protocols') && req.method() === 'POST',
            { timeout: 10000 },
        );

        await page.click('#submit-btn');

        const request = await requestPromise;
        expect(request.method()).toBe('POST');
        // multipart/form-data
        const headers = request.headers();
        expect(headers['content-type']).toMatch(/multipart\/form-data/);
    });

    test('submit → кнопка disabled и показывает progress', async ({ page }) => {
        await page.goto('/#/upload');
        await page.setInputFiles('#file-input', {
            name: 'test.mp3',
            mimeType: 'audio/mpeg',
            buffer: Buffer.from('x'),
        });
        await page.fill('#title-input', 'Disabled Test');

        // Замедлим ответ чтобы успеть проверить состояние
        await page.route('**/api/v1/hmp/protocols', async (route) => {
            await new Promise(r => setTimeout(r, 1000));
            await route.fulfill({
                status: 201,
                contentType: 'application/json',
                body: JSON.stringify({ id: 'new-id', title: 'Disabled Test' }),
            });
        });

        await page.click('#submit-btn');
        await expect(page.locator('#submit-btn')).toBeDisabled();
    });
});