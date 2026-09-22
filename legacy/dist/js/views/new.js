/* ====== Представление: форма нового протокола ====== */

import { createProtocol } from '../storage.js';

export function renderNew(root) {
  root.innerHTML = `
    <h2>Новый протокол</h2>
    <form id="new-protocol-form">
      <div class="field">
        <label for="title">Название / тема совещания</label>
        <input id="title" name="title" required placeholder="Например: План спринта №14">
      </div>
      <div class="field">
        <label for="date">Дата</label>
        <input id="date" name="date" type="date" required>
      </div>
      <div class="field">
        <label for="location">Место проведения</label>
        <input id="location" name="location" placeholder="Переговорная 3 / Zoom">
      </div>
      <div class="field">
        <label for="chair">Председатель</label>
        <input id="chair" name="chair" placeholder="Иванов И.И.">
      </div>
      <div class="field">
        <label for="attendees">Участники (по одному на строку)</label>
        <textarea id="attendees" name="attendees" rows="4" placeholder="Петров П.П.&#10;Сидоров С.С."></textarea>
      </div>
      <div class="field">
        <label for="agenda">Повестка дня</label>
        <textarea id="agenda" name="agenda" rows="3"></textarea>
      </div>
      <div class="field">
        <label for="decisions">Решения</label>
        <textarea id="decisions" name="decisions" rows="4"></textarea>
      </div>
      <button type="submit">💾 Сохранить</button>
    </form>
  `;

  document.getElementById('new-protocol-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const protocol = {
      title: fd.get('title'),
      date: fd.get('date'),
      location: fd.get('location'),
      chair: fd.get('chair'),
      attendees: String(fd.get('attendees') || '').split('\n').map(s => s.trim()).filter(Boolean),
      agenda: fd.get('agenda'),
      decisions: fd.get('decisions'),
    };
    const saved = createProtocol(protocol);
    alert(`Протокол сохранён (id: ${saved.id}).`);
    document.querySelector('nav button[data-view="list"]').click();
  });
}