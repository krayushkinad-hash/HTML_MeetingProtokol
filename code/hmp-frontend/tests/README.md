# HMP Frontend Tests

Тесты для frontend части **HTML_MeetingProtokol** (vanilla JS, ES modules, без фреймворков).

## Структура

```
code/hmp-frontend/
├── package.json              # dev-зависимости + npm scripts
├── jest.config.js            # конфиг Jest (jsdom env)
├── babel.config.json         # трансформ ESM через babel-jest
├── playwright.config.js      # конфиг Playwright для E2E
├── .eslintrc.json            # ESLint
├── .prettierrc.json          # Prettier
└── tests/
    ├── README.md             # ← этот файл
    ├── setup.js              # общие моки (fetch, localStorage, matchMedia) + helpers
    ├── _helpers/
    │   └── format.js         # formatTime/formatDuration/formatFileSize для прямого тестирования
    ├── api/
    │   └── client.test.js    # ~25 unit-тестов для api/client.js
    ├── views/
    │   ├── protocol.test.js      # renderProtocolDetail + renderUtteranceItem + synthesize
    │   ├── settings.test.js      # renderSettingsView + saveSettings + draft
    │   └── screenshots.test.js   # US-019: synthesize button
    ├── utils/
    │   └── format.test.js    # formatTime / formatTimestamp / formatDuration / formatFileSize
    └── e2e/
        ├── smoke.spec.js             # базовая загрузка
        ├── navigation.spec.js        # router + nav-link active
        ├── create-protocol.spec.js   # форма upload
        ├── list-protocols.spec.js    # главная с моками
        └── screenshot-button.spec.js # кнопка "Собрать скриншоты"
```

## Установка

```bash
cd code/hmp-frontend
npm install
```

## Запуск

### Все unit-тесты

```bash
npm test
```

С автоперезапуском при изменении:

```bash
npm run test:watch
```

Только определённая группа:

```bash
npm run test:unit
```

(запускает только `tests/api/`, `tests/views/`, `tests/utils/`)

### Coverage

```bash
npm run coverage
```

Генерирует:
- `coverage/lcov.info` — для CI (lcov)
- `coverage/index.html` — открыть в браузере для просмотра

Покрытие включает:
- `src/js/api/client.js`
- `src/js/views/protocol.js`
- `src/js/views/settings.js`
- `src/js/utils/toast.js`

### E2E тесты (Playwright)

E2E тесты **требуют запущенный frontend** (и опционально backend). По умолчанию `baseURL=http://127.0.0.1:8080`.

```bash
# 1. Запустить backend (в отдельном терминале)
cd code/hmp-backend
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Запустить frontend static server (в отдельном терминале)
cd code/hmp-frontend/public
python -m http.server 8080

# 3. Установить браузер для Playwright (один раз)
npm run test:e2e:install

# 4. Запустить тесты
npm run test:e2e
```

С кастомным URL:

```bash
E2E_BASE_URL=http://localhost:3000 npm run test:e2e
```

Только один spec:

```bash
npx playwright test tests/e2e/smoke.spec.js
```

### Lint + Format

```bash
npm run lint         # ESLint
npm run lint:fix     # ESLint --fix
npm run format       # Prettier --write
npm run format:check # проверка без изменений
```

## Что покрыто

### api/client.js (~25 тестов)
- **ApiError**: создание из RFC 7807 problem, fallback messages
- **Protocols**: listProtocols (с query params), getProtocol, createProtocol (FormData), createProtocolFromUrl (JSON), updateProtocol, deleteProtocol, deleteProtocolPermanent
- **Folders**: listFolders, createFolder
- **Screenshots**: listScreenshots, synthesizeScreenshots (с дефолтами и кастомными opts), uploadScreenshot (FormData)
- **Decisions / Action Items / Speakers / Utterances / Search / Calendar / Transcription / User Setting / Whisper Models**
- **Error handling**: 4xx (нет retry), 5xx (retry x3), network error (retry), AbortError (нет retry), 204 No Content
- **Headers**: X-Correlation-Id (UUID v4), Content-Type только для JSON

### views/protocol.js (~25 тестов)
- **renderProtocolDetail**: spinner, заголовок, вкладки, видео плеер, кнопки действий
- **renderUtteranceItem** (косвенно через `.transcript-list`):
  - speaker badge (с display_name и fallback)
  - timestamp button (⏱ + data-time)
  - важное ☆/⭐
  - low confidence (⚠️, danger/warning/success класс)
  - translation block
  - decision mark (⚖️)
- **renderScreenshotsTab**: synthesize button + strategy select + max input
- **handleClick на timestamp**: seekTo через audioPlayer, fallback на video.currentTime, NaN no-op
- **Cache fallback**: network error → IDB кэш, нет кэша → редирект

