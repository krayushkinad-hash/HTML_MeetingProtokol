// US-013 — локальный кэш для поиска

/**
 * Storage layer — IndexedDB кэш для офлайн-режима (NFR §QG-8, ADR-006).
 *
 * Используется для:
 * - Кэширования протоколов для Astra Linux офлайн
 * - Ускорения загрузки при повторном открытии
 */

const DB_NAME = 'html_mp_v1';
const DB_VERSION = 3;
export const STORES = {
    protocols: 'protocols',
    utterances: 'utterances',
    speakers: 'speakers',
    tags: 'tags',
    metadata: 'metadata',
    action_items: 'action_items',
    decisions: 'decisions',
    summaries: 'summaries',
    screenshots: 'screenshots',
};

let dbPromise = null;

function openDB() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
        // First, try to open with the current version
        const request = indexedDB.open(DB_NAME);

        request.onerror = () => {
            // Only delete if DB version is corrupted (rare case)
            console.warn('Database open failed, trying repair...');
            const deleteReq = indexedDB.deleteDatabase(DB_NAME);
            deleteReq.onsuccess = () => {
                console.log('Old database deleted, creating fresh');
                const retry = indexedDB.open(DB_NAME, DB_VERSION);
                retry.onupgradeneeded = (e) => createStores(e.target.result);
                retry.onsuccess = () => resolve(retry.result);
                retry.onerror = () => reject(retry.error);
            };
            deleteReq.onerror = () => reject(request.error);
            deleteReq.onblocked = () => {
                console.error('Database delete blocked - close other tabs');
                reject(new Error('Database blocked by other tabs'));
            };
        };
        request.onsuccess = () => {
            const db = request.result;
            // Check if all expected stores exist
            const expectedStores = Object.values(STORES);
            const missingStores = expectedStores.filter(s => !db.objectStoreNames.contains(s));

            if (missingStores.length > 0) {
                console.log('Missing stores detected:', missingStores);
                console.log('Will create them in upgrade (close DB first)...');
                db.close();

                // Increment version to trigger upgrade
                const newVersion = db.version + 1;
                const upgradeReq = indexedDB.open(DB_NAME, newVersion);

                upgradeReq.onupgradeneeded = (e) => {
                    createStores(e.target.result);
                };

                upgradeReq.onsuccess = () => {
                    console.log('Stores created successfully');
                    resolve(upgradeReq.result);
                };

                upgradeReq.onerror = () => {
                    console.error('Failed to create stores');
                    reject(upgradeReq.error);
                };
            } else {
                resolve(db);
            }
        };
        request.onupgradeneeded = (event) => {
            createStores(event.target.result);
        };
    });
    return dbPromise;
}

function createStores(db) {
    if (!db.objectStoreNames.contains(STORES.protocols)) {
        db.createObjectStore(STORES.protocols, { keyPath: 'id' });
    }
    if (!db.objectStoreNames.contains(STORES.utterances)) {
        const store = db.createObjectStore(STORES.utterances, { keyPath: 'id' });
        store.createIndex('by_protocol', 'protocol_id');
        store.createIndex('by_text', 'text');
    }
    if (!db.objectStoreNames.contains(STORES.speakers)) {
        const store = db.createObjectStore(STORES.speakers, { keyPath: 'id' });
        store.createIndex('by_protocol', 'protocol_id');
    }
    if (!db.objectStoreNames.contains(STORES.tags)) {
        const store = db.createObjectStore(STORES.tags, { keyPath: 'id' });
        store.createIndex('by_protocol', 'protocol_id');
    }
    if (!db.objectStoreNames.contains(STORES.metadata)) {
        db.createObjectStore(STORES.metadata, { keyPath: 'key' });
    }
    if (!db.objectStoreNames.contains(STORES.action_items)) {
        const store = db.createObjectStore(STORES.action_items, { keyPath: 'id' });
        store.createIndex('by_protocol', 'protocol_id');
    }
    if (!db.objectStoreNames.contains(STORES.decisions)) {
        const store = db.createObjectStore(STORES.decisions, { keyPath: 'id' });
        store.createIndex('by_protocol', 'protocol_id');
    }
    if (!db.objectStoreNames.contains(STORES.summaries)) {
        const store = db.createObjectStore(STORES.summaries, { keyPath: 'id' });
        store.createIndex('by_protocol', 'protocol_id');
    }
    if (!db.objectStoreNames.contains(STORES.screenshots)) {
        const store = db.createObjectStore(STORES.screenshots, { keyPath: 'id' });
        store.createIndex('by_protocol', 'protocol_id');
    }
}

