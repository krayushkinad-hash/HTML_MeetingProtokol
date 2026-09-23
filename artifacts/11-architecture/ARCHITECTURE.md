# Architecture: HTML_MeetingProtokol

## 1. Метаинформация

| Поле | Значение |
|---|---|
| **Проект** | HTML_MeetingProtokol |
| **Дата** | 2026-09-14 |
| **Версия** | 1.0 |
| **Источники** | VISION.md (Scope IN, §9 Ограничения), NFR.md (12 Quality Goals), DATA_MODEL.md (17 таблиц), API.md (~60 эндпоинтов), PROCESSES.md (4 процесса), SCREEN_FLOW.md (16 экранов), TRACEABILITY.md |
| **Архитектурный стиль** | 2-tier монолит + локальный backend + опциональный Telegram-bot |
| **Среда** | Single-user (desktop + offline) |
| **Cloud strategy** | Local-only для данных, опциональные внешние API (Hermes/GigaChat/Telegram) |
| **Автор** | Алексей Краюшкин |

## 2. Архитектурные цели и принципы

### 2.1. Quality Attributes (из NFR §2)

| Цель | Приоритет | Как реализуется |
|---|---|---|
| **Локальность и приватность (QG-1)** | Critical | Backend на localhost, нет передачи данных во внешние сервисы |
| **RSS ≤4 ГБ (QG-7)** | Critical | Потоковое чтение, chunk ≤8 МБ, мониторинг с автопаузой |
| **WER ≤15% (QG-3)** | High | Whisper Large-v3 + словарь терминов |
| **Latency Live ≤3 сек (QG-5)** | High | WebSocket streaming + Whisper fp16 |
| **Офлайн Astra (QG-8)** | High | IndexedDB + статические файлы |

### 2.2. Архитектурные принципы

1. **Privacy by Design** — данные никогда не покидают машину пользователя (152-ФЗ)
2. **Local First** — приложение работает без сети, синхронизация опциональна
3. **Streaming Everything** — большие файлы обрабатываются потоково, не в памяти
4. **Graceful Degradation** — fallback при недоступности компонентов
5. **KISS / YAGNI** — без over-engineering, single-user приложение не требует микросервисов
6. **Single Worker** — лимит 1 воркер транскрипции (нет параллелизма, нет конкуренции за ресурсы)
7. **Offline-First для просмотра** — Astra Linux работает без сети
8. **Standards Compliance** — DOCX по Краюшкину, JSON по RFC 7807, OpenAPI 3.1

### 2.3. Ограничения

- **152-ФЗ** — данные локально, LLM только через сертифицированные сервисы (GigaChat ФСТЭК) или Hermes
- **OOM** — RSS ≤4 ГБ при обработке 2-часовой записи
- **Astra Linux** — только просмотр, нет транскрипции/AI-фич
- **Single-user** — нет multi-tenancy, нет auth (localhost-only)
- **Контроль ресурсов** — автопауза при 80% RAM, потоковая обработка

## 3. C4 Context (Level 1)

```mermaid
C4Context
    title System Context: HTML_MeetingProtokol

    Person(alexey, "Алексей", "P-01: владелец, обрабатывает протоколы на Windows")
    Person(alexey2, "Алексей (Astra)", "P-02: в командировке, просматривает историю")
    Person(guest, "Гость совещания", "P-03: участник встречи (только чтение)")

    System_Boundary(c1, "HTML_MeetingProtokol") {
        System(hmp_win, "Windows App", "Основное приложение (транскрипция, AI)")
        System(hmp_astra, "Astra App", "Только просмотр (offline)")
        System(bot, "Telegram Bot", "AI-прокси (опционально)")
    }

    System_Ext(telemost, "Яндекс Телемост", "Видеоконференции")
    System_Ext(yadisk, "Яндекс.Диск", "Облачное хранилище")
    System_Ext(gdrive, "Google Drive", "Облачное хранилище")
    System_Ext(mailru, "Mail.ru Cloud", "Облачное хранилище")
    System_Ext(hermes, "Hermes API", "LLM (приоритет)")
    System_Ext(gigachat, "GigaChat API", "LLM (альтернатива, ФСТЭК)")
    System_Ext(telegram, "Telegram Bot API", "Канал уведомлений")

    Rel(alexey, hmp_win, "Загружает файлы, редактирует, экспортирует DOCX")
    Rel(alexey, bot, "/summarize, /actions, /tags", "HTTPS")
    Rel(alexey2, hmp_astra, "Просматривает историю офлайн")
    Rel(guest, hmp_win, "Просматривает свой протокол (только чтение)")

    Rel(hmp_win, telemost, "Live Mode (iframe)", "HTTPS")
    Rel(hmp_win, yadisk, "Скачивает файлы", "HTTPS")
    Rel(hmp_win, gdrive, "Скачивает файлы", "HTTPS")
    Rel(hmp_win, mailru, "Скачивает файлы", "HTTPS")
    Rel(hmp_win, hermes, "LLM-запросы (опционально)", "HTTPS/REST")
    Rel(hmp_win, gigachat, "LLM-запросы (опционально)", "HTTPS/REST")

    Rel(bot, hermes, "LLM-запросы", "HTTPS/REST")
    Rel(bot, gigachat, "LLM-запросы (fallback)", "HTTPS/REST")
    Rel(bot, telegram, "Уведомления", "HTTPS/Webhook")
```

## 4. C4 Container (Level 2)

```mermaid
C4Container
    title Container Diagram: HTML_MeetingProtokol

    Person(alexey, "Алексей", "P-01")

    System_Boundary(c1, "Локальная машина (Windows 11)") {
        Container(frontend, "Frontend", "Vanilla JS + CSS", "UI, IndexedDB кэш")
        Container(backend, "Backend", "FastAPI + Python 3.11+", "REST API + WebSocket")
        Container(whisper, "Whisper", "faster-whisper / large-v3", "Транскрипция (subprocess)")
        Container(pyannote, "pyannote.audio", "3.1+", "Диаризация (Python API)")
        Container(ollama, "Ollama", "0.3+", "Локальная LLM (опционально)")
        ContainerDb(postgres, "PostgreSQL", "15+", "Основная БД")
        ContainerDb(sqlite, "SQLite", "3.40+", "Offline БД (fallback)")
        ContainerDb(idb, "IndexedDB", "Browser API", "Кэш протоколов")
    }

    System_Boundary(c2, "VPS (опционально)") {
        Container(bot, "Telegram Bot", "aiogram 3.x + Python 3.11+", "AI-прокси через Telegram")
    }

    System_Ext(hermes, "Hermes API", "https://api.hermes.com/v1")
    System_Ext(gigachat, "GigaChat API", "https://gigachat.devices.sberbank.ru/api/v1")
    System_Ext(cloud, "Cloud Storage", "Яндекс.Диск / Google Drive / Mail.ru")
    System_Ext(telemost, "Яндекс Телемост", "iframe-интеграция")

    Rel(alexey, frontend, "Использует", "file:// или localhost")
    Rel(frontend, backend, "REST API + WebSocket", "HTTP (localhost:8000)")
    Rel(frontend, idb, "Читает/пишет кэш", "IndexedDB API")

    Rel(backend, postgres, "SQL через SQLAlchemy", "TCP 5432")
    Rel(backend, sqlite, "SQL (offline fallback)", "File I/O")
    Rel(backend, whisper, "Python API / subprocess", "in-process")
    Rel(backend, pyannote, "Python API", "in-process")
    Rel(backend, ollama, "POST /api/generate", "HTTP (localhost:11434)")

    Rel(backend, hermes, "POST /chat/completions", "HTTPS/REST")
    Rel(backend, gigachat, "POST /chat/completions", "HTTPS/REST")
    Rel(backend, cloud, "GET (file download)", "HTTPS Range")
    Rel(frontend, telemost, "iframe (Live Mode)", "HTTPS")

    Rel(bot, hermes, "POST /chat/completions", "HTTPS/REST")
    Rel(bot, gigachat, "POST /chat/completions", "HTTPS/REST")
    Rel(bot, backend, "Опционально: проксирование", "HTTPS")
```

