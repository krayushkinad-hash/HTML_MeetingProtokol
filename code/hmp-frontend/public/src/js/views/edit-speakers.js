// US-003 — диаризация review

/**
 * EditSpeakers view — управление ораторами и объединение.
 *
 * Позволяет:
 * - Переименовывать ораторов
 * - Изменять цвета
 * - Помечать "это я" (is_user)
 * - Объединять двух ораторов
 * - Удалять ораторов без реплик
 */
import { api } from '../api/client.js';
import { toast } from '../utils/toast.js';

export async function renderEditSpeakers(rootEl, protocolId) {
    rootEl.innerHTML = '<div class="loading"><div class="spinner"></div> Загрузка ораторов...</div>';

    let speakers, protocol;
    try {
        [protocol, speakers] = await Promise.all([
            api.getProtocol(protocolId),
            api.listSpeakers(protocolId),
        ]);
    } catch (err) {
        toast.error(`Ошибка: ${err.message}`);
        window.location.hash = `#/protocols/${protocolId}`;
        return;
    }

    if (!speakers.length) {
        rootEl.innerHTML = `
            <h1><i class="fa-solid fa-microphone"></i> Редактирование ораторов</h1>
            <p class="text-muted">В этом протоколе пока нет ораторов. Запустите диаризацию.</p>
            <button class="btn btn-primary" onclick="window.location.hash='#/protocols/${protocolId}'">← Назад к протоколу</button>
        `;
        return;
    }

    rootEl.innerHTML = `
        <div class="toolbar">
            <button class="btn" onclick="window.location.hash='#/protocols/${protocolId}'">← Назад</button>
            <h1 style="display:inline-block; margin-left:12px;"><i class="fa-solid fa-microphone"></i> Редактор ораторов</h1>
        </div>
        <p class="text-muted">Протокол: <strong>${escapeHtml(protocol.title)}</strong> · ${speakers.length} ораторов</p>

        <div class="speakers-edit-grid">
            ${speakers.map(s => `
                <div class="speaker-edit-card" style="border-left: 4px solid ${s.color || '#888'};" data-id="${s.id}">
                    <div class="speaker-header">
                        <input type="color" class="color-picker" value="${s.color || '#888888'}" data-field="color">
                        <input type="text" class="speaker-name-input" value="${escapeHtml(s.display_name || s.speaker_label)}" placeholder="${escapeHtml(s.speaker_label)}" data-field="display_name">
                    </div>
                    <div class="speaker-meta">
                        <span class="text-muted">${escapeHtml(s.speaker_label)}</span>
                        <label class="user-checkbox">
                            <input type="checkbox" ${s.is_user ? 'checked' : ''} data-field="is_user">
                            Это я
                        </label>
                    </div>
                    <div class="speaker-actions">
                        <button class="btn btn-primary btn-sm save-btn" data-action="save"><i class="fa-regular fa-floppy-disk"></i> Сохранить</button>
                        <button class="btn btn-danger btn-sm delete-btn" data-action="delete"><i class="fa-regular fa-trash-can"></i>️ Удалить</button>
                    </div>
                </div>
            `).join('')}
        </div>

        <hr style="margin: 32px 0;">

        <h2><i class="fa-solid fa-link"></i> Объединить ораторов</h2>
        <p class="text-muted">Перенесите все реплики одного оратора к другому.</p>
        <div class="merge-form">
            <select class="select" id="source-speaker">
                <option value="">— Источник (удалить) —</option>
                ${speakers.map(s => `<option value="${s.id}">${escapeHtml(s.display_name || s.speaker_label)}</option>`).join('')}
            </select>
            <span class="merge-arrow">→</span>
            <select class="select" id="target-speaker">
                <option value="">— Цель (оставить) —</option>
                ${speakers.map(s => `<option value="${s.id}">${escapeHtml(s.display_name || s.speaker_label)}</option>`).join('')}
            </select>
            <input type="text" class="input" id="merge-name" placeholder="Новое имя (опционально)">
            <button class="btn btn-primary" id="btn-merge"><i class="fa-solid fa-link"></i> Объединить</button>
        </div>
    `;

    // Wire up handlers
    rootEl.querySelectorAll('.speaker-edit-card').forEach(card => {
        const speakerId = card.dataset.id;

        card.querySelector('.save-btn').addEventListener('click', async () => {
            const data = {};
            card.querySelectorAll('[data-field]').forEach(input => {
                const field = input.dataset.field;
                if (input.type === 'checkbox') data[field] = input.checked;
                else data[field] = input.value;
            });
            try {
                await api.updateSpeaker(speakerId, data);
                toast.success('Оратор обновлён');
            } catch (err) {
                toast.error(`Ошибка: ${err.message}`);
            }
        });

        card.querySelector('.delete-btn').addEventListener('click', async () => {
            if (!confirm('Удалить оратора? Будут удалены ТОЛЬКО ораторы без реплик.')) return;
            try {
                await fetch(`http://127.0.0.1:8000/api/v1/hmp/speakers/${speakerId}`, { method: 'DELETE' });
                toast.success('Оратор удалён');
                renderEditSpeakers(rootEl, protocolId);
            } catch (err) {
                toast.error(`Ошибка: ${err.message}`);
            }
        });
    });

    document.getElementById('btn-merge').addEventListener('click', async () => {
        const sourceId = document.getElementById('source-speaker').value;
        const targetId = document.getElementById('target-speaker').value;
        const newName = document.getElementById('merge-name').value.trim() || null;

        if (!sourceId || !targetId) {
            toast.error('Выберите источник и цель');
            return;
        }
        if (sourceId === targetId) {
            toast.error('Источник и цель должны различаться');
            return;
        }
        if (!confirm('Объединить? Все реплики источника будут переназначены цели.')) return;

        try {
            await api.mergeSpeakers(sourceId, targetId, newName);
            toast.success('Ораторы объединены');
            renderEditSpeakers(rootEl, protocolId);
        } catch (err) {
            toast.error(`Ошибка: ${err.message}`);
        }
    });
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}
