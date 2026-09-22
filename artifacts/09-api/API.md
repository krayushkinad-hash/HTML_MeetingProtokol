# API Specification: HTML_MeetingProtokol

**Дата:** 2026-09-21
**Версия:** 1.1
**API Base URL:** `http://127.0.0.1:8000/api/v1/hmp`
**Middleware prefix:** `/api/v1/hmp/` (все routers смонтированы с `prefix=api_prefix`)

---

## 1. Базовый URL

```
http://127.0.0.1:8000/api/v1/hmp/
```

Все запросы из frontend должны использовать полный путь с `/api/v1/hmp/` prefix.

---

## 2. CORS и безопасность

- **CORS:** `force_cors_headers` middleware добавляет заголовки ко всем ответам
- **GET fallback:** 404/204 на GET заменяется на `null` или `[]`
- **Correlation ID:** каждый запрос пробрасывает `X-Correlation-Id`

---

## 3. Формат ошибок (RFC 7807 Problem Details)

```json
{
  "type": "about:blank",
  "title": "Validation Error",
  "status": 422,
  "detail": "Не указано обязательное поле",
  "correlation_id": "uuid"
}
```

---

## 4. Параметры в URL

Все параметры в URL используют **полные имена** для единообразия:

| Параметр | Тип | Описание |
|---|---|---|
| `{protocol_id}` | UUID | ID протокола |
| `{task_id}` | UUID | ID задачи транскрипции |
| `{audio_file_id}` | UUID | ID аудио файла |
| `{utterance_id}` | UUID | ID реплики |
| `{action_item_id}` | UUID | ID задачи |
| `{speaker_id}` | UUID | ID оратора |
| `{folder_id}` | UUID | ID папки |
| `{decision_id}` | UUID | ID решения |
| `{screenshot_id}` | UUID | ID скриншота |
| `{tag_id}` | UUID | ID тега |
| `{term_id}` | UUID | ID термина словаря |
| `{user_id}` | UUID | ID пользователя |
| `{version_number}` | int | Номер версии |
| `{ext}` | str | Расширение файла |

---

## 5. Endpoints

### 5.А. Protocols (US-001, US-002, US-010, US-014, US-053, US-060)

Эпик: upload, protocol, lifecycle, folders.

#### 5.А.1. `POST /api/v1/hmp/protocols`

Создать протокол (загрузить локальный файл). **(US-001)**

- **Body:** multipart/form-data
  - `file`: UploadFile (обязательно)
  - `title`, `date`, `location`, `chair`: метаданные

#### 5.А.2. `POST /api/v1/hmp/protocols/from-url`

Создать протокол из URL. **(US-002)**

- **Body:** `{ "url": "https://...", "title": "...", "date": "..." }`

#### 5.А.3. `GET /api/v1/hmp/protocols`

Список протоколов с пагинацией и фильтром. **(US-010)**

- **Query:** `page` (default=1), `limit` (default=50, max=200), `sort` (default=-date), `folder_id`

#### 5.А.4. `GET /api/v1/hmp/protocols/{protocol_id}`

Получить протокол по ID.

#### 5.А.5. `PATCH /api/v1/hmp/protocols/{protocol_id}`

Обновить метаданные протокола.

#### 5.А.6. `DELETE /api/v1/hmp/protocols/{protocol_id}`

Soft delete протокола. **(US-052)**

#### 5.А.7. `DELETE /api/v1/hmp/protocols/{protocol_id}/permanent`

Hard delete протокола со всеми связанными данными. **(US-053)**

Каскадно удаляет: utterances, speakers, tags, action_items, decisions, summary, transcription_tasks, screenshots, audio_file. Удаляет файл с диска.

#### 5.А.8. `GET /api/v1/hmp/protocols/{protocol_id}/action-items`

Список action items протокола.

#### 5.А.9. `GET /api/v1/hmp/protocols/{protocol_id}/decisions`

Список решений протокола.