## 5. C4 Component (Level 3)

### 5.1. Backend components (FastAPI)

```mermaid
C4Component
    title Backend Component Diagram: HTML_MeetingProtokol

    Container(whisper, "Whisper", "ML model")
    Container(pyannote, "pyannote", "ML model")
    ContainerDb(postgres, "PostgreSQL", "DB")
    Container_Ext(hermes, "Hermes API", "External")

    Component(api, "API Layer", "FastAPI routers", "HTTP endpoints, валидация Pydantic, auth middleware")
    Component(svc_protocol, "Protocol Service", "Service layer", "CRUD протоколов")
    Component(svc_transcribe, "Transcription Service", "Service layer", "Запуск Whisper, мониторинг RSS, retry")
    Component(svc_diarize, "Diarization Service", "Service layer", "Запуск pyannote, merge с Whisper")
    Component(svc_ai, "AI Service", "Service layer", "Саммари, action items, коррекция")
    Component(svc_export, "Export Service", "Service layer", "DOCX генерация, async tasks")
    Component(svc_bot, "Bot Service", "Telegram bot integration", "Webhook, команды")
    Component(repo_protocol, "Protocol Repository", "Repository", "SQLAlchemy ORM")
    Component(repo_utterance, "Utterance Repository", "Repository", "SQLAlchemy ORM")
    Component(repo_speaker, "Speaker Repository", "Repository", "SQLAlchemy ORM")
    Component(repo_meta, "Meta Repository", "Repository", "Action items, tags, decisions, summary")
    Component(repo_bot, "Bot Repository", "Repository", "API users, commands log")
    Component(llm_client, "LLM Client", "Abstraction", "Hermes / GigaChat / Ollama с fallback")
    Component(monitor, "Resource Monitor", "Background task", "RSS, автопауза при 80% RAM")
    Component(encryption, "Encryption Service", "AES-256-GCM", "Шифрование токенов API-провайдеров")

    Rel(api, svc_protocol, "Uses")
    Rel(api, svc_transcribe, "Uses")
    Rel(api, svc_diarize, "Uses")
    Rel(api, svc_ai, "Uses")
    Rel(api, svc_export, "Uses")
    Rel(api, svc_bot, "Uses")

    Rel(svc_protocol, repo_protocol, "Uses")
    Rel(svc_transcribe, repo_utterance, "Uses")
    Rel(svc_transcribe, monitor, "Reports RSS")
    Rel(svc_transcribe, whisper, "Subprocess")
    Rel(svc_diarize, pyannote, "Python API")
    Rel(svc_diarize, repo_speaker, "Uses")
    Rel(svc_ai, llm_client, "Uses")
    Rel(svc_ai, repo_meta, "Uses")
    Rel(svc_export, repo_protocol, "Reads")
    Rel(svc_export, repo_utterance, "Reads")
    Rel(svc_export, repo_speaker, "Reads")
    Rel(svc_bot, repo_bot, "Uses")
    Rel(svc_bot, llm_client, "Uses")

    Rel(repo_protocol, postgres, "SQL")
    Rel(repo_utterance, postgres, "SQL")
    Rel(repo_speaker, postgres, "SQL")
    Rel(repo_meta, postgres, "SQL")
    Rel(repo_bot, postgres, "SQL")
    Rel(repo_bot, encryption, "Encrypts tokens")

    Rel(llm_client, hermes, "HTTPS/REST")
```

### 5.2. Frontend components (Vanilla JS)

```mermaid
C4Component
    title Frontend Component Diagram

    Component(router, "Router", "Hash-based", "Навигация между экранами")
    Component(view_list, "ListView", "UI", "Список протоколов + фильтры")
    Component(view_calendar, "CalendarView", "UI", "Месяц/неделя/день")
    Component(view_protocol, "ProtocolView", "UI", "Метаданные + табы")
    Component(view_transcript, "TranscriptView", "UI", "Видео + транскрипция + коррекция")
    Component(view_live, "LiveModeView", "UI", "3 панели: видео, чат, скриншоты")
    Component(view_export, "ExportDialog", "UI", "Опции DOCX + прогресс")
    Component(view_settings, "SettingsView", "UI", "Словарь, бот, LLM-провайдер")
    Component(ctrl_upload, "UploadController", "Controller", "Drag-drop, multipart, прогресс")
    Component(ctrl_transcribe, "TranscribeController", "Controller", "Запуск + polling статуса")
    Component(ctrl_ai, "AIController", "Controller", "Саммари / actions / коррекция")
    Component(ctrl_export, "ExportController", "Controller", "Async export + polling")
    Component(ctrl_live, "LiveController", "Controller", "WebSocket, события")
    Component(storage, "Storage", "IndexedDB API", "Кэш протоколов")
    Component(api_client, "API Client", "HTTP", "fetch с retry, X-Correlation-Id")

    Rel(router, view_list, "Mounts")
    Rel(router, view_calendar, "Mounts")
    Rel(router, view_protocol, "Mounts")
    Rel(router, view_transcript, "Mounts")
    Rel(router, view_live, "Mounts")
    Rel(router, view_export, "Mounts")
    Rel(router, view_settings, "Mounts")

    Rel(view_protocol, ctrl_ai, "Uses")
    Rel(view_protocol, ctrl_transcribe, "Uses")
    Rel(view_list, ctrl_upload, "Uses")
    Rel(view_transcript, ctrl_ai, "Uses")
    Rel(view_live, ctrl_live, "Uses")
    Rel(view_export, ctrl_export, "Uses")

    Rel(ctrl_upload, api_client, "Uses")
    Rel(ctrl_transcribe, api_client, "Uses")
    Rel(ctrl_ai, api_client, "Uses")
    Rel(ctrl_export, api_client, "Uses")
    Rel(ctrl_live, api_client, "Uses")

    Rel(api_client, storage, "Кэширует ответы")
    Rel(view_protocol, storage, "Читает кэш (offline)")
    Rel(view_calendar, storage, "Читает кэш (offline)")
```

### 5.3. Telegram Bot components (aiogram 3.x)

```mermaid
C4Component
    title Telegram Bot Component Diagram

    Component_Ext(telegram, "Telegram Bot API", "Webhooks")
    Component_Ext(hermes, "Hermes API", "LLM")
    Component_Ext(gigachat, "GigaChat API", "LLM")
    Container_Ext(backend, "Backend API", "Optional")

    Component(dispatcher, "Dispatcher", "aiogram", "Routing команд")
    Component(cmd_summarize, "/summarize", "Handler", "Саммари через LLM")
    Component(cmd_actions, "/actions", "Handler", "Action items")
    Component(cmd_tags, "/tags", "Handler", "Теги")
    Component(cmd_voice, "Voice Handler", "Handler", "Скачать + Whisper")
    Component(auth, "Auth Middleware", "Whitelist", "Проверка telegram_id")
    Component(notifier, "Notifier", "Background task", "Уведомления о завершении")
    Component(llm_router, "LLM Router", "Abstraction", "Hermes → GigaChat fallback")
    Component(logger, "Logger", "Audit", "Лог команд в БД")
    ComponentDb(bot_db, "Bot DB", "PostgreSQL/SQLite", "Users, command log")

    Rel(telegram, dispatcher, "Webhook")
    Rel(dispatcher, auth, "Filter")
    Rel(dispatcher, cmd_summarize, "Routes")
    Rel(dispatcher, cmd_actions, "Routes")
    Rel(dispatcher, cmd_tags, "Routes")
    Rel(dispatcher, cmd_voice, "Routes")
    Rel(auth, bot_db, "Check whitelist")
    Rel(cmd_summarize, llm_router, "Uses")
    Rel(cmd_actions, llm_router, "Uses")
    Rel(llm_router, hermes, "HTTPS")
    Rel(llm_router, gigachat, "Fallback")
    Rel(cmd_summarize, logger, "Logs")
    Rel(notifier, telegram, "Sends")
    Rel(notifier, backend, "Optional: polling")
```

