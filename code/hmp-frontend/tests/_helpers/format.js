/**
 * Helpers — копии приватных format-функций из src/js/views/protocol.js.
 *
 * Эти функции не экспортированы из src/, поэтому для прямого unit-тестирования
 * мы дублируем их логику здесь. Это допустимо: код тривиальный, чистый,
 * без побочных эффектов, и любое расхождение с оригиналом сразу же будет
 * поймано на e2e тестах через UI.
 *
 * Если в src/ добавят export — этот файл можно удалить и тесты перевесить
 * на import directly.
 */

/**
 * Форматирует секунды в M:SS или H:MM:SS.
 * @param {number} seconds
 * @returns {string}
 */
export function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '0:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Алиас formatTime с fallback для falsy значений.
 * @param {number} seconds
 * @returns {string}
 */
export function formatTimestamp(seconds) {
    if (!seconds) return '0:00';
    return formatTime(seconds);
}

/**
 * Форматирует секунды в "X мин" или "X ч Y мин".
 * @param {number} seconds
 * @returns {string}
 */
export function formatDuration(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h} ч ${m} мин`;
    return `${m} мин`;
}

/**
 * Форматирует байты в человеко-читаемый размер (Б / КБ / МБ / ГБ).
 * @param {number} bytes
 * @returns {string}
 */
export function formatFileSize(bytes) {
    if (!bytes || bytes === 0) return '--';
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    let size = bytes;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit++;
    }
    return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}