#### 5.А.10. `GET /api/v1/hmp/protocols/{protocol_id}/screenshots`

Список скриншотов протокола.

#### 5.А.11. `GET /api/v1/hmp/protocols/{protocol_id}/summary`

Саммари протокола. **(US-022)**

#### 5.А.12. `GET /api/v1/hmp/protocols/{protocol_id}/tags`

Список тегов протокола. **(US-028)**

#### 5.А.13. `POST /api/v1/hmp/protocols/batch-move`

Пакетное перемещение протоколов в папку. **(US-060)**

- **Body:** `{ "protocol_ids": ["uuid", ...], "folder_id": "uuid" }`

#### 5.А.14. `PUT /api/v1/hmp/protocols/{protocol_id}/folder`

Переместить протокол в папку. **(US-060)**

- **Body:** `{ "folder_id": "uuid" }`

---

### 5.Б. Folders (US-059, US-060, US-061)

Эпик: folders.

#### 5.Б.1. `GET /api/v1/hmp/folders`

Список папок с фильтром по parent.

- **Query:** `parent_id` (опционально)

#### 5.Б.2. `POST /api/v1/hmp/folders`

Создать папку. **(US-059)**

- **Body:** `{ "name": "...", "color": "#3b82f6", "icon": "...", "parent_id": "uuid" }`

#### 5.Б.3. `GET /api/v1/hmp/folders/{folder_id}`

Получить папку по ID.

#### 5.Б.4. `PATCH /api/v1/hmp/folders/{folder_id}`

Обновить папку.

#### 5.Б.5. `DELETE /api/v1/hmp/folders/{folder_id}`

Удалить папку. **(US-061)**

#### 5.Б.6. `POST /api/v1/hmp/folders/{folder_id}/protocols/{protocol_id}`

Добавить протокол в папку.

#### 5.Б.7. `DELETE /api/v1/hmp/folders/{folder_id}/protocols/{protocol_id}`

Убрать протокол из папки.

---

### 5.В. Audio Files (US-001, US-013, US-064, US-069)

Эпик: upload, file.

#### 5.В.1. `GET /api/v1/hmp/audio-files/{audio_file_id}`

Получить метаданные аудио-файла.

- **Returns:** `{ "id", "filename", "file_path", "extension", "size_bytes", "mime_type", "duration_sec" }`

#### 5.В.2. `GET /api/v1/hmp/audio-files/{audio_file_id}/video`

HTTP Range streaming видео. (legacy)

#### 5.В.3. `POST /api/v1/hmp/audio-files/{audio_file_id}/open-folder`

Открыть папку с файлом в проводнике ОС. **(US-069)**

Кроссплатформенно: Windows (explorer), macOS (open), Linux (xdg-open).

- **Returns:** `{ "os", "folder", "file_path", "command" }`

---

### 5.Г. Transcription (US-005, US-006, US-049, US-050, US-051)

Эпик: trans.

#### 5.Г.1. `POST /api/v1/hmp/transcribe/run`

Запустить транскрипцию протокола. **(US-005)**

- **Body:** `{ "protocol_id": "uuid", "model": "large-v3", "language": "ru", "beam_size": 5, "compute_type": "float16" }`

#### 5.Г.2. `GET /api/v1/hmp/transcribe/status/{task_id}`

Получить статус задачи (in-memory).

#### 5.Г.3. `POST /api/v1/hmp/transcribe/cancel/{task_id}`

Отменить задачу транскрипции.

#### 5.Г.4. `GET /api/v1/hmp/transcribe/progress/{task_id}`

Прогресс задачи (in-memory).

#### 5.Г.5. `GET /api/v1/hmp/transcribe/progress-by-protocol/{protocol_id}`

Прогресс транскрипции через БД (survives restart). **(US-066)**

#### 5.Г.6. `GET /api/v1/hmp/transcribe/health`

Healthcheck подсистемы транскрипции.

---