## 6. Sequence Diagrams (ключевые сценарии)

### 6.1. Загрузка файла + транскрипция

```mermaid
sequenceDiagram
    autonumber
    actor U as Алексей (P-01)
    participant FE as Frontend
    participant API as Backend
    participant DB as PostgreSQL
    participant FS as Filesystem
    participant WS as Whisper
    participant PY as pyannote

    U->>FE: 1. Drag-n-drop meeting.mp4
    FE->>API: 2. POST /protocols (multipart, chunk ≤8 MB)
    API->>FS: 3. Stream save to ~/.html_mp/protocols/<id>/
    API->>DB: 4. BEGIN TXN; INSERT protocol, audio_file; COMMIT
    API-->>FE: 5. 201 Created {protocol_id, status: "loaded"}

    U->>FE: 6. Click "Запустить транскрипцию"
    FE->>API: 7. POST /transcribe/run {protocol_id}
    API->>DB: 8. INSERT transcribe_task (status=queued)
    API->>WS: 9. model.transcribe() порциями 30 сек

    loop Для каждой порции (n × 30 сек)
        WS->>WS: 10. Распознавание (fp16, beam_size=1)
        WS-->>API: 11. Segments {start, end, text, confidence}
        API->>API: 12. Проверка RSS; если >80% → pause
        API->>DB: 13. BATCH INSERT utterance
    end

    WS-->>API: 14. Готово; wer_quality = 12.3%
    API->>DB: 15. UPDATE protocol.wer_quality, status
    API->>PY: 16. pyannote diarize()
    PY-->>API: 17. DiarizationResult {speakers, segments, der}
    API->>DB: 18. INSERT speaker, UPDATE utterance.speaker_id
    API->>DB: 19. UPDATE protocol.status = 'ready'
    API-->>FE: 20. 200 OK {wer, der, duration}

    FE->>FE: 21. Toast "Готово!"
    U->>FE: 22. Открывает ProtocolView
```

### 6.2. Live Mode (Яндекс Телемост)

```mermaid
sequenceDiagram
    autonumber
    actor U as Алексей
    participant FE as Frontend
    participant API as Backend
    participant WS as Whisper
    participant PY as pyannote
    participant TM as Яндекс Телемост (iframe)
    participant FS as Filesystem

    U->>FE: 1. Click "Начать Live Mode"
    FE->>API: 2. POST /live/start {telemost_url}
    API->>DB: 3. INSERT protocol (status=live)
    API-->>FE: 4. {protocol_id, websocket_url, telemost_iframe_url}

    FE->>TM: 5. iframe load
    FE->>API: 6. WebSocket connect /live/{id}/stream

    par Захват аудио (Electron)
        API->>API: 7. Audio capture from iframe (Web Audio API)
        API->>WS: 8. Streaming recognition (10 сек chunks)
    and Захват экрана
        loop Каждые 60 сек
            API->>FS: 9. Screenshot via Canvas API
            API->>FS: 10. Save screenshot.png
            API->>API: 11. WebSocket send {event: "screenshot"}
        end
    end

    WS-->>API: 12. Utterance {start, end, text, speaker}
    API->>PY: 13. Online diarization
    PY-->>API: 14. speaker_label
    API->>API: 15. WebSocket send {event: "utterance"}
    FE-->>U: 16. Появляется реплика в реальном времени

    U->>FE: 17. Click "Завершить встречу"
    FE->>API: 18. POST /live/{id}/stop
    API->>API: 19. Flush buffer, finalize transcript
    API->>DB: 20. UPDATE protocol.status='loaded'
    API-->>FE: 21. {summary: "saved as N utterances"}
```

### 6.3. Telegram-бот /summarize

```mermaid
sequenceDiagram
    autonumber
    actor U as Алексей в Telegram
    participant TG as Telegram Bot (VPS)
    participant BL as Backend (опционально)
    participant H as Hermes API
    participant G as GigaChat API
    participant TDB as Bot DB

    U->>TG: 1. /summarize 550e8400-...
    TG->>TG: 2. Auth Middleware: telegram_id == whitelist?
    TG->>TDB: 3. INSERT command_log (status=pending)
    TG-->>U: 4. ⏳ Обрабатываю протокол...

    alt Backend доступен
        TG->>BL: 5. POST /ai/summarize {protocol_id, provider="hermes"}
        BL->>BL: 6. Собрать текст из utterances
        BL->>H: 7. POST /chat/completions
        alt Hermes OK
            H-->>BL: 8. summary_text
        else Hermes fail
            BL->>G: 9. POST /chat/completions (fallback)
            G-->>BL: 10. summary_text
        end
        BL-->>TG: 11. {summary_text}
    else Backend недоступен
        TG->>H: 12. Прямой вызов (с предзагруженным протоколом)
        H-->>TG: 13. summary_text
    end

    TG->>TDB: 14. UPDATE command_log (status=success, tokens=X)
    TG-->>U: 15. 📋 Саммари встречи 14.09: ...
```

### 6.4. Экспорт DOCX (async)

```mermaid
sequenceDiagram
    autonumber
    actor U as Алексей
    participant FE as Frontend
    participant API as Backend
    participant DB as PostgreSQL
    participant FS as Filesystem

    U->>FE: 1. Click "Экспорт DOCX"
    FE->>API: 2. POST /export/docx {protocol_id, options}
    API->>DB: 3. INSERT export_task (status=queued, progress=0)
    API-->>FE: 4. 202 Accepted {task_id}

    par Async worker
        API->>DB: 5. UPDATE status='processing', progress=10
        API->>DB: 6. SELECT utterances, speakers, screenshots
        API->>FS: 7. Запись во временный .docx (python-docx)
        API->>API: 8. Построение заголовков, таймкодов, гиперссылок
        API->>API: 9. Встраивание скриншотов (PIL, resize)
        API->>DB: 10. UPDATE progress=50, 80, 100
        API->>FS: 11. Move to final path
        API->>DB: 12. UPDATE status='completed', file_size=...
    end

    loop Polling каждые 2 сек
        FE->>API: 13. GET /export/status/{task_id}
        API-->>FE: 14. {status, progress_percent}
        FE->>FE: 15. UI: progress bar обновляется
    end

    alt Успех
        FE->>API: 16. GET /export/download/{task_id}
        API-->>FE: 17. DOCX binary (Content-Disposition)
        FE->>FE: 18. Browser save dialog
    else Ошибка
        API-->>FE: 19. {status: "failed", error_message: "..."}
        FE-->>U: 20. Toast "Ошибка экспорта, попробуйте снова"
    end
```

### 6.5. Офлайн-просмотр в Astra Linux

