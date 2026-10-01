/**
 * E2E screenshots: открыть вкладку скриншотов на протоколе, проверить кнопку.
 *
 * Шаги:
 * 1. Зайти на /#/protocols/<uuid>
 * 2. Кликнуть на вкладку "Скриншоты"
 * 3. Проверить что кнопка "Собрать скриншоты" видна
 */
const { test, expect } = require('@playwright/test');

const PROTOCOL_ID = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';

test.describe('Screenshots button', () => {
    test('страница протокола загружается', async ({ page }) => {
        // Мокаем все API вызовы
        await page.route('**/api/v1/hmp/**', async (route) => {
            const url = route.request().url();
            if (url.includes(`/protocols/${PROTOCOL_ID}`) && route.request().method() === 'GET' && !url.includes('screenshots') && !url.includes('utterances')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        id: PROTOCOL_ID,
                        title: 'Test Protocol',
                        date: '2025-01-15T10:00:00Z',
                        status: 'transcribed',
                    }),
                });
            } else if (url.includes('/utterances')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ items: [] }),
                });
            } else if (url.includes('/screenshots')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify([]),
                });
            } else {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify([]),
                });
            }
        });

        await page.goto(`/#/protocols/${PROTOCOL_ID}`);
        await page.waitForTimeout(500);

        // Заголовок протокола
        await expect(page.locator('h1')).toContainText('Test Protocol');
    });

    test('вкладка "Скриншоты" существует и кликабельна', async ({ page }) => {
        await page.route('**/api/v1/hmp/**', async (route) => {
            const url = route.request().url();
            if (url.includes(`/protocols/${PROTOCOL_ID}`) && !url.includes('screenshots') && !url.includes('utterances') && !url.includes('speakers') && !url.includes('tags') && !url.includes('actions') && !url.includes('decisions') && !url.includes('summary')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        id: PROTOCOL_ID,
                        title: 'Screenshots Test',
                        date: '2025-01-15T10:00:00Z',
                        status: 'transcribed',
                    }),
                });
            } else {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify([]),
                });
            }
        });

        await page.goto(`/#/protocols/${PROTOCOL_ID}`);
        await page.waitForTimeout(500);

        const screenshotsTab = page.locator('#tab-screenshots');
        await expect(screenshotsTab).toBeVisible();
        await screenshotsTab.click();
    });

    test('кнопка "Собрать скриншоты" видна после клика на вкладку', async ({ page }) => {
        await page.route('**/api/v1/hmp/**', async (route) => {
            const url = route.request().url();
            if (url.includes(`/protocols/${PROTOCOL_ID}`) && !url.includes('/screenshots') && !url.includes('/utterances')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        id: PROTOCOL_ID,
                        title: 'Synthesize Test',
                        date: '2025-01-15T10:00:00Z',
                        status: 'transcribed',
                    }),
                });
            } else if (url.includes('/utterances')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ items: [] }),
                });
            } else {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify([]),
                });
            }
        });

        await page.goto(`/#/protocols/${PROTOCOL_ID}`);
        await page.waitForTimeout(500);

        await page.click('#tab-screenshots');
        await page.waitForTimeout(200);

        const synthesizeBtn = page.locator('#btn-synthesize-screenshots');
        await expect(synthesizeBtn).toBeVisible();
        await expect(synthesizeBtn).toContainText(/Собрать/i);
    });

    test('select со strategies и input max видны', async ({ page }) => {
        await page.route('**/api/v1/hmp/**', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ items: [] }),
            });
        });

        // Перезапишем более специфичный мок для /protocols/<id>
        await page.route(`**/protocols/${PROTOCOL_ID}`, async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    id: PROTOCOL_ID,
                    title: 'Strategy Test',
                    date: '2025-01-15T10:00:00Z',
                    status: 'transcribed',
                }),
            });
        });

        await page.goto(`/#/protocols/${PROTOCOL_ID}`);
        await page.waitForTimeout(500);
        await page.click('#tab-screenshots');
        await page.waitForTimeout(200);

        await expect(page.locator('#synthesize-strategy')).toBeVisible();
        await expect(page.locator('#synthesize-max')).toBeVisible();

        const options = await page.locator('#synthesize-strategy option').count();
        expect(options).toBeGreaterThanOrEqual(3);

        const maxValue = await page.locator('#synthesize-max').inputValue();
        expect(maxValue).toBe('10');
    });

    test('клик на "Собрать скриншоты" → POST /screenshots/synthesize', async ({ page }) => {
        let synthesizeCalled = false;
        await page.route('**/api/v1/hmp/**', async (route) => {
            const url = route.request().url();
            if (url.includes('/screenshots/synthesize')) {
                synthesizeCalled = true;
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ screenshots_created: 3 }),
                });
            } else if (url.includes(`/protocols/${PROTOCOL_ID}`) && !url.includes('/screenshots') && !url.includes('/utterances')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        id: PROTOCOL_ID,
                        title: 'Click Test',
                        date: '2025-01-15T10:00:00Z',
                        status: 'transcribed',
                    }),
                });
            } else if (url.includes('/utterances')) {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ items: [] }),
                });
            } else {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify([]),
                });
            }
        });

        await page.goto(`/#/protocols/${PROTOCOL_ID}`);
        await page.waitForTimeout(500);
        await page.click('#tab-screenshots');
        await page.waitForTimeout(200);
        await page.click('#btn-synthesize-screenshots');
        await page.waitForTimeout(1000);

        expect(synthesizeCalled).toBe(true);
    });
});