### 5.Д. Diarization (US-003, US-007)

#### 5.Д.1. `POST /api/v1/hmp/diarize/run`

Запустить диаризацию. **(US-007)**

- **Body:** `{ "protocol_id": "uuid" }`

#### 5.Д.2. `GET /api/v1/hmp/diarize/result/{protocol_id}`

Получить результат диаризации.

---

### 5.Е. Utterances (US-003, US-008)

Эпик: diar, transcript.

#### 5.Е.1. `GET /api/v1/hmp/utterances`

Список реплик с фильтром.

- **Query:** `protocol_id`, `limit` (default=100), `cursor`

#### 5.Е.2. `GET /api/v1/hmp/utterances/{utterance_id}`

Получить реплику.

#### 5.Е.3. `PATCH /api/v1/hmp/utterances/{utterance_id}/text`

Изменить текст реплики. **(US-008)**

- **Body:** `{ "text": "..." }`

#### 5.Е.4. `PATCH /api/v1/hmp/utterances/{utterance_id}/speaker`

Назначить оратора. **(US-003)**

- **Body:** `{ "speaker_id": "uuid" }`

#### 5.Е.5. `GET /api/v1/hmp/utterances/{utterance_id}/versions`

История версий реплики.

#### 5.Е.6. `POST /api/v1/hmp/utterances/{utterance_id}/restore/{version_number}`

Восстановить версию реплики.

---

### 5.Ж. Speakers (US-003)

#### 5.Ж.1. `GET /api/v1/hmp/speakers`

Список ораторов протокола.

- **Query:** `protocol_id`

#### 5.Ж.2. `PATCH /api/v1/hmp/speakers/{speaker_id}`

Обновить оратора (имя, цвет).

#### 5.Ж.3. `POST /api/v1/hmp/speakers/merge`

Объединить двух ораторов. **(US-003)**

- **Body:** `{ "source_id": "uuid", "target_id": "uuid", "new_display_name": "..." }`

---

### 5.З. Decisions (US-023, US-026)

#### 5.З.1. `GET /api/v1/hmp/decisions`

Список решений протокола.

- **Query:** `protocol_id`

#### 5.З.2. `POST /api/v1/hmp/decisions`

Создать решение.

#### 5.З.3. `DELETE /api/v1/hmp/decisions/{decision_id}`

Удалить решение.

---

### 5.И. Action Items (US-023)

#### 5.И.1. `POST /api/v1/hmp/action-items`

Создать задачу.

#### 5.И.2. `PATCH /api/v1/hmp/action-items/{action_item_id}`

Обновить задачу (статус, ответственный).

#### 5.И.3. `DELETE /api/v1/hmp/action-items/{action_item_id}`

Удалить задачу.

---

### 5.К. Tags (US-028, US-029)

#### 5.К.1. `POST /api/v1/hmp/tags`

Создать тег. **(US-028)**

#### 5.К.2. `DELETE /api/v1/hmp/tags/{tag_id}`

Удалить тег.

---

### 5.Л. Screenshots (US-046, US-047)

#### 5.Л.1. `POST /api/v1/hmp/screenshots`

Создать скриншот. **(US-047)**

- **Body:** `{ "protocol_id", "file_path", "timestamp_sec" }`

#### 5.Л.2. `POST /api/v1/hmp/screenshots/upload`

Загрузить файл скриншота (multipart).

#### 5.Л.3. `GET /api/v1/hmp/screenshots/{screenshot_id}`

Получить скриншот.

#### 5.Л.4. `DELETE /api/v1/hmp/screenshots/{screenshot_id}`

Удалить скриншот.

---

### 5.М. AI Operations (US-022, US-023, US-026, US-044, US-045)

#### 5.М.1. `POST /api/v1/hmp/ai/summarize`

Сгенерировать саммари протокола. **(US-022)**

- **Body:** `{ "protocol_id": "uuid" }`

#### 5.М.2. `POST /api/v1/hmp/ai/extract-actions`