```mermaid
sequenceDiagram
    autonumber
    actor U as Алексей (Astra, офлайн)
    participant FE as Frontend (статика)
    participant IDB as IndexedDB
    participant BG as Background Sync

    Note over U,BG: До поездки (на Windows, онлайн)
    U->>FE: 1. Открывает Calendar
    FE->>BG: 2. Service Worker: загрузить все протоколы в кэш
    BG->>FE: 3. IndexedDB write (batch по 50 протоколов)
    FE->>BG: 4. Cache static assets (JS, CSS, Mermaid.js)
    Note over U,BG: В поездке (Astra, офлайн)

    U->>FE: 5. Открывает Calendar
    FE->>IDB: 6. SELECT * FROM protocols (local)
    IDB-->>FE: 7. Список 200 протоколов (<500 мс)
    FE->>U: 8. Отображение календаря

    U->>FE: 9. Открывает протокол от 14.09
    FE->>IDB: 10. SELECT utterances WHERE protocol_id=...
    IDB-->>FE: 11. Реплики + спикеры
    FE->>IDB: 12. SELECT video_url (file:// or blob:)
    FE-->>U: 13. Видео + транскрипция

    U->>FE: 14. Поиск "бюджет"
    FE->>IDB: 15. WHERE text LIKE '%бюджет%'
    IDB-->>FE: 16. Результаты
    FE-->>U: 17. Подсвеченные реплики

    Note over U,BG: Попытка загрузить новый файл
    FE->>FE: 18. Network offline → вкладка "По ссылке" недоступна
    FE-->>U: 19. Tooltip "Требуется интернет"
```

## 7. Deployment Diagram

```mermaid
graph TB
    subgraph Win["🪟 Windows 11 (основная, полный функционал)"]
        Browser["Browser / Electron<br/>Frontend (localhost)"]
        FastAPI["FastAPI<br/>Backend :8000"]
        Whisper["Whisper Large-v3<br/>faster-whisper"]
        Pyannote["pyannote.audio 3.1"]
        Ollama["Ollama<br/>:11434 (опционально)"]
        Postgres[("PostgreSQL 15<br/>:5432<br/>(или SQLite)")]
        AudioFiles[("~/.html_mp/protocols/<id>/<br/>audio/video/screenshots")]
    end

    subgraph Astra["🐧 Astra Linux (только просмотр, офлайн)"]
        BrowserAstra["Browser<br/>(только статика)"]
        IDB[("IndexedDB<br/>кэш протоколов")]
        VideoFiles[("Видео + DOCX<br/>скопированы заранее")]
    end

    subgraph VPS["☁️ VPS (опционально, для бота)"]
        Bot["Telegram Bot<br/>aiogram 3.x<br/>Python 3.11+"]
        BotDB[("SQLite<br/>(не критично)")]
    end

    subgraph Cloud["☁️ Cloud (внешние сервисы)"]
        Yandex["Яндекс.Диск"]
        Google["Google Drive"]
        Mail["Mail.ru Cloud"]
        Telemost["Яндекс Телемост<br/>(iframe)"]
        Hermes["Hermes API<br/>https://api.hermes.com/v1"]
        GigaChat["GigaChat API<br/>(ФСТЭК)"]
        Telegram["Telegram Bot API"]
    end

    subgraph "Локальная сеть (Windows)"
        Browser -.->|"localhost:8000"| FastAPI
        FastAPI --> Postgres
        FastAPI --> Whisper
        FastAPI --> Pyannote
        FastAPI --> Ollama
        FastAPI --> AudioFiles
    end

    Browser -.->|"iframe"| Telemost
    FastAPI ==>|"HTTPS (chunked)"| Yandex
    FastAPI ==>|"HTTPS (chunked)"| Google
    FastAPI ==>|"HTTPS (chunked)"| Mail
    FastAPI ==>|"HTTPS /chat/completions"| Hermes
    FastAPI ==>|"HTTPS /chat/completions"| GigaChat

    BrowserAstra -.->|"кэш"| IDB
    BrowserAstra -.->|"file:// или blob:"| VideoFiles

    Bot ==>|"HTTPS /chat/completions"| Hermes
    Bot ==>|"HTTPS /chat/completions"| GigaChat
    Bot ==>|"HTTPS webhook"| Telegram
    Bot --> BotDB

    Bot -.->|"опционально"| FastAPI
```

## 8. Network Diagram

| Порт | Сервис | Bind | Доступ | Протокол |
|---|---|---|---|---|
| **8000** | FastAPI Backend | 127.0.0.1 only | localhost | HTTP/REST + WebSocket |
| **5432** | PostgreSQL | 127.0.0.1 only | localhost | TCP (PostgreSQL wire) |
| **11434** | Ollama | 127.0.0.1 only | localhost | HTTP/REST |
| **443** | HTTPS (outbound) | — | Internet | HTTPS (Hermes, GigaChat, Telegram, cloud) |

### Firewall rules

| Direction | Source | Destination | Port | Protocol | Allowed |
|---|---|---|---|---|---|
| Inbound | Localhost | 127.0.0.1 | 8000 | TCP | ✅ (для frontend) |
| Inbound | Localhost | 127.0.0.1 | 5432 | TCP | ✅ (для backend) |
| Inbound | Localhost | 127.0.0.1 | 11434 | TCP | ✅ (для Ollama) |
| Outbound | 127.0.0.1 | hermes.com | 443 | HTTPS | ✅ (для LLM) |
| Outbound | 127.0.0.1 | gigachat.devices.sberbank.ru | 443 | HTTPS | ✅ (для LLM) |
| Outbound | 127.0.0.1 | api.telegram.org | 443 | HTTPS | ✅ (для бота) |
| Outbound | 127.0.0.1 | cloud-api.yandex.net | 443 | HTTPS | ✅ (для загрузки) |
| Outbound | 127.0.0.1 | www.googleapis.com | 443 | HTTPS | ✅ (для загрузки) |
| Outbound | 127.0.0.1 | cloud.mail.ru | 443 | HTTPS | ✅ (для загрузки) |
| Outbound | 127.0.0.1 | telemost.yandex.ru | 443 | HTTPS | ✅ (для Live Mode) |
| **Inbound from Internet** | **Любой** | **Локальная машина** | **Любой** | — | **❌ ЗАБЛОКИРОВАНО** |

## 9. Технологический стек

| Слой | Технология | Версия | Обоснование |
|---|---|---|---|
| **Frontend** | Vanilla JS + CSS | ES2022 | Нет фреймворков — кросс-платформенность без зависимостей |
| **Модули Frontend** | ES modules | — | Нативная поддержка браузерами |
| **Хранилище Frontend** | IndexedDB | API 3.0 | Офлайн-кэш, до 50% диска |
| **Backend** | Python | 3.11+ | LTS, async, typing |
| **Web framework** | FastAPI | 0.110+ | Async, OpenAPI auto-gen, Pydantic |
| **ASGI server** | Uvicorn | 0.27+ | Production-ready, HTTP/2 |
| **ORM** | SQLAlchemy | 2.x | Async, type-safe |
| **Migrations** | Alembic | 1.13+ | Standard для SQLAlchemy |
| **DB (online)** | PostgreSQL | 15+ | JSONB, GIN-индексы, partial index |
| **DB (offline)** | SQLite | 3.40+ | Fallback для Astra Linux |
| **Транскрипция** | faster-whisper | 1.0+ | CTranslate2, в 4× быстрее openai-whisper |
| **Модель транскрипции** | Whisper | large-v3 | Лучшее качество для русского (WER ≤15%) |
| **Диаризация** | pyannote.audio | 3.1+ | DER ≤20%, SOTA для 2-10 ораторов |
| **LLM (опционально локально)** | Ollama + llama.cpp | 0.3+ | Локально, без облака |
| **LLM (приоритет)** | Hermes API | API текущая | Гибкость, поддержка экспериментов |
| **LLM (альтернатива)** | GigaChat | API 2024-09 | ФСТЭК сертифицирован |
| **Telegram Bot** | aiogram | 3.x | Async, современный |
| **Embedding** | sentence-transformers | 2.2+ | Локально, multilingual |
| **DOCX** | python-docx | 1.1+ | Стандарт де-факто |
| **Мониторинг ресурсов** | psutil | 5.9+ | Кросс-платформенный |
| **HTTP клиент (Python)** | httpx | 0.27+ | Async, HTTP/2 |
| **Безопасность (AES)** | cryptography | 42+ | Лидер по безопасности |
| **Логирование** | structlog | 24+ | Структурированные JSON-логи |
| **Тестирование** | pytest | 8+ | Стандарт |
| **Load-тесты** | k6 | latest | JavaScript, но работает с любым API |
| **Mermaid рендер** | Playwright + Chromium | latest | Для PNG-диаграмм в DOCX |
| **Browser automation** | Playwright | latest | Для скриншотов UI в DOCX |

