// US-011 — календарь; US-014 — фильтр по дате

/**
 * Calendar view (F-HMP-3, US-011).
 */
import { api } from '../api/client.js';
import { toast } from '../utils/toast.js';

export async function renderCalendarView(rootEl) {
    const now = new Date();
    let year = now.getFullYear();
    let month = now.getMonth() + 1;

    rootEl.innerHTML = `
        <div class="toolbar">
            <button class="btn" id="prev-month">‹ Предыдущий</button>
            <h2 id="month-label" style="flex:1; text-align:center;"></h2>
            <button class="btn" id="next-month">Следующий ›</button>
        </div>
        <div id="calendar-grid"></div>
    `;

    const monthLabel = document.getElementById('month-label');
    const grid = document.getElementById('calendar-grid');

    document.getElementById('prev-month').addEventListener('click', () => {
        month--;
        if (month < 1) { month = 12; year--; }
        load();
    });
    document.getElementById('next-month').addEventListener('click', () => {
        month++;
        if (month > 12) { month = 1; year++; }
        load();
    });

    async function load() {
        const monthNames = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                            'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
        monthLabel.textContent = `${monthNames[month - 1]} ${year}`;

        grid.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

        try {
            const data = await api.getCalendar(year, month);
            render(data.counts_by_date || {});
        } catch (err) {
            toast.error(`Ошибка календаря: ${err.message}`);
            grid.innerHTML = `<p class="text-error">Не удалось загрузить календарь</p>`;
        }
    }

    function render(counts) {
        const firstDay = new Date(year, month - 1, 1).getDay();
        const daysInMonth = new Date(year, month, 0).getDate();
        const offset = (firstDay + 6) % 7; // Понедельник = 0

        let html = '<table style="width:100%; border-collapse:collapse;"><thead><tr>';
        ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].forEach(d => {
            html += `<th style="padding:8px; text-align:center; color:var(--text-muted); font-weight:500;">${d}</th>`;
        });
        html += '</tr></thead><tbody><tr>';

        for (let i = 0; i < offset; i++) {
            html += '<td style="padding:8px;"></td>';
        }

        for (let day = 1; day <= daysInMonth; day++) {
            if ((day + offset - 1) % 7 === 0 && day > 1) html += '</tr><tr>';
            const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            const count = counts[dateStr] || 0;
            // E223: используем локальную дату (не UTC), иначе после 21:00 MSK
            // "сегодня" выделялось бы неправильно.
            const _today = new Date();
            const todayStr = `${_today.getFullYear()}-${String(_today.getMonth() + 1).padStart(2, '0')}-${String(_today.getDate()).padStart(2, '0')}`;
            const isToday = dateStr === todayStr;
            const bg = count > 0 ? 'var(--accent)' : isToday ? 'var(--bg-tertiary)' : 'transparent';
            const color = count > 0 ? 'white' : 'inherit';
            html += `<td style="padding:8px; text-align:center; cursor:${count > 0 ? 'pointer' : 'default'}; background:${bg}; color:${color}; border-radius:6px;" data-date="${dateStr}">
                <div>${day}</div>
                ${count > 0 ? `<small>${count} ${count === 1 ? 'протокол' : count < 5 ? 'протокола' : 'протоколов'}</small>` : ''}
            </td>`;
        }
        html += '</tr></tbody></table>';
        grid.innerHTML = html;

        grid.querySelectorAll('td[data-date]').forEach(td => {
            td.addEventListener('click', () => {
                window.location.hash = `#/?date=${td.dataset.date}`;
            });
        });
    }

    await load();
}
