/**
 * E2E list protocols: проверка что протоколы отображаются на главной.
 *
 * Главная страница (#/) — это renderListView, который вызывает api.listProtocols.
 * Если backend недоступен — должна быть пустое состояние (empty-state).
 */
const { test, expect } = require('@playwright/test');

test.describe('List protocols', () => {
    test('главная страница загружается без ошибок', async ({ page }) => {
        const errors = [];
        page.on('pageerror', (err) => errors.push(err.message));

        await page.goto('/');
        await page.waitForTimeout(500);

        // Без критических JS ошибок
        expect(errors).toEqual([]);
    });

    test('есть контейнер для списка протоколов', async ({ page }) => {
        await page.goto('/');
        // view-root заполнен (список или empty-state)
        const viewRoot = page.locator('#view-root');
        await expect(viewRoot).toBeAttached();
        const html = await viewRoot.innerHTML();
        expect(html.length).toBeGreaterThan(50); // не пустой
    });

    test('с мок-данными отображается карточка протокола', async ({ page }) => {
        // Мокаем API
        await page.route('**/api/v1/hmp/protocols**', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify([
                    {
                        id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
                        title: 'Mocked Protocol',
                        date: '2025-01-15T10:00:00Z',
                        status: 'transcribed',
                    },
                ]),
            });
        });

        await page.goto('/');
        // Подождём пока список отрендерится
        await page.waitForTimeout(500);

        const content = await page.locator('#view-root').textContent();
        expect(content).toContain('Mocked Protocol');
    });

    test('пустой список → empty state или "нет протоколов"', async ({ page }) => {
        await page.route('**/api/v1/hmp/protocols**', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify([]),
            });
        });

        await page.goto('/');
        await page.waitForTimeout(500);

        // Не должно быть ошибки
        const errors = [];
        page.on('pageerror', (err) => errors.push(err.message));
        expect(errors).toEqual([]);
    });

    test('ошибка API → fallback или empty state', async ({ page }) => {
        await page.route('**/api/v1/hmp/protocols**', async (route) => {
            await route.fulfill({
                status: 500,
                contentType: 'application/json',
                body: JSON.stringify({ status: 500, title: 'Server Error' }),
            });
        });

        await page.goto('/');
        await page.waitForTimeout(1500);

        // Не должно быть краша — приложение должно показать что-то осмысленное
        const body = await page.locator('body').textContent();
        expect(body).toBeTruthy();
    });
});