## 10. ADR (Architecture Decision Records)

### ADR-001: FastAPI вместо Django

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Нужен backend для локального single-user приложения с REST API + WebSocket.
**Решение:** FastAPI 0.110+.
**Альтернативы:**
- **Django + DRF** — слишком тяжёлый, ORM не async, админка не нужна для single-user
- **Flask** — нет async, нет OpenAPI из коробки
- **aiohttp** — низкоуровневый, нет OpenAPI
**Последствия:**
- ✅ Async из коробки (нужно для WebSocket Live Mode)
- ✅ Pydantic для валидации (RFC 7807 ready)
- ✅ Авто-генерация OpenAPI 3.1
- ⚠️ Молодая экосистема (но достаточно зрелая)
**Связь:** API.md, NFR §3.1 (latency targets)

### ADR-002: PostgreSQL 15 как основная БД

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Хранение протоколов, реплик, метаданных. Нужны JSONB, GIN-индексы для полнотекстового поиска.
**Решение:** PostgreSQL 15 + JSONB + GIN для `to_tsvector('russian', text)`.
**Альтернативы:**
- **MongoDB** — избыточно для реляционных данных, нет FTS из коробки для русского
- **SQLite** — нет параллельных воркеров, нет JSONB
- **MySQL** — нет нормального JSONB, нет FTS для русского
**Последствия:**
- ✅ Полнотекстовый поиск на русском (`to_tsvector('russian', text)`)
- ✅ UUID как PK из коробки
- ✅ Partial indexes для оптимизации
- ⚠️ Нужен systemd для авто-запуска
**Связь:** DATA_MODEL.md §17 (таблицы), NFR §6.1

### ADR-003: Vanilla JS без React/Vue

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Frontend для кросс-платформенного приложения (Windows + Astra Linux).
**Решение:** Vanilla JS + ES modules + IndexedDB.
**Альтернативы:**
- **React + Webpack** — тяжёлый bundle, нужен build-шаг
- **Vue** — чуть легче, но всё равно нужен build
- **Svelte** — компилируется в vanilla JS, но добавляет зависимость
**Последствия:**
- ✅ Bundle < 300 КБ (без Webpack/Vite)
- ✅ Работает в file:// без сервера (Astra офлайн)
- ✅ Нет npm install на чужой машине
- ⚠️ Больше boilerplate-кода
**Связь:** NFR §3.2 (Frontend Performance Budget), NFR §7 (Cross-platform)

### ADR-004: Hermes как приоритетный LLM

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** AI-фичи (саммари, action items, коррекция текста) через LLM.
**Решение:** **Hermes — приоритет**, GigaChat — fallback.
**Альтернативы:**
- **Только GigaChat** — российский, ФСТЭК, но менее гибкий
- **Только локальная Ollama** — слабое железо, медленно
- **OpenAI** — нет 152-ФЗ compliant
**Последствия:**
- ✅ Hermes — гибкий, поддержка экспериментов
- ✅ GigaChat — сертифицирован ФСТЭК (для критичных данных)
- ✅ Автопереключение через `/set_provider` команду в боте
- ⚠️ Два провайдера — больше кода в `LLM Client`
**Связь:** VISION §7.1 (Telegram-бот), API.md §4.7

### ADR-005: Faster-Whisper вместо OpenAI-Whisper

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Транскрипция аудио/видео файлов до 2 часов.
**Решение:** `faster-whisper` (CTranslate2-based) с моделью `large-v3`.
**Альтернативы:**
- **openai-whisper** — медленнее в 4×, больше памяти
- **Vosk** — легче, но WER 20-25% (хуже для русского)
- **Yandex SpeechKit** — нарушает "локальность" (по умолчанию)
**Последствия:**
- ✅ В 4× быстрее (1 час аудио за 5-10 мин)
- ✅ На 40% меньше памяти (fp16, beam_size=1)
- ⚠️ Модель 3 ГБ — нужен диск
**Связь:** NFR §3 (Performance), DATA_MODEL §4.2 (audio_file)

### ADR-006: IndexedDB для офлайн-кэша (Astra Linux)

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Просмотр истории протоколов в Astra Linux без интернета.
**Решение:** IndexedDB + Service Worker для кэширования статики.
**Альтернативы:**
- **LocalStorage** — лимит ~5 МБ, синхронный API
- **Прямой файл SQLite через WASM** — сложнее, нужен WASM-loader
- **Только Postgres через network** — не работает офлайн
**Последствия:**
- ✅ До 50% диска (лимит браузера)
- ✅ Асинхронный API
- ✅ Поддержка индексов для быстрого поиска
- ⚠️ Квота может быть ограничена браузером
**Связь:** NFR §QG-8 (Astra офлайн), SCREEN_FLOW §F-HMP-3

### ADR-007: Локальный backend (не Electron-встроенный)

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Backend (FastAPI + Whisper + pyannote) должен работать на той же машине, что и frontend.
**Решение:** **Отдельный процесс** FastAPI на `localhost:8000` + frontend в браузере/Electron.
**Альтернативы:**
- **Electron с встроенным Python** — сложная сборка, pyinstaller + electron-builder
- **WebAssembly Whisper** — медленно, нет pyannote
- **Только CLI** — неудобно для не-разработчика
**Последствия:**
- ✅ Чёткое разделение frontend/backend
- ✅ Backend можно перезапустить независимо
- ✅ Простая отладка (curl + логи)
- ⚠️ Два процесса для пользователя (но через .bat/.sh автозапуск)
**Связь:** §3 (C4 Context), NFR §7 (Cross-platform)

### ADR-008: Потоковое чтение файлов (chunk ≤8 МБ)

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Загрузка файлов до 10 ГБ не должна съедать RAM.
**Решение:** Multipart streaming на upload + чтение по 8 МБ чанкам.
**Альтернативы:**
- **read-to-memory** — OOM на 10 ГБ файле
- **TUS protocol** — overkill для local
- **WebSocket upload** — медленнее HTTP multipart
**Последствия:**
- ✅ Постоянное потребление RAM ≤10 МБ
- ✅ Совместимо со всеми HTTP-клиентами
- ⚠️ Нужна обработка partial writes (но решаемо через tempfile)
**Связь:** NFR §QG-7 (RSS ≤4 ГБ), VISION §9 (Ограничения)

### ADR-009: Один воркер транскрипции

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** На одной машине — одна GPU, один CPU-набор. Параллелизм снижает throughput из-за contention.
**Решение:** **1 воркер** через очередь задач (например, `asyncio.Queue` или Celery + Redis).
**Альтернативы:**
- **Параллельные воркеры** — конкуренция за GPU, OOM
- **Multiprocessing** — overhead на IPC
- **GPU sharing через MPS** — нет поддержки в Whisper
**Последствия:**
- ✅ Предсказуемое потребление памяти
- ✅ Нет race condition на ресурсах
- ⚠️ Если несколько пользователей — нужен scheduler
**Связь:** NFR §QG-7, VISION §9

