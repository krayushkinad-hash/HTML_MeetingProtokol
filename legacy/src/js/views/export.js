/* ====== Представление: экспорт ====== */

import { listProtocols } from '../storage.js';

export function renderExport(root) {
  const items = listProtocols();

  root.innerHTML = `
    <h2>Экспорт</h2>
    <p>Выберите протокол для экспорта в печатный HTML или JSON.</p>
    ${items.length === 0
      ? '<p class="placeholder">Нет данных для экспорта.</p>'
      : items.map(p => `
          <article class="protocol-card">
            <h3>${escapeHtml(p.title || 'Без названия')} — ${escapeHtml(p.date || '—')}</h3>
            <button data-act="print" data-id="${p.id}">🖨 Печать / HTML</button>
            <button data-act="json" data-id="${p.id}">{ } JSON</button>
          </article>
        `).join('')
    }
  `;

  root.querySelectorAll('button[data-act]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      const protocol = items.find(p => p.id === id);
      if (!protocol) return;
      if (btn.dataset.act === 'json') downloadJSON(protocol);
      if (btn.dataset.act === 'print') openPrintView(protocol);
    });
  });
}

function downloadJSON(protocol) {
  const blob = new Blob([JSON.stringify(protocol, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `protocol_${protocol.date || protocol.id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function openPrintView(protocol) {
  const w = window.open('', '_blank');
  w.document.write(`
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>${escapeHtml(protocol.title)}</title>
    <style>body{font-family:Times New Roman,serif;max-width:800px;margin:24px auto;line-height:1.5}
    h1{text-align:center}table{width:100%;border-collapse:collapse}td,th{border:1px solid #000;padding:6px}
    </style></head><body>
    <h1>ПРОТОКОЛ СОВЕЩАНИЯ</h1>
    <p><b>Тема:</b> ${escapeHtml(protocol.title || '')}<br>
       <b>Дата:</b> ${escapeHtml(protocol.date || '')}<br>
       <b>Место:</b> ${escapeHtml(protocol.location || '')}<br>
       <b>Председатель:</b> ${escapeHtml(protocol.chair || '')}</p>
    <h2>Участники</h2>
    <ol>${(protocol.attendees || []).map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ol>
    <h2>Повестка</h2><pre>${escapeHtml(protocol.agenda || '')}</pre>
    <h2>Решения</h2><pre>${escapeHtml(protocol.decisions || '')}</pre>
    </body></html>
  `);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 300);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}