/**
 * Unit-тесты для format-хелперов (formatTime / formatTimestamp /
 * formatDuration / formatFileSize).
 *
 * Эти функции приватные в src/js/views/protocol.js, поэтому для
 * тестирования мы используем их логические копии из tests/_helpers/format.js.
 * Если в src/ добавят export — можно переключиться на прямой import.
 */
import {
    formatTime,
    formatTimestamp,
    formatDuration,
    formatFileSize,
} from '@tests/_helpers/format.js';

describe('format helpers', () => {
    // ─────────────────────────────────────────────────────────────
    // formatTime
    // ─────────────────────────────────────────────────────────────

    describe('formatTime', () => {
        test('форматирует 0 секунд', () => {
            expect(formatTime(0)).toBe('0:00');
        });

        test('форматирует секунды', () => {
            expect(formatTime(5)).toBe('0:05');
        });

        test('форматирует минуты и секунды', () => {
            expect(formatTime(65)).toBe('1:05');
        });

        test('форматирует минуты с padding', () => {
            expect(formatTime(305)).toBe('5:05');
        });

        test('форматирует часы, минуты, секунды', () => {
            expect(formatTime(3661)).toBe('1:01:01');
        });

        test('форматирует ровно 1 час', () => {
            expect(formatTime(3600)).toBe('1:00:00');
        });

        test('fallback для NaN', () => {
            expect(formatTime(NaN)).toBe('0:00');
        });

        test('fallback для Infinity', () => {
            expect(formatTime(Infinity)).toBe('0:00');
        });

        test('fallback для отрицательных', () => {
            expect(formatTime(-5)).toBe('0:00');
        });

        test('fallback для undefined', () => {
            expect(formatTime(undefined)).toBe('0:00');
        });

        test('padding для минут при часах', () => {
            expect(formatTime(3605)).toBe('1:00:05');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // formatTimestamp
    // ─────────────────────────────────────────────────────────────

    describe('formatTimestamp', () => {
        test('0 → 0:00', () => {
            expect(formatTimestamp(0)).toBe('0:00');
        });

        test('null → 0:00', () => {
            expect(formatTimestamp(null)).toBe('0:00');
        });

        test('undefined → 0:00', () => {
            expect(formatTimestamp(undefined)).toBe('0:00');
        });

        test('передаёт в formatTime', () => {
            expect(formatTimestamp(125)).toBe('2:05');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // formatDuration
    // ─────────────────────────────────────────────────────────────

    describe('formatDuration', () => {
        test('только минуты', () => {
            expect(formatDuration(300)).toBe('5 мин');
        });

        test('0 секунд → 0 мин', () => {
            expect(formatDuration(0)).toBe('0 мин');
        });

        test('1 час ровно → "1 ч 0 мин"', () => {
            expect(formatDuration(3600)).toBe('1 ч 0 мин');
        });

        test('1 час 30 мин', () => {
            expect(formatDuration(3600 + 30 * 60)).toBe('1 ч 30 мин');
        });

        test('больше часа — округление минут вниз', () => {
            expect(formatDuration(3600 + 90)).toBe('1 ч 1 мин');
        });

        test('секунды игнорируются (округляются вниз до минут)', () => {
            expect(formatDuration(125)).toBe('2 мин');
        });
    });

    // ─────────────────────────────────────────────────────────────
    // formatFileSize
    // ─────────────────────────────────────────────────────────────

    describe('formatFileSize', () => {
        test('0 → "--"', () => {
            expect(formatFileSize(0)).toBe('--');
        });

        test('null → "--"', () => {
            expect(formatFileSize(null)).toBe('--');
        });

        test('undefined → "--"', () => {
            expect(formatFileSize(undefined)).toBe('--');
        });

        test('маленький размер в байтах', () => {
            expect(formatFileSize(500)).toBe('500 Б');
        });

        test('1024 байта → 1.0 КБ', () => {
            expect(formatFileSize(1024)).toBe('1.0 КБ');
        });

        test('1.5 КБ', () => {
            expect(formatFileSize(1536)).toBe('1.5 КБ');
        });

        test('1 МБ', () => {
            expect(formatFileSize(1024 * 1024)).toBe('1.0 МБ');
        });

        test('10 МБ (10 * 1024 * 1024)', () => {
            expect(formatFileSize(10 * 1024 * 1024)).toBe('10.0 МБ');
        });

        test('1 ГБ', () => {
            expect(formatFileSize(1024 * 1024 * 1024)).toBe('1.0 ГБ');
        });

        test('большой размер в ГБ', () => {
            expect(formatFileSize(5 * 1024 * 1024 * 1024)).toBe('5.0 ГБ');
        });

        test('не округляет до ГБ если > ГБ (cap)', () => {
            // 1024 ГБ в байтах = 1.099e12 — превышает max unit
            // Остаётся в ГБ (максимальный юнит)
            const huge = 1024 * 1024 * 1024 * 1024; // 1024 ГБ
            expect(formatFileSize(huge)).toBe('1024.0 ГБ');
        });
    });
});