### ADR-010: Мониторинг RSS с автопаузой

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Whisper Large-v3 может съесть всю RAM при длинных записях.
**Решение:** Background task с `psutil.Process.memory_info().rss` каждые 5 сек. При >80% RAM → pause + уведомление пользователю.
**Альтернативы:**
- **cgroups memory limit** — только Linux
- **Windows Job Objects** — не работает для кросс-платформы
- **Memory-mapped файлы** — Whisper не поддерживает
**Последствия:**
- ✅ Кросс-платформенный механизм
- ✅ Пользователь может закрыть другие приложения
- ⚠️ Pause замедляет обработку
**Связь:** NFR §QG-7

### ADR-011: python-docx + кастомные стили (Краюшкин)

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** DOCX-экспорт должен соответствовать ГОСТ-стилю Алексея.
**Решение:** `python-docx` с ручной настройкой: TNR 12, поля 20/10/10/10, заголовки 16/14/12.
**Альтернативы:**
- **docxtpl** — нужен шаблон, не подходит для динамического контента
- **pandoc** — не контролирует стили на 100%
- **HTML → DOCX через LibreOffice** — тяжёлый, нужен LibreOffice
**Последствия:**
- ✅ Полный контроль над стилями
- ✅ Кросс-платформенно
- ⚠️ Много boilerplate-кода (но уже решено в `scripts/render_*.py`)
**Связь:** VISION §7.1 (DOCX), FORM_EXPORT_DIALOG §F-HMP-5

### ADR-012: Telegram Bot как опциональный компонент

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Нужен ли Telegram-бот для мобильного доступа.
**Решение:** **Опционально**, разворачивается на VPS (отдельный от основного приложения).
**Альтернативы:**
- **Встроить в desktop** — нет смысла, не мобильно
- **PWA с push-уведомлениями** — нужна инфраструктура
- **Не делать** — упускаем мобильный сценарий
**Последствия:**
- ✅ Мобильный доступ к AI-фичам
- ✅ Не блокирует основной MVP
- ✅ Минимальная стоимость ($3-5/мес VPS)
- ⚠️ Нужно поддерживать отдельный сервис
**Связь:** VISION §7.1 (Telegram-бот), EPIC-TELEGRAM

### ADR-013: Whitelist по telegram_id для бота

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Бот должен принимать команды только от Алексея.
**Решение:** Whitelist по `telegram_id` в таблице `api_user`.
**Альтернативы:**
- **Логин/пароль** — неудобно для мобильного сценария
- **OAuth через Telegram Login Widget** — overkill
- **Без auth** — небезопасно
**Последствия:**
- ✅ Простая авторизация для одного пользователя
- ✅ Audit trail через `command_log`
- ⚠️ Если утерян доступ к Telegram — нужно переустановить whitelist
**Связь:** DATA_MODEL §4.14 (api_user), API.md §4.17

### ADR-014: Шифрование токенов LLM-провайдеров (AES-256-GCM)

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Токены Hermes/GigaChat/Telegram не должны попасть в логи.
**Решение:** AES-256-GCM с мастер-ключом из `.env`.
**Альтернативы:**
- **Открытый текст** — риск утечки в логи/бэкапы
- **Хэширование** — нельзя расшифровать для использования
- **Vault (HashiCorp)** — overkill для single-user
**Последствия:**
- ✅ Токены зашифрованы в БД
- ✅ Логи содержат только метаданные (last 4 chars)
- ⚠️ Если утерян .env — нужно переустановить токены
**Связь:** DATA_MODEL §4.14 (api_user), NFR §6.4

### ADR-015: WebSocket для Live Mode (не polling)

**Дата:** 2026-09-14
**Статус:** Accepted
**Контекст:** Live Mode требует latency ≤3 сек для реплик.
**Решение:** WebSocket `/live/{id}/stream` с bidirectional events.
**Альтернативы:**
- **HTTP polling каждые 1 сек** — 60× больше запросов, выше latency
- **Server-Sent Events (SSE)** — не поддерживает client→server events
- **gRPC streaming** — overkill для local
**Последствия:**
- ✅ Latency ≤1 сек (WebSocket быстрее)
- ✅ Меньше нагрузки на сервер (1 соединение)
- ⚠️ Нужна обработка reconnect на стороне клиента
**Связь:** NFR §QG-5, API.md §4.16

## 11. Протоколы обмена данными

### 11.1. HTTP/REST (Frontend ↔ Backend)

| Параметр | Значение |
|---|---|
| **Base URL** | `http://localhost:8000/api/v1/hmp` |
| **Content-Type** | `application/json` (default), `multipart/form-data` (upload) |
| **Authentication** | None (localhost-only) |
| **Формат ошибок** | RFC 7807 (Problem Details) |
| **Заголовки** | `X-Correlation-Id` (UUID, пробрасывается), `Content-Type`, `Accept-Language: ru-RU` |
| **Пагинация** | `?page=1&limit=50` (offset), `?cursor=...` (cursor) |
| **Сортировка** | `?sort=-date,title` (multi-field, `-` DESC) |
| **Фильтрация** | `?filter[status]=ready&filter[date_from]=2026-01-01` |
| **Идемпотентность** | `Idempotency-Key: <uuid>` для POST/PATCH/DELETE |
| **Timeout** | 30 сек (синхронные), 60 сек (AI), 30 мин (транскрипция) |
| **Rate limit** | 100 req/min (на пользователя, для бота) |
| **Compression** | gzip (Content-Encoding: gzip) |

### 11.2. WebSocket (Live Mode)

| Параметр | Значение |
|---|---|
| **URL** | `ws://localhost:8000/api/v1/hmp/live/{protocol_id}/stream` |
| **Subprotocol** | `hmp-v1` |
| **Heartbeat** | каждые 30 сек (ping/pong frames) |
| **Reconnect** | экспоненциальный backoff (1с, 2с, 4с, 8с, max 30с) |
| **Сообщения** | JSON `{event: "utterance"|"screenshot"|"speaker_change", data: {...}, timestamp: "..."}` |
| **Размер сообщения** | ≤16 КБ (для скриншотов используется HTTP) |
| **Auth** | None (localhost), но проверка `protocol_id` существует |

### 11.3. Telegram Bot API

| Параметр | Значение |
|---|---|
| **Mode** | Webhook (на VPS) — `https://bot.example.com/webhook` |
| **Webhook secret** | 32-64 символа, проверка `X-Telegram-Bot-Api-Secret-Token` |
| **Polling mode** | Только для разработки (long polling) |
| **Команды** | `/summarize`, `/actions`, `/tags`, `/list`, `/search`, `/help` |
| **Файлы** | Скачивание через `getFile` (≤20 МБ), для большего — HTTP Range |
| **Inline mode** | Не используется |
| **Retry** | 3 раза с exponential backoff |

### 11.4. LLM API (Hermes / GigaChat)

| Параметр | Hermes | GigaChat |
|---|---|---|
| **URL** | `https://api.hermes.com/v1/chat/completions` | `https://gigachat.devices.sberbank.ru/api/v1/chat/completions` |
| **Auth** | `Authorization: Bearer <api_key>` | `Authorization: Bearer <oauth_token>` |
| **Content-Type** | `application/json` | `application/json` |
| **Max tokens** | 4096 | 4096 |
| **Temperature** | 0.3 (для саммари — детерминированно) | 0.3 |
| **Timeout** | 30 сек | 30 сек |
| **Retry** | 3 раза | 3 раза |
| **Streaming** | Server-Sent Events (`stream: true`) | Аналогично |

### 11.5. PostgreSQL (SQLAlchemy)

| Параметр | Значение |
|---|---|
| **Connection string** | `postgresql+asyncpg://user:pass@localhost:5432/html_mp` |
| **Pool size** | 10 |
| **Max overflow** | 20 |
| **Pool timeout** | 30 сек |
| **Statement timeout** | 60 сек |
| **Connection timeout** | 10 сек |