/**
 * Check if store exists in database
 */
async function ensureStore(storeName) {
    try {
        const db = await openDB();
        if (!db.objectStoreNames.contains(storeName)) {
            console.warn(`Store ${storeName} not found, returning empty`);
            return false;
        }
        return true;
    } catch (e) {
        console.error(`Error opening DB: ${e}`);
        return false;
    }
}

async function put(storeName, value) {
    if (!(await ensureStore(storeName))) return;
    const db = await openDB();
    return new Promise((resolve, reject) => {
        try {
            const tx = db.transaction(storeName, 'readwrite');
            tx.objectStore(storeName).put(value);
            tx.oncomplete = () => resolve();
            tx.onerror = () => resolve(); // Don't reject, just resolve
        } catch (e) {
            console.warn(`put(${storeName}) failed:`, e);
            resolve();
        }
    });
}

async function get(storeName, key) {
    if (!(await ensureStore(storeName))) return null;
    const db = await openDB();
    return new Promise((resolve, reject) => {
        try {
            const tx = db.transaction(storeName, 'readonly');
            const request = tx.objectStore(storeName).get(key);
            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => resolve(null);
        } catch (e) {
            console.warn(`get(${storeName}) failed:`, e);
            resolve(null);
        }
    });
}

async function getAll(storeName) {
    if (!(await ensureStore(storeName))) return [];
    const db = await openDB();
    return new Promise((resolve, reject) => {
        try {
            const tx = db.transaction(storeName, 'readonly');
            const request = tx.objectStore(storeName).getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => resolve([]);
        } catch (e) {
            console.warn(`getAll(${storeName}) failed:`, e);
            resolve([]);
        }
    });
}

async function getByIndex(storeName, indexName, value) {
    if (!(await ensureStore(storeName))) return [];
    const db = await openDB();
    return new Promise((resolve, reject) => {
        try {
            const tx = db.transaction(storeName, 'readonly');
            const store = tx.objectStore(storeName);
            if (!store.indexNames.contains(indexName)) {
                console.warn(`Index ${indexName} not found on store ${storeName}`);
                resolve([]);
                return;
            }
            const idx = store.index(indexName);
            const request = idx.getAll(value);
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => resolve([]);
        } catch (e) {
            console.warn(`getByIndex(${storeName}, ${indexName}) failed:`, e);
            resolve([]);
        }
    });
}

async function deleteItem(storeName, key) {
    if (!(await ensureStore(storeName))) return;
    const db = await openDB();
    return new Promise((resolve, reject) => {
        try {
            const tx = db.transaction(storeName, 'readwrite');
            tx.objectStore(storeName).delete(key);
            tx.oncomplete = () => resolve();
            tx.onerror = () => resolve();
        } catch (e) {
            console.warn(`delete(${storeName}) failed:`, e);
            resolve();
        }
    });
}

async function clear(storeName) {
    if (!(await ensureStore(storeName))) return;
    const db = await openDB();
    return new Promise((resolve, reject) => {
        try {
            const tx = db.transaction(storeName, 'readwrite');
            tx.objectStore(storeName).clear();
            tx.oncomplete = () => resolve();
            tx.onerror = () => resolve();
        } catch (e) {
            console.warn(`clear(${storeName}) failed:`, e);
            resolve();
        }
    });
}

/**
 * Force recreate database (use if schema is corrupted)
 */
async function resetDB() {
    dbPromise = null;
    return new Promise((resolve, reject) => {
        const deleteReq = indexedDB.deleteDatabase(DB_NAME);
        deleteReq.onsuccess = () => {
            console.log('Database deleted, will recreate on next access');
            resolve();
        };
        deleteReq.onerror = () => reject(deleteReq.error);
        deleteReq.onblocked = () => {
            console.warn('Database deletion blocked. Close other tabs.');
            resolve();
        };
    });
}

export const storage = {
    put,
    get,
    getAll,
    getByIndex,
    delete: deleteItem,
    clear,
    reset: resetDB,
    open: openDB,
    STORES,
};