Извлечь задачи из текста. **(US-023)**

- **Body:** `{ "protocol_id": "uuid" }`

#### 5.М.3. `POST /api/v1/hmp/ai/cleanup-text`

LLM cleanup текста. **(US-044)**

- **Body:** `{ "text": "...", "dictionary": [...] }`

#### 5.М.4. `POST /api/v1/hmp/ai/restore-punctuation`

Восстановить пунктуацию. **(US-006)**

#### 5.М.5. `POST /api/v1/hmp/ai/review-transcript`

Ревью транскрипта LLM.

#### 5.М.6. `POST /api/v1/hmp/ai/semantic-search`

Семантический поиск.

---

### 5.Н. Calendar / Search (US-011, US-013)

#### 5.Н.1. `GET /api/v1/hmp/calendar`

Протоколы по месяцам. **(US-011)**

- **Query:** `year`, `month`

#### 5.Н.2. `GET /api/v1/hmp/search`

Полнотекстовый поиск. **(US-013)**

- **Query:** `q`, `protocol_id`

---

### 5.О. Dictionary (US-045)

#### 5.О.1. `GET /api/v1/hmp/dictionary`

Список словарных терминов.

#### 5.О.2. `POST /api/v1/hmp/dictionary`

Добавить термин.

- **Body:** `{ "term": "...", "replacement": "...", "category": "..." }`

#### 5.О.3. `PATCH /api/v1/hmp/dictionary/{term_id}`

Обновить термин.

#### 5.О.4. `DELETE /api/v1/hmp/dictionary/{term_id}`

Удалить термин.

---

### 5.П. User Settings (US-054..058, US-066, US-072)

#### 5.П.1. `GET /api/v1/hmp/user-setting`

Получить настройки пользователя. **(US-054)**

#### 5.П.2. `PATCH /api/v1/hmp/user-setting`

Обновить настройки. **(US-054)**

- **Body:** любое поле из UserSetting (см. DATA_MODEL.md §4.4)

---

### 5.Р. Export (US-015, US-016, US-024, US-025)

#### 5.Р.1. `POST /api/v1/hmp/export/docx`

Запустить экспорт протокола в DOCX. **(US-015)**

- **Body:** `{ "protocol_id", "template_id", "include_screenshots": true }`

#### 5.Р.2. `GET /api/v1/hmp/export/status/{task_id}`

Статус экспорта.

#### 5.Р.3. `GET /api/v1/hmp/export/download/{task_id}`

Скачать DOCX-файл.

---

### 5.С. Bot (Telegram) (US-031, US-037, US-067)

#### 5.С.1. `GET /api/v1/hmp/bot/settings`

Получить настройки Telegram бота. **(US-037)**

#### 5.С.2. `PATCH /api/v1/hmp/bot/settings`

Обновить настройки бота.

#### 5.С.3. `POST /api/v1/hmp/bot/test-connection`

Проверить подключение к Telegram. **(US-067)**

- **Body:** `{ "bot_token": "..." }`

#### 5.С.4. `GET /api/v1/hmp/bot/users`

Список разрешённых пользователей.

#### 5.С.5. `POST /api/v1/hmp/bot/users`

Добавить пользователя.

#### 5.С.6. `PATCH /api/v1/hmp/bot/users/{user_id}`

Обновить пользователя.

#### 5.С.7. `DELETE /api/v1/hmp/bot/users/{user_id}`

Удалить пользователя.

#### 5.С.8. `GET /api/v1/hmp/bot/commands-log`

Лог команд бота.

#### 5.С.9. `POST /api/v1/hmp/bot/restart`

Перезапустить бота.

#### 5.С.10. `POST /api/v1/hmp/bot/test`

Тестовая команда.

---

### 5.Т. Live Mode (US-009, US-019, US-030)

#### 5.Т.1. `POST /api/v1/hmp/live/start`