### 11.6. Multipart upload (файлы)

| Параметр | Значение |
|---|---|
| **Max file size** | 10 ГБ |
| **Max request size** | 10 ГБ |
| **Chunk size** | 8 МБ |
| **Allowed MIME** | `audio/mpeg`, `audio/wav`, `video/mp4`, `video/x-matroska`, `audio/ogg`, `audio/flac`, `audio/mp4` |
| **Streaming** | Обязательно для файлов >100 МБ |
| **Resume** | HTTP Range при ошибке |

## 12. Схема базы данных

См. **DATA_MODEL.md §2** для полной ER-диаграммы.

**17 таблиц, 22+ FK-связи, 56 индексов, 14 ENUM-типов, GIN-индекс для русского полнотекстового поиска.**

## 13. Observability Stack

### 13.1. Метрики

| Метрика | Тип | Где собирается |
|---|---|---|
| `transcription_duration_sec` | Histogram | Backend, после обработки |
| `transcription_wer` | Gauge | Backend, при завершении |
| `diarization_der` | Gauge | Backend, при завершении |
| `peak_rss_mb` | Gauge | Backend, во время обработки |
| `db_query_latency_ms` | Histogram | SQLAlchemy middleware |
| `llm_tokens_used` | Counter | Backend + Bot |
| `oom_pauses_total` | Counter | Backend |
| `http_requests_total` | Counter | Backend, по эндпоинтам |

**Формат:** Prometheus text format (если подключён), иначе JSON-логи.

### 13.2. Логи

| Уровень | Формат | Где |
|---|---|---|
| INFO | `{"timestamp":"...","level":"info","correlation_id":"...","method":"POST","path":"...","status":201,"duration_ms":145}` | Backend stdout |
| WARNING | То же + `{"reason":"..."}` | Backend stdout |
| ERROR | То же + `{"error":"...","stack_trace":"..."}` | Backend stdout |

**Ротация:** logrotate, 7 дней локально.

**Чувствительные данные НЕ логируются:**
- Токены API (только длина + last 4 chars)
- Telegram ID пользователей (только в whitelist-логах)
- Содержимое файлов

### 13.3. Трассировка

- **X-Correlation-Id** пробрасывается через все запросы и ответы
- В логах присутствует поле `correlation_id` для поиска end-to-end
- Готовность к OpenTelemetry (если потребуется)

### 13.4. Health checks

| Endpoint | Назначение |
|---|---|
| `GET /health` | Простой — возвращает 200 OK |
| `GET /health/deep` | Проверяет БД, модели, диск, RSS |

## 14. Безопасность (Security Architecture)

### 14.1. Perimeter

| Уровень | Защита |
|---|---|
| **Network** | Backend только на `127.0.0.1`, файрвол блокирует входящие из Internet |
| **Application** | Single-user, нет remote access |
| **Per-tenant** | N/A (single-user) |
| **Telegram bot** | Whitelist по telegram_id |

### 14.2. Аутентификация

| Канал | Механизм |
|---|---|
| **Local backend** | Нет (localhost only) |
| **Telegram bot** | Whitelist telegram_id в `api_user` |
| **HTTPS cloud** | Нет (публичные URL, но для скачивания, не для записи) |
| **HTTPS LLM** | Bearer token (зашифрован в БД) |

### 14.3. Авторизация (RBAC)

| Роль | Права |
|---|---|
| **Admin (Алексей)** | Полный доступ ко всем эндпоинтам |
| **Telegram User (whitelisted)** | Команды бота |
| **Telegram User (non-whitelisted)** | 403 Forbidden |
| **Network (anyone)** | 127.0.0.1 only |

### 14.4. Шифрование

| Канал | Алгоритм | Где |
|---|---|---|
| **At rest (local files)** | Опционально AES-256 (v2) | ~/.html_mp/protocols/ |
| **At rest (DB tokens)** | AES-256-GCM | api_user.tokens_* |
| **At rest (DB sensitive)** | Опционально (v2) | — |
| **In transit (external)** | TLS 1.3 | Hermes, GigaChat, Telegram, cloud |
| **In transit (internal)** | Нет (localhost) | — |

### 14.5. Threat Model (STRIDE)

| Угроза | Уровень | Митигация |
|---|---|---|
| **S**poofing (подмена пользователя) | Низкий | Whitelist для бота, localhost для backend |
| **T**ampering (изменение данных) | Средний | Backup-стратегия, checksum для файлов |
| **R**epudiation (отказ от действий) | Средний | Audit log в `command_log` |
| **I**nformation Disclosure | Средний | Шифрование токенов, нет логирования PII |
| **D**enial of Service | Низкий | Single-user, лимиты на размер файлов |
| **E**levation of Privilege | Низкий | Whitelist для бота |

### 14.6. OWASP API Top 10 (2023)

См. API.md §5.6 — все 10 пунктов закрыты.

### 14.7. Аудит

- Все команды бота логируются в `command_log`
- Все API-запросы логируются в stdout (структурированный JSON)
- Все изменения в БД логируются через SQLAlchemy events (опционально, v2)

## 15. Производительность и масштабирование

### 15.1. Capacity Planning

| Ресурс | Минимум | Рекомендуется | Лимит |
|---|---|---|---|
| **RAM** | 16 ГБ | 32 ГБ | 80% автопауза |
| **Диск** | 50 ГБ свободных | 100 ГБ | Предупреждение при <10 ГБ |
| **CPU** | 4 ядра | 8 ядер | — |
| **GPU VRAM** | 8 ГБ (medium) / 12 ГБ (large-v3) | — | — |

### 15.2. Bottlenecks

| Узкое место | Митигация |
|---|---|
| **Whisper Large-v3 на CPU** | fallback на medium + квантование int8 |
| **Pyannote на CPU** | Нет (всегда GPU) |
| **LLM через Hermes API** | Кэш результатов на 24 часа |
| **Индексирование 5000 реплик** | batch insert, GIN-индекс отложенный |
| **Загрузка 10 ГБ файла** | HTTP Range с retry, chunk ≤8 МБ |

### 15.3. Автопауза при OOM

```python
# Мониторинг RSS каждые 5 сек
async def monitor_memory():
    while True:
        rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
        if rss_mb > MAX_RSS_MB:
            await pause_transcription()
            await notify_user("RAM > 80%, обработка на паузе")
        await asyncio.sleep(5)
```

### 15.4. Кэширование

| Уровень | Что кэшируется | Где | TTL |
|---|---|---|---|
| **L1: In-memory** | Whisper model (3 ГБ) | Backend процесс | До перезапуска |
| **L2: Browser** | Протоколы в IndexedDB | Frontend | Бесконечно (до явного удаления) |
| **L3: HTTP** | GET-запросы | ETag/If-None-Match | 60 сек |
| **L4: File** | Аудио/видео файлы | Filesystem | Бесконечно |

## 16. Disaster Recovery

### 16.1. Backup Strategy

| Что | Как | Где | Retention |
|---|---|---|---|
| **PostgreSQL дамп** | `pg_dump` ежедневно в `~/.html_mp/backup/` | Локально | 7 дней |
| **PostgreSQL WAL** | archive_mode=on (опционально, v2) | Локально | 1 день |
| **Полный бэкап** | tar.gz всего `~/.html_mp/` | Яндекс.Диск (через rclone) | 30 дней |
| **Audio/video файлы** | Символическая копия | Только локально (нет смысла бэкапить 100 ГБ) | — |

### 16.2. RTO / RPO

