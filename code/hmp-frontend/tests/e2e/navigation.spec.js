/**
 * E2E navigation: клик на вкладки в шапке, проверка активной.
 *
 * Проверяем что hash router работает и подсвечивает активную вкладку.
 */
const { test, expect } = require('@playwright/test');

test.describe('Navigation', () => {
    test('клик на "Загрузить" → URL = #/upload, link активный', async ({ page }) => {
        await page.goto('/');

        const uploadLink = page.locator('header a[href="#/upload"]');
        await uploadLink.click();

        // URL обновился
        expect(page.url()).toMatch(/#\/upload/);

        // Active class
        await expect(uploadLink).toHaveClass(/active/);
    });

    test('клик на "Календарь" → URL = #/calendar, link активный', async ({ page }) => {
        await page.goto('/');

        const calLink = page.locator('header a[href="#/calendar"]');
        await calLink.click();

        expect(page.url()).toMatch(/#\/calendar/);
        await expect(calLink).toHaveClass(/active/);
    });

    test('клик на "Настройки" → URL = #/settings, link активный', async ({ page }) => {
        await page.goto('/');

        const settingsLink = page.locator('header a[href="#/settings"]');
        await settingsLink.click();

        expect(page.url()).toMatch(/#\/settings/);
        await expect(settingsLink).toHaveClass(/active/);
    });

    test('клик на "Протоколы" → URL = #/', async ({ page }) => {
        await page.goto('/#/calendar');

        const homeLink = page.locator('header a[href="#/"]').first();
        await homeLink.click();

        expect(page.url()).toMatch(/#\/$/);
    });

    test('только одна nav-link активна одновременно', async ({ page }) => {
        await page.goto('/');

        const activeLinks = page.locator('header a.active, header .nav-link.active');
        const count = await activeLinks.count();
        // Главная страница — одна активная (Протоколы)
        expect(count).toBe(1);
    });
});