Начать live mode (WebSocket). **(US-019, US-030)**

#### 5.Т.2. `POST /api/v1/hmp/live/{protocol_id}/stop`

Остановить live mode.

---

### 5.У. Media (Static) (US-064)

#### 5.У.1. `GET /api/v1/hmp/media/protocols/{protocol_id}/source.{ext}`

Потоковое видео/аудио для video-player. **(US-064)**

- **Path:** `{ext}` — расширение файла (m4a, mp4, wav, mp3)

Frontend URL pattern:
```javascript
const url = `http://127.0.0.1:8000/api/v1/hmp/media/protocols/${protocolId}/source.${ext}`;
```

---

### 5.Ф. Admin (US-072)

#### 5.Ф.1. `DELETE /api/v1/hmp/admin/clear-data`

Удалить ВСЕ данные (БД + файлы). **(US-072)**

Удаляет из БД: utterances, speakers, tags, action_items, decisions, summaries, transcription_tasks, screenshots, audio_files, folders, protocol_versions, protocols.

Удаляет с диска: всю папку `~/.html_mp/protocols/`.

#### 5.Ф.2. `GET /api/v1/hmp/admin/stats`

Статистика для диалога подтверждения.

- **Returns:** `{ "protocols", "audio_files", "utterances", "screenshots", "folders" }`

---

### 5.Х. Health

#### 5.Х.1. `GET /api/v1/hmp/health`

Basic healthcheck.

#### 5.Х.2. `GET /api/v1/hmp/health/deep`

Deep healthcheck (проверяет БД, диск).

---

## 6. Связь с другими артефактами

- **DATA_MODEL.md** — структура БД (19 таблиц)
- **NFR.md** — нефункциональные требования
- **US_LIST.md** — перечень US (77 US, 15 эпиков)
- **TRACEABILITY.md** — маппинг US ↔ endpoints ↔ frontend
- **ARCHITECTURE.md** — архитектура и ADR

---

## 7. Тестирование

- **Swagger UI:** `http://127.0.0.1:8000/docs`
- **OpenAPI JSON:** `http://127.0.0.1:8000/openapi.json`
- **Тесты:** `python code/hmp-backend/scripts/test_endpoints.py`

```bash
# Из корня проекта:
python code/hmp-backend/scripts/test_endpoints.py

# Проверка всех endpoints через Curl:
for endpoint in /health /protocols /folders /admin/stats; do
    curl "http://127.0.0.1:8000/api/v1/hmp${endpoint}"
done
```

---

## 8. Changelog

- **v1.1 (2026-09-21):** Унифицированный формат endpoint'ов (`### X.Y.Z. \`METHOD /path\``), единые имена параметров (`{protocol_id}` вместо `{id}`)
- **v1.0 (2026-09-15):** Начальная версия

---

**Документ:** API Specification v1.1
**Автор:** Generated by api-detail-designer
**Дата:** 2026-09-21

### 5.Ф. Whisper Models (US-058, US-075)

#### 5.Ф.1. `GET /whisper/models`
List all available Whisper models with download status.

```
curl http://127.0.0.1:8000/api/v1/hmp/whisper/models
```

Response:
```json
{
  "models": [
    {
      "name": "tiny",
      "size_mb": 75,
      "repo": "Systran/faster-whisper-tiny",
      "downloaded": true,
      "path": "C:\Users\...",
      "size_on_disk_mb": 75.4
    },
    ...
  ],
  "active": "large-v3",
  "cache_dir": "C:\Users\...\.cache\huggingface\hub",
  "available": ["tiny","base","small","medium","large-v2","large-v3","distil-small-en","distil-medium-en","distil-large-v3"]
}
```

#### 5.Ф.2. `POST /whisper/download/{name}`
Start downloading a model in background. Returns 202.

```
curl -X POST http://127.0.0.1:8000/api/v1/hmp/whisper/download/large-v3
```

#### 5.Ф.3. `GET /whisper/progress/{name}`
Get download progress.