| Сценарий | RTO | RPO | Действия |
|---|---|---|---|
| Backend crash | 1 мин | 0 | systemd auto-restart |
| PostgreSQL corrupt | 5 мин | 0 | Восстановление из `pg_dump` |
| Диск переполнен | 10 мин | 0 | Ротация старых протоколов |
| Случайное удаление файла | 1 час | 24 часа | Восстановление из Яндекс.Диска |
| Полная потеря машины | 1 день | 24 часа | Восстановление из облачного бэкапа |

### 16.3. Процедура восстановления

```bash
# 1. Установить зависимости
pip install -r requirements.txt
playwright install chromium

# 2. Скачать бэкап
rclone copy yadisk:html_mp_backup/latest ~/.html_mp/

# 3. Восстановить PostgreSQL
pg_restore -d html_mp ~/.html_mp/backup/latest.dump

# 4. Запустить backend
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 5. Запустить frontend
open http://localhost:8000/static/
```

## 17. Открытые вопросы и риски

### 17.1. Открытые вопросы

| # | Вопрос | Планируемое решение |
|---|---|---|
| 1 | Какой **точный endpoint** Hermes API? | Уточнить при регистрации |
| 2 | Какой **лимит токенов** у GigaChat? | Бесплатный тариф = 100K токенов/мес |
| 3 | Какой **Telegram ID** Алексея? | Получить через @userinfobot |
| 4 | Какой **VPS провайдер** для бота? | Timeweb / Aéza / Selectel |
| 5 | Стоит ли **поддерживать видео (mp4)** в Astra Linux? | Да (но без Live Mode) |

### 17.2. Архитектурные риски

| # | Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|---|
| 1 | Whisper Large-v3 не помещается в 12 ГБ VRAM | Средняя | Высокое | Fallback на medium + int8 |
| 2 | Pyannote требует HuggingFace token | Средняя | Среднее | Токен в `.env`, альтернатива — resemblyzer |
| 3 | Hermes API изменит формат | Низкая | Высокое | Абстрактный LLM-клиент с интерфейсом |
| 4 | IndexedDB квота в Firefox < Chrome | Низкая | Среднее | Fallback на file-based кэш |
| 5 | Whisper галлюцинирует при тишине | Средняя | Среднее | LLM-коррекция текста (EPIC-CORRECT) |

### 17.3. Что не решено

- [ ] Streaming-режим для Hermes API (планируется в Q3 2027)
- [ ] Семантический поиск с эмбеддингами (планируется в Q2 2027)
- [ ] Интеграция с Яндекс Трекером для action items (планируется в Q3 2027)
- [ ] Мобильное приложение (out of scope MVP)
- [ ] Multi-user (out of scope MVP)

## 18. Связь с другими артефактами

| Артефакт | Связь с ARCHITECTURE |
|---|---|
| **VISION §7.1** | Scope IN → §2 Принципы, §3 Context |
| **VISION §9** | Ограничения → §2.3, §10 (ADR), §15 Performance |
| **NFR §2 Quality Goals** | QG-1..12 → §2.1, §15, §14 Security |
| **NFR §3 Performance** | Latency targets → §4 Containers, §11 Protocols |
| **NFR §7 Cross-platform** | Windows+Astra → §7 Deployment |
| **DATA_MODEL §17** | Таблицы → §4, §5.1, §12 |
| **API.md §60 endpoints** | Endpoints → §4, §5, §11.1 |
| **PROCESSES §P-01..04** | Процессы → §6 Sequence Diagrams |
| **SCREEN_FLOW §16 screens** | UI → §5.2 Frontend components |
| **TRACEABILITY §8** | US↔NFR → §10 ADR (обоснование) |

## 19. Готовность к реализации

| Компонент | Архитектура готова | Можно начинать код |
|---|---|---|
| **Backend (FastAPI + SQLAlchemy)** | ✅ | ✅ `code-scaffold-generator` |
| **Frontend (Vanilla JS + IndexedDB)** | ✅ | ✅ `code-scaffold-generator` |
| **Telegram Bot (aiogram 3.x)** | ✅ | ⏳ После основного MVP |
| **ML pipeline (Whisper + pyannote)** | ✅ | ✅ `code-scaffold-generator` |
| **DOCX экспорт** | ✅ | ✅ `code-scaffold-generator` |
| **Инфраструктура (systemd, rclone)** | ✅ | ⏳ При deployment |

**Заключение:** архитектура полностью определена. Можно начинать `code-scaffold-generator` для генерации скелета backend.

## Распределённая архитектура (US-089)

### C4: Container diagram

```
┌───────────────────────────────────────────────────────────────┐
│  USER (Browser)                                              │
│  ┌──────────────────────────────────────────────────┐        │
│  │  Frontend SPA (Vanilla JS)                       │        │
│  │  http://127.0.0.1:5173                          │        │
│  │  • UI + Drag&Drop upload                         │        │
│  │  • IndexedDB offline cache                       │        │
│  └────────────┬─────────────────────────────────────┘        │
└───────────────┼──────────────────────────────────────────────┘
                │ HTTP/JSON (CORS)
                ▼
┌───────────────────────────────────────────────────────────────┐
│  LOCAL BACKEND (FastAPI)                                      │
│  http://127.0.0.1:8000/api/v1/hmp/                          │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ FastAPI app                                          │    │
│  │  • PostgreSQL (utterances, decisions, protocols)    │    │
│  │  • Local Whisper (если не remote)                   │    │
│  │  • Polling progress                                 │    │
│  │  • Recording `user_setting.whisper_remote_enabled`  │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────┘
                │ HTTPS (optional, для prod)
                ▼
┌───────────────────────────────────────────────────────────────┐
│  REMOTE WHISPER (опционально)                                 │
│  http://195.133.77.76:8000 (или свой URL)                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ FastAPI app (минимальный)                           │    │
│  │  • /health endpoint                                 │    │
│  │  • POST /transcribe (multipart)                     │    │
│  │  • CORS middleware                                  │    │
│  │  • faster-whisper (base/small/medium/large-v3)     │    │
│  │  • systemd сервис                                   │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────┘
```

### Sequence: Remote transcription (US-089)

```
User         Frontend          Local Backend     Remote Whisper
 │               │                    │                  │
 │  click ✓      │                    │                  │
 ├──────────────►│                    │                  │
 │               │ read user_setting  │                  │
 │               ├───────────────────►│                  │
 │               │ enabled=true, url=...                 │
 │               │◄───────────────────┤                  │
 │               │                    │                  │
 │               │ GET /media/...source.webm             │
 │               ├───────────────────►│                  │
 │               │◄──────────────────┤ audio bytes       │
 │               │                    │                  │
 │               │ FormData(file, model, lang)            │
 │               ├───────────[XHR upload progress]────────►│
 │               │                    │                  │ loads Whisper
 │               │                    │                  │ transcribes
 │               │◄──── JSON {text, segments[]} ───────────┤
 │               │                    │                  │
 │  progress bar │                    │                  │
 │  updates      │                    │                  │
 │               │                    │                  │
 │  POST each segment to /api/v1/hmp/utterances             │
 │               ├───────────────────►│                  │
 │               │ reload transcript   │                  │
 │               │ toast.success: N реплик               │
 │               │                    │                  │
 ◄───────────────┤                    │                  │
```

### Компоненты

- **Local Backend** — управляет UI state, polling, persistence (БД)
- **Remote Whisper** — pure compute, stateless (можно горизонтально масштабировать)
- **Frontend** — switch между local/remote на основе user_setting

### Trade-offs

| Подход | Плюс | Минус |
|---|---|---|
| **Pure local** | Нет интернета | Медленно на CPU ноутбука |
| **Pure remote** | Быстро, качественно | Зависит от сети, нужна VPS |
| **Hybrid (E254)** | Гибкость, fallback | Немного сложнее UI |
