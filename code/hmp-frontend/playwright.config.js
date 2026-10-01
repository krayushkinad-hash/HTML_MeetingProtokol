/**
 * Playwright config для HMP frontend E2E тестов.
 *
 * По умолчанию E2E тесты подключаются к локально запущенному backend
 * (http://127.0.0.1:8000) и frontend (http://127.0.0.1:8080 или подобный).
 *
 * Использование:
 *   1. Запусти backend: cd code/hmp-backend && uvicorn ...
 *   2. Запусти frontend server: cd code/hmp-frontend/public && python -m http.server 8080
 *   3. Запусти тесты: npm run test:e2e
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
    testDir: './tests/e2e',
    fullyParallel: false,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    workers: 1, // serial — single browser context

    reporter: [
        ['list'],
        ['html', { outputFolder: '../playwright-report', open: 'never' }],
    ],

    use: {
        baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8080',
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',
        actionTimeout: 10000,
        navigationTimeout: 30000,
    },

    projects: [
        {
            name: 'chromium',
            use: { ...devices['Desktop Chrome'] },
        },
    ],

    // Без автозапуска webServer — backend и frontend запускает пользователь
    // (по требованию проекта, чтобы можно было подключиться к реальному стенду)
});