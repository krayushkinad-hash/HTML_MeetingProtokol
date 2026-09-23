# HTML_MeetingProtokol

> **Локальное приложение для протоколирования совещаний**
>
> Аудио/видео запись → транскрипция (Whisper) → саммари (AI) → решения/задачи → экспорт в Word/PDF.

![status](https://img.shields.io/badge/version-v1.2--2026--09--23-blue)
![python](https://img.shields.io/badge/python-3.10%2B-green)
![whisper](https://img.shields.io/badge/faster--whisper-latest-orange)

---

## 🎯 О приложении

**HTML_MeetingProtokol** — локальное (offline-first) веб-приложение для ведения базы протоколов совещаний.

### Что умеет

- 📁 **Загрузка аудио/видео** — drag-and-drop, HTTPS URL, локальные файлы
- 🎙️ **Транскрибация** — faster-whisper, 6 моделей (tiny→large-v3), GPU/CPU
- 👥 **Диаризация** — определение ораторов (эвристика по паузам)
- ⚖️ **Решения** — ручная пометка + AI auto-extract (по ключевым словам "решили", "договорились")
- ⭐ **Закладки "Важное"** — быстрый доступ к важным моментам
- 📝 **Редактирование реплик** — inline-edit с историей (ProtocolVersion)
- 🔍 **Грамматика/правописание** — MOCK-проверка с batch apply
- 📊 **Саммари** — AI-генерация саммари протокола
- 🤖 **Двухпроходная транскрибация** — Tiny → upgrade слабых → Large
- 🌍 **Перевод** — реплик на другой язык с сохранением оригинала
- 💾 **Экспорт** — Word, PDF, Markdown
- ⏸ **Pause/Resume** — длинные транскрибации можно прерывать
- 🔁 **Переход по таймкоду** — клик на timestamp в реплике → плеер перематывает

### Что НЕ умеет (пока)

- ❌ Streaming речь (только batch)
- ❌ Real-time коллаборация
- ❌ Запись с микрофона (только файлы)

---

## 🏗 Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND (Vanilla JS + HTMLAudioElement + IndexedDB)         │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ upload.js  │  │ protocol.js  │  │ list.js / live.js  │    │
│  └────────────┘  └──────────────┘  └────────────────────┘    │
│       ↓ HTTP/JSON via fetch                                  │
│  IndexedDB (offline cache)                                   │
└────────────────────┬─────────────────────────────────────────┘
                     │ /api/v1/hmp/*
┌────────────────────┴─────────────────────────────────────────┐
│  BACKEND (FastAPI + SQLAlchemy async + faster-whisper)       │
│  ┌──────────────────┐  ┌──────────────────────────┐          │
│  │ routers/         │  │ services/                │          │
│  │  - protocols      │  │  - transcription.py     │          │
│  │  - transcribe     │  │  - whisper_models.py     │          │
│  │  - decisions      │  │  - diarization.py        │          │
│  │  - utterances     │  │  - task_status.py        │          │
│  │  - ai (extract,   │  │                          │          │
│  │    cleanup,       │  │                          │          │
│  │    translate,     │  │                          │          │
│  │    check-grammar) │  │                          │          │
│  └──────────────────┘  └──────────────────────────┘          │
│       ↓ SQLAlchemy                                            │
│  PostgreSQL 15 (asyncpg)                                     │
└──────────────────────────────────────────────────────────────┘
```

**Стек:**
- Backend: Python 3.10+, FastAPI 0.115, SQLAlchemy 2.x async, PostgreSQL 15
- Frontend: Vanilla JS (ES2022), HTMLAudioElement + HTMLVideoElement, IndexedDB
- ML: faster-whisper (Whisper large-v3/tiny/...), ffmpeg для декодирования

---

## 📂 Структура проекта

```
HTML_MeetingProtokol/
├── code/
│   ├── hmp-backend/                  # FastAPI приложение
│   │   ├── app/
│   │   │   ├── main.py              # FastAPI startup + proxy cleanup (E061)
│   │   │   ├── routers/             # 17 роутеров
│   │   │   │   ├── protocols.py     # CRUD протоколов + upload
│   │   │   │   ├── transcribe.py    # transcribe + pause/resume + upgrade
│   │   │   │   ├── utterances.py    # GET/PUT текст + PATCH important
│   │   │   │   ├── decisions.py     # CRUD решений + timestamp_sec
│   │   │   │   ├── ai.py            # 4 endpoint (cleanup/translate/extract/check-grammar)
│   │   │   │   ├── audio.py         # streaming endpoints
│   │   │   │   ├── speakers.py      # CRUD ораторов
│   │   │   │   ├── diarize.py       # эвристическая диаризация
│   │   │   │   ├── summary.py       # AI саммари
│   │   │   │   ├── export.py        # Word/PDF/MD export
│   │   │   │   ├── live.py          # Live Meeting Protocol (Яндекс Телемост)
│   │   │   │   └── ...             # ещё 7 роутеров
│   │   │   ├── services/
│   │   │   │   ├── transcription.py # WhisperService (E131 streaming, E150 pause/resume)
│   │   │   │   ├── diarization.py   # HeuristicDiarization (E141)
│   │   │   │   ├── whisper_models.py # ModelManager
│   │   │   │   └── task_status.py   # update_task_status_in_db (E116)
│   │   │   ├── db/                 # SQLAlchemy models + session
│   │   │   ├── core/                # config, logging
│   │   │   └── schemas/             # Pydantic schemas
│   │   ├── scripts/migrations/      # ALTER TABLE скрипты
│   │   └── requirements-complete.txt
│   └── hmp-frontend/                 # Vanilla JS
│       ├── public/
│       │   ├── index.html
│       │   └── src/js/
│       │       ├── views/            # 12 views: list/protocol/upload/live/...
│       │       ├── api/client.js     # API wrapper (90+ endpoints)
│       │       ├── storage/         # IndexedDB wrapper
│       │       └── utils/
│       └── src/                      # source-of-truth (зеркалится в public)
└── artifacts/                         # Spec-driven development
    ├── 01-vision/
    ├── 02-personas/
    ├── 03-user-stories/              # US-001..US-087
    ├── 04-processes/
    ├── 07-data-model/
    ├── 08-nfr/
    ├── 09-api/
    ├── 10-traceability/
    └── 11-architecture/
```

---

## 🚀 Быстрый старт

### Требования

- Windows 10/11
- Python 3.10+
- PostgreSQL 15
- ~10 GB свободного места (модели Whisper + аудиозаписи)
- Опционально: NVIDIA GPU с CUDA (для ускорения в ~10x)

### Установка

```powershell
# 1. Клонировать
git clone https://github.com/krayushkinad-hash/HTML_MeetingProtokol.git
cd HTML_MeetingProtokol

# 2. Backend
cd code\hmp-backend
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements-complete.txt
.\.venv\Scripts\pip.exe install PySocks  # ← обязательно! Иначе SOCKS proxy упадёт
.\.venv\Scripts\python.exe -m scripts.migrations.2026_09_23_add_language_fields
.\.venv\Scripts\python.exe -m scripts.migrations.2026_09_23_add_pause_resume_fields
.\.venv\Scripts\python.exe -m scripts.migrations.2026_09_23_force_alter_columns

# 3. Frontend — без сборки, чистый JS
cd ..\hmp-frontend
# Откройте public/index.html в браузере или настройте сервер

# 4. Запуск backend
cd ..\hmp-backend
.\.venv\Scripts\python.exe main.py
```

Backend стартует на `http://127.0.0.1:8000`.

### Скачивание моделей Whisper

1. Откройте UI → **Настройки → Транскрипция → Управление моделями**
2. Скачайте хотя бы одну модель:
   - `tiny` — 75 MB, для тестов (быстро, некачественно)
   - `base` — 150 MB, default
   - `small` — 500 MB, баланс
   - `medium` — 1.5 GB, хорошо для русского
   - `large-v3` — 3 GB, лучшее качество

---

## 📂 Поддерживаемые форматы файлов

### Аудио
`mp3`, `wav`, `m4a`, `ogg`, `flac`, **`opus`**, **`webm`**, `aac`, `mka`

### Видео
`mp4`, `mkv`, **`webm`**, `mov`, `avi`, `3gp`, `ogv`

> `faster-whisper` использует **ffmpeg** для декодирования всех форматов. Никакой backend-валидации MIME — frontend фильтрует через `ALLOWED_EXTENSIONS`.

---

## 🎯 Использование

### Создать протокол

1. **Загрузить протокол** → drag-and-drop или HTTPS URL
2. Открыть протокол → кнопка **Транскрибировать**
3. Дождаться завершения (progress bar в углу)
4. Открыть вкладку **Транскрипт** — все реплики видны

### Пометить решение

- Клик `+ ⚖️` на реплике → ручная пометка
- Клик `🤖 Найти решения` в toolbar → AI найдёт паттерны
- Все решения → вкладка **Решения** с таймкодами

### Закладки "Важное"

- Клик `☆` на реплике → закладка (⭐)
- Жёлтая рамка слева
- Полный список → вкладка **Транскрипт** (фильтр в разработке)

### Перейти к моменту в записи

- Клик на **таймкод** реплики → плеер перематывает и запускает
- Скорость: 0.5x / 0.75x / 1x / 1.25x / 1.5x / 2x
- Громкость регулируется

### Редактирование реплик

- Клик ✏️ на реплике → редактор textarea
- `Ctrl+Enter` — сохранить, `Escape` — отмена
- История изменений в `ProtocolVersion`

### Проверка грамматики

- Клик 🔍 на реплике → проверка
- Клик `🔍 Проверить всё` → batch по всем репликам
- `✏️ Применить всё` — исправления разом

### Двухпроходная транскрибация

1. Транскрибация **base/tiny** → быстро получаем все реплики
2. Клик `🚀 Улучшить слабые` → большая модель только для слабых
3. Экономия: 30 минут audio × large = 30 мин, но если улучшать только 30% слабых → ~10 мин

### Перевод

1. Toolbar → выбрать язык перевода (EN/DE/ES/FR/RU)
2. Клик 🌐 Перевести
3. Под каждой репликой — оригинал + перевод с меткой языка

---

## 🔧 Возможности (features)

### Backend (73 Python модуля)

| Фича | Endpoint | Описание |
|---|---|---|
| Создать протокол | `POST /protocols` | multipart upload + URL |
| Список протоколов | `GET /protocols` | пагинация + фильтры |
| Транскрибация | `POST /transcribe/run` | Background task |
| Pause транскрибации | `POST /transcribe/pause/{id}` | E150 |
| Resume транскрибации | `POST /transcribe/resume/{id}` | E150 |
| Upgrade слабых | `POST /transcribe/upgrade/{id}` | E162: tiny → large для слабых |
| Streaming audio | `GET /media/protocols/{id}/source.{ext}` | для media-плеера |
| Список реплик | `GET /utterances?protocol_id=` | пагинация |
| Редактировать реплику | `PUT /utterances/{id}/text` | с version snapshot |
| Пометить "Важное" | `PATCH /utterances/{id}/important` | E172 |
| Решения CRUD | `GET/POST/DELETE /decisions` | с timestamp_sec |
| AI извлечь решения | `POST /ai/extract-decisions` | E147 |
| AI cleanup | `POST /ai/cleanup-text` | MOCK |
| AI translate | `POST /ai/translate` | E149 |
| AI grammar | `POST /ai/check-grammar` | E154 |
| Саммари | `POST /ai/summarize` | LLM |
| Диаризация | `POST /diarize/run` | E141 |
| Экспорт | `POST /export/word\|pdf\|md` | python-docx |
| Live Meeting | `POST /live/start` | Яндекс Телемост |

### Frontend (12 views)

| View | Назначение |
|---|---|
| `list.js` | Список всех протоколов + фильтры |
| `upload.js` | Drag-and-drop + HTTPS URL |
| `protocol.js` | Детальный вид протокола (главный) |
| `live.js` | Запись с Яндекс Телемост |
| `whisper-models.js` | Управление моделями Whisper |
| `settings.js` | Настройки + статистика |
| `calendar.js` | Календарь по датам |
| `edit-speakers.js` | Ручная правка ораторов |
| `screenshots.js` | Скриншоты видео |
| `actions.js` | Action items / задачи |
| `decisions.js` | Решения (отдельная страница) |

### Media Player (E170)

Встроенный плеер для аудио/видео:
- ▶ / ⏸ Play/Pause
- ⏩ Перемотка slider
- 🔊 Громкость + mute
- ⚡ Скорость: 0.5x — 2x
- 🎬 Автоопределение видео/аудио по MIME
- ⏰ Клик на таймкод → переход + автозапуск

---

## 📊 NFR (Non-Functional Requirements)

| NFR | Значение |
|---|---|
| Latency до первого текста | ≤ 10 сек (для 1 часа аудио) |
| Latency инкрементального появления реплик | каждые 2-3 сек (E131 streaming) |
| Max размер файла | 10 GB (cloud_max_file_size_mb) |
| Max длина одной транскрибации | без ограничений (pause/resume) |
| Поддержка браузеров | Chrome 90+, Firefox 88+, Safari 14+ |
| Offline режим | частичный (IndexedDB) |

---

## 🐛 Известные проблемы

| Проблема | Workaround |
|---|---|
| SOCKS proxy без PySocks | `pip install PySocks` |
| GPU не используется | проверить CUDA + cuDNN 9.x |
| Backend не стартует | проверить миграции: `python -m scripts.migrations.*` |
| Reset stuck transcriptions | автоматически при старте |

---

## 🛠 Разработка

### Pipeline-checker

```powershell
python .hermes\profiles\alex3\skills\pipeline-checker\scripts\run_pipeline_check.py --full
```

Проверяет:
- Все артефакты (Vision → Architecture)
- US_LIST ↔ US_*.md карточки
- TRACEABILITY маппинг
- Backend синтаксис (73 .py модулей)
- Frontend JS syntax
- README consistency

### E-коды

`hermes-profile → alex3 → skills → hmp-errors-database` — база знаний с фиксами
багов. Накопили **150+ E-кодов** (E001..E173).

### Файлы артефактов

- `artifacts/01-vision/VISION.md` — общее видение
- `artifacts/03-user-stories/` — 87 US-карточек (US-001..US-087)
- `artifacts/04-processes/PROCESSES.md` — BPMN workflows
- `artifacts/07-data-model/DATA_MODEL.md` — SQLAlchemy модели
- `artifacts/09-api/API.md` — все endpoints
- `artifacts/10-traceability/TRACEABILITY.md` — US ↔ Frontend ↔ Backend
- `artifacts/11-architecture/ARCHITECTURE.md` — диаграммы

---

## 📜 История версий

### v1.2 (2026-09-23)
- **E150**: Pause/Resume транскрибации + cross-session
- **E151**: Audio hash validation для resume
- **E153**: Чистая ретранскрибация (DELETE в router)
- **E162**: Двухпроходная транскрибация (tiny → large для слабых)
- **E163**: Progress bar UI показывает ошибки
- **E164/E166**: SOCKS proxy fix
- **E167/E168**: Model override leak / shadowing fixes
- **E170**: Медиа-плеер (аудио + видео) с переходом по таймкоду
- **E171**: Ремонт пометки решений (guard data-wired)
- **E172**: Закладки "Важное" (⭐)
- **E173**: Поддержка webm/opus/mka/mkv/...

### v1.1 (2026-09-21)
- E001..E130: Базовый функционал (транскрибация, диаризация, решения)
- 7 моделей Whisper

### v1.0 (2026-09-15)
- MVP

---

## 🤝 Contributing

См. `.hermes/profiles/alex3/skills/` для всех фиксов (E001..E173) и `.hermes/profiles/alex3/projects/HTML_MeetingProtokol/artifacts/` для спецификаций.

---

## 📝 Лицензия

[Внутренний продукт]

---

**Версия документа:** 2026-09-23
**Эпиков:** 16 | **US:** 87 | **E-кодов:** 173 | **Backend .py:** 73 | **Размер:** ~30 000 строк
