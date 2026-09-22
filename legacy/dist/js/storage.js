/* ====== Локальное хранилище (LocalStorage) ====== */

const KEY = 'html_meeting_protokol_v1';

let cache = null;

export function initStorage() {
  const raw = localStorage.getItem(KEY);
  cache = raw ? JSON.parse(raw) : { protocols: [] };
  if (!Array.isArray(cache.protocols)) cache.protocols = [];
  save();
}

function save() {
  localStorage.setItem(KEY, JSON.stringify(cache));
}

export function listProtocols() {
  return [...cache.protocols].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
}

export function getProtocol(id) {
  return cache.protocols.find(p => p.id === id) || null;
}

export function createProtocol(data) {
  const protocol = {
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    ...data,
  };
  cache.protocols.push(protocol);
  save();
  return protocol;
}

export function updateProtocol(id, patch) {
  const idx = cache.protocols.findIndex(p => p.id === id);
  if (idx === -1) return null;
  cache.protocols[idx] = { ...cache.protocols[idx], ...patch, updatedAt: new Date().toISOString() };
  save();
  return cache.protocols[idx];
}

export function deleteProtocol(id) {
  const before = cache.protocols.length;
  cache.protocols = cache.protocols.filter(p => p.id !== id);
  if (cache.protocols.length !== before) {
    save();
    return true;
  }
  return false;
}