```
curl http://127.0.0.1:8000/api/v1/hmp/whisper/progress/large-v3
```

Response:
```json
{
  "model_name": "large-v3",
  "downloaded_bytes": 1048576,
  "total_bytes": 3250000000,
  "percent": 32.3,
  "elapsed_sec": 12.5,
  "speed_mbps": 0.5,
  "success": null
}
```

#### 5.Ф.4. `GET /whisper/status/{name}`
Quick check if model is cached locally.

```
curl http://127.0.0.1:8000/api/v1/hmp/whisper/status/tiny
```

Response:
```json
{
  "model": "tiny",
  "downloaded": true,
  "expected_size_mb": 75,
  "size_mb": 75.4,
  "path": "C:\Users\..."
}
```

#### 5.Ф.5. `POST /whisper/active/{name}`
Set active model (used by transcription service).

```
curl -X POST http://127.0.0.1:8000/api/v1/hmp/whisper/active/tiny
```

#### 5.Ф.6. `DELETE /whisper/models/{name}`
Remove downloaded model from cache.

```
curl -X DELETE http://127.0.0.1:8000/api/v1/hmp/whisper/models/tiny
```

#### 5.Ф.7. `GET /whisper/active`
Get currently active model name.

```
curl http://127.0.0.1:8000/api/v1/hmp/whisper/active
```

Response:
```json
{"active": "large-v3"}
```

### 5.Э.6. `POST /export/archive/{protocol_id}` (US-071)
Archive protocol as ZIP with all related files.

```
curl -X POST http://127.0.0.1:8000/api/v1/hmp/export/archive/{protocol_id}
```

Response:
```json
{
  "archive_id": "uuid",
  "path": "C:\\...\\protocols\\{pid}\\uuid.zip",
  "size_kb": 1234,
  "download_url": "/api/v1/hmp/export/download/uuid"
}
```

ZIP содержит:
- `protocol.json` — метаданные
- `transcript.txt` — текст реплик
- `source.{ext}` — оригинальный файл

### 5.Э.7. `GET /export/download/{archive_id}` (US-071)
Download the archived ZIP.

```
curl -OJ http://127.0.0.1:8000/api/v1/hmp/export/download/{archive_id}
```

### 5.Ф.8. `GET /whisper/debug/proxy` (E061)
Diagnostic endpoint — show current proxy environment variables.

```
curl http://127.0.0.1:8000/api/v1/hmp/whisper/debug/proxy
```

Response:
```json
{
  "HTTP_PROXY": null,
  "HTTPS_PROXY": null,
  "ALL_PROXY": "socks4://127.0.0.1:10808",  // проблема!
  "SOCKS_PROXY": null,
  ...
}
```

Используйте чтобы проверить что proxy vars очищены. Если `ALL_PROXY` или `SOCKS_PROXY` не null — перезапустите backend после очистки env vars.

## Settings API (env-based)

### Whisper Configuration

| Variable | Type | Default | Description |
|---|---|---|---|
| `WHISPER_DEVICE` | `cuda` / `cpu` | `cpu` | Inference device (E111 auto-detect cudnn) |
| `WHISPER_COMPUTE_TYPE` | `float16` / `int8` / `float32` | `int8` | Quantization |
| `WHISPER_VAD_FILTER` | `bool` | `false` | Voice Activity Detection (E118) |
| `VAD_MIN_SILENCE_DURATION_MS` | `int` | `1000` | Min silence to trim (E118) |
| `VAD_SPEECH_PAD_MS` | `int` | `300` | Padding around speech (E118) |
| `VAD_THRESHOLD` | `float` | `0.5` | Speech threshold 0-1 (E118) |

### Example .env

```ini
# Use GPU
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16

# VAD on (for clean speech)
WHISPER_VAD_FILTER=true
VAD_MIN_SILENCE_DURATION_MS=1000
VAD_THRESHOLD=0.5
```
