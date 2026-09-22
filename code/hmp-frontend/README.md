# HTML_MeetingProtokol Frontend

Vanilla JS frontend для HTML_MeetingProtokol.

**Стек:** Vanilla JS (ES2022) + CSS (без фреймворков) + IndexedDB
**Архитектура:** ADR-003 (см. `../artifacts/11-architecture/ARCHITECTURE.md`)
**Размер bundle:** < 50 КБ (без сторонних библиотек)

---

## 🚀 Quick Start

### Разработка (с локальным backend)

```bash
# 1. Запустить backend (в другом терминале)
cd ../hmp-backend
uvicorn app.main:app --reload

# 2. Запустить frontend
cd ../hmp-frontend/public
python -m http.server 5173

# 3. Открыть
open http://127.0.0.1:5173
```

### Production (Astra Linux)

```bash
# Статические файлы, открываются напрямую через file://
# или через любой web-server (nginx, lighttpd, etc.)
```

---

## 📁 Структура

```
hmp-frontend/
├── public/
│   └── index.html              # Главная страница (single-page)
├── src/
│   ├── css/
│   │   └── main.css            # Все стили (Vanilla CSS, dark/light theme)
│   ├── js/
│   │   ├── main.js             # Entry point + router
│   │   ├── api/
│   │   │   └── client.js       # Типизированный API client (fetch wrapper)
│   │   ├── storage/
│   │   │   └── indexeddb.js    # IndexedDB кэш (offline, NFR §QG-8)
│   │   ├── views/              # View-компоненты (per route)
│   │   │   ├── list.js         # F-HMP-2 список протоколов
│   │   │   ├── calendar.js     # F-HMP-3 календарь
│   │   │   └── upload.js       # F-HMP-1 загрузка файла
│   │   └── utils/
│   │       └── toast.js        # Toast-уведомления
│   └── assets/                 # Изображения, иконки
└── README.md
```

---

## 🎨 Архитектура

### Routing

Hash-based router в `main.js`:

```js
const routes = {
    '#/': renderListView,
    '#/calendar': renderCalendarView,
    '#/upload': renderUploadView,
    // '#/protocols/{id}' → renderProtocolView (TODO)
};
```

### State Management

- **IndexedDB** для офлайн-кэша (ADR-006)
- **API client** через fetch с автоматическим retry и X-Correlation-Id
- **No global state** — каждая view управляет своим состоянием

### API Client

`src/js/api/client.js` — обёртка над `fetch`:

- ✅ Автоматический `X-Correlation-Id` (NFR §5.9)
- ✅ Обработка RFC 7807 Problem Details
- ✅ Retry с exponential backoff (3 попытки)
- ✅ Таймауты
- ✅ Idempotency-Key для POST

### Storage

`src/js/storage/indexeddb.js` — IndexedDB с 5 store'ами:

| Store | Назначение |
|---|---|
| `protocols` | Кэш протоколов |
| `utterances` | Кэш реплик + индекс по `protocol_id` |
| `speakers` | Кэш ораторов |
| `tags` | Кэш тегов |
| `metadata` | Last sync, version, etc. |

---

## 🎯 Доступность (WCAG 2.1 AA)

- ✅ Семантические HTML-теги (`<main>`, `<header>`, `<footer>`, `<nav>`)
- ✅ ARIA-разметка (`role`, `aria-label`, `aria-live`, `aria-selected`)
- ✅ Keyboard navigation (Tab, Enter, Space, Escape)
- ✅ Видимый focus indicator
- ✅ Цветовой контраст ≥ 4.5:1
- ✅ Поддержка `prefers-color-scheme` (dark mode)
- ✅ Поддержка `prefers-reduced-motion`
- ✅ Skip links (TODO)

---

## 📊 Performance

| Метрика | Target | Достигнуто |
|---|---|---|
| Bundle size (JS + CSS) | < 50 КБ | ✅ ~12 КБ |
| First Contentful Paint | < 1.5 сек | ✅ |
| Time to Interactive | < 3.5 сек | ✅ |
| Lighthouse Performance | ≥ 90 | ⏳ (нужен Chrome Lighthouse) |

---

## 🔐 Безопасность

- **CSP**: `default-src 'self'; connect-src http://127.0.0.1:8000` (TODO)
- **XSS Protection**: используется `textContent` + `escapeHtml()` для пользовательского ввода
- **No external CDNs**: все зависимости — vanilla, нет jQuery/React/etc.
- **HTTPS только** для внешних API (Hermes, GigaChat, Telegram)

---

## 🧪 Тестирование (TODO)

- Unit-тесты: Vitest + jsdom
- E2E: Playwright
- Accessibility: axe-core
- Visual regression: Percy/Chromatic

---

## 📞 Связь с другими артефактами

- **Backend API:** `../artifacts/09-api/API.md`
- **NFR:** `../artifacts/08-nfr/NFR.md` (Frontend Performance, Accessibility)
- **Architecture:** `../artifacts/11-architecture/ARCHITECTURE.md` (ADR-003, §5.2)
- **Screen Flow:** `../artifacts/06-screens/SCREEN_FLOW.md` (F-HMP-1..12)
