/* ====== Точка входа приложения HTML_MeetingProtokol ====== */

import { initStorage } from './storage.js';
import { renderList } from './views/list.js';
import { renderNew } from './views/new.js';
import { renderExport } from './views/export.js';

const app = document.getElementById('app');

const routes = {
  list: renderList,
  new: renderNew,
  export: renderExport,
};

function navigate(view) {
  const renderer = routes[view] || (() => {
    app.innerHTML = '<p class="placeholder">Раздел не найден.</p>';
  });
  renderer(app);
}

document.querySelectorAll('nav button[data-view]').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.view));
});

// Инициализация локального хранилища и стартовый экран
initStorage();
navigate('list');

console.info('HTML_MeetingProtokol запущен. Версия 0.1.0');