/**
 * E2E smoke: страница загружается, есть <title>, основные элементы.
 *
 * Требования:
 * - Frontend запущен на http://127.0.0.1:8080 (или E2E_BASE_URL)
 * - Backend запущен на http://127.0.0.1:8000 (опционально — если выключен,
 *   приложение работает в offline-режиме, smoke должен проходить)
 */
const { test, expect } = require('@playwright/test');

test.describe('Smoke', () => {
    test('страница загружается и содержит title', async ({ page }) => {
        const response = await page.goto('/');
        expect(response).toBeTruthy();
        // Может быть 200 или 304 (cache), главное чтобы не 5xx
        expect(response.status()).toBeLessThan(500);

        await expect(page).toHaveTitle(/HTML_MeetingProtokol/);
    });

    test('есть header с заголовком приложения', async ({ page }) => {
        await page.goto('/');
        const header = page.locator('h1');
        await expect(header).toBeVisible();
        await expect(header).toContainText(/HTML_MeetingProtokol/);
    });

    test('есть nav-ссылки на основные вкладки', async ({ page }) => {
        await page.goto('/');
        const navLinks = page.locator('header .nav a, header nav a');
        const count = await navLinks.count();
        expect(count).toBeGreaterThanOrEqual(3);
    });

    test('есть footer с версией', async ({ page }) => {
        await page.goto('/');
        const footer = page.locator('.app-footer');
        await expect(footer).toBeVisible();
    });

    test('view-root присутствует', async ({ page }) => {
        await page.goto('/');
        const viewRoot = page.locator('#view-root');
        await expect(viewRoot).toBeAttached();
    });
});