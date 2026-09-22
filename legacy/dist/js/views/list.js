/* ====== Представление: список протоколов ====== */

import { listProtocols, deleteProtocol } from '../storage.js';

export function renderList(root) {
  const items = listProtocols();

  root.innerHTML = `
    <h2>Протоколы совещаний</h2>
    ${items.length === 0
      ? '<p class="placeholder">Пока нет ни одного протокола. Создайте первый.</p>'
      : items.map(p => `
          <article class="protocol-card" data-id="${p.id}">
            <h3>${escapeHtml(p.title || 'Без названия')}</h3>
            <p><strong>Дата:</strong> ${escapeHtml(p.date || '—')}</p>
            <p><strong>Место:</strong> ${escapeHtml(p.location || '—')}</p>
            <p><strong>Председатель:</strong> ${escapeHtml(p.chair || '—')}</p>
            <p><strong>Участников:</strong> ${(p.attendees || []).length}</p>
            <div class="actions">
              <button data-act="open" data-id="${p.id}">Открыть</button>
              <button data-act="delete" data-id="${p.id}">Удалить</button>
            </div>
          </article>
        `).join('')
    }
  `;

  root.querySelectorAll('button[data-act]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      if (btn.dataset.act === 'delete') {
        if (confirm('Удалить протокол?')) {
          deleteProtocol(id);
          renderList(root);
        }
      } else if (btn.dataset.act === 'open') {
        alert(`Просмотр протокола ${id} (будет реализовано на шаге CRUD-генератора).`);
      }
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}