### views/settings.js (~14 тестов)
- **renderSettingsView**: заголовок, 5 вкладок, активная по умолчанию
- **Tab switching**: profile → transcription → ai
- **saveSettings**: success (draft удаляется), failed (draft остаётся), PATCH /user-setting
- **save draft**: немедленно до API ответа, change event в input
- **Button state**: "Сохранение..." + disabled во время запроса
- **Draft restore**: draft перезаписывает server значения

### views/screenshots.test.js (~10 тестов)
- **UI**: кнопка #btn-synthesize-screenshots, select strategies (4 шт.), input max, file input
- **Click handler**: POST /screenshots/synthesize, success toast, reload списка, error toast
- **Button disabled** во время запроса
- **Custom strategy**: decisions + max=5
- **Badge**: количество в tab-bar

### utils/format.test.js (~30 тестов)
- **formatTime**: 0, секунды, минуты, часы, padding, NaN/Infinity/negative
- **formatTimestamp**: 0, null, undefined, через formatTime
- **formatDuration**: минуты, часы, 1ч ровно, секунды игнорируются
- **formatFileSize**: 0/null/undefined → "--", Б, КБ, МБ, ГБ, cap юнитов

### E2E (~20 тестов)
- **smoke**: title, header, nav-links, footer, view-root
- **navigation**: клик по вкладкам, active class, только одна активная
- **create-protocol**: форма, поля, date today, submit без файла → нет API вызова, URL-таб, submit с файлом → multipart POST, progress
- **list-protocols**: загрузка без ошибок, мок-данные, empty state, error fallback
- **screenshot-button**: страница протокола, вкладка скриншотов, кнопка видна, select strategies, max=10, click → POST /synthesize

## Helpers (tests/setup.js)

Глобальные моки, доступные через `import { ... } from './setup.js'`:

```js
import {
    createMockResponse,    // Response-like объект
    createMockProtocol,    // { id, title, date, status, ... }
    createMockUtterance,   // { id, text, speaker_id, start_sec, ... }
    createMockSpeaker,     // { id, display_name, ... }
    mockFetchSequence,     // несколько ответов подряд
    mockFetchUrl,          // один ответ для конкретного URL
} from '@tests/setup.js';
```

Пример:

```js
import { createMockProtocol, mockFetchSequence } from '@tests/setup.js';

global.fetch = jest.fn();
mockFetchSequence([
    { body: createMockProtocol({ title: 'Test' }) },
    { body: [] },
]);
```

## Архитектурные решения

### Почему не Jest ESM нативно?

`package.json` имеет `"type": "module"`, но `babel-jest` трансформирует `src/js/*.js` из ESM в CJS для совместимости с jest-environment-jsdom (без --experimental-vm-modules). Это упрощает моки и не требует отдельной конфигурации.

### Почему `tests/_helpers/format.js`?

`formatTime`, `formatDuration`, `formatFileSize` — приватные функции в `src/js/views/protocol.js`. Чтобы тестировать их напрямую (без рендеринга всего UI), мы дублируем их логику в `tests/_helpers/format.js`. Это допустимо: код тривиальный и не имеет побочных эффектов. Если в `src/` добавят export — этот хелпер можно удалить.

### Почему E2E не запускает webServer сам?

По требованию проекта backend и frontend запускаются **вручную** (отдельный серверный процесс с реальными зависимостями — Whisper, PostgreSQL и т.д.). Playwright настроен на `http://127.0.0.1:8080` по умолчанию (можно переопределить через `E2E_BASE_URL`).

### Coverage thresholds

```js
coverageThreshold: {
    global: {
        statements: 25,
        branches: 15,
        functions: 20,
        lines: 25,
    },
}
```

Пороги низкие потому что многие view-файлы содержат много логики рендеринга inline в template strings (не считается statements). Можно поднять когда добавим больше тестов.

## Troubleshooting

### `Cannot find module '@api/client.js'`

`moduleNameMapper` в `jest.config.js` маппит `@api/...` → `src/js/api/...`. Если jest не подхватывает — убедитесь что `jest.config.js` в корне `code/hmp-frontend/`.

### `localStorage is not defined`

`tests/setup.js` инициализирует `localStorage` через `beforeEach` clear. Убедитесь что `setupFiles: ['<rootDir>/tests/setup.js']` присутствует в `jest.config.js`.

### Playwright: `browserType.launch: Executable doesn't exist`

Запустите `npm run test:e2e:install` для установки Chromium.

### Tests timeout на 5xx retry

Backoff: 1s + 2s = 3s. Если тест проверяет 5xx — увеличьте `testTimeout` до 20s (уже сделано для retry-тестов).