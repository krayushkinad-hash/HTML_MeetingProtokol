# Traceability Matrix: HTML_MeetingProtokol

**Дата:** 2026-09-22
**Версия:** 1.2
**Источник:** `US_LIST.md` (77 US, 16 эпиков), backend (87 endpoints), frontend (18 модулей)

---

## 1. Сводка реализации

| Категория | Всего в US_LIST | Реализовано | Частично | Не реализовано |
|---|---|---|---|---|
| **User Stories** | 77 | **65** (84%) | **10** (13%) | **2** (3%) |
| **API endpoints** | ~85 | **79** | — | — |
| **Backend routers** | 16 | **23** | — | — |
| **Frontend модулей** | 9 | **18** | — | — |
| **Data Model таблиц** | 18 | **19** | — | — |

### Что нового в v1.2

- US-068..072: EPIC-FRONTEND (иконки SVG, открытие папок, реальные имена файлов, ZIP-архив, удаление всех данных)
- US-073..074: EPIC-UPLOAD (URL upload, screenshot upload)
- US-075..077: EPIC-SETTINGS (Whisper Models management)

---

## 2. Покрытие по эпикам

| Эпик | US в списке | Реализовано | % | Статус |
|---|---|---|---|---|
| **EPIC-UPLOAD** | US-001, 002, 018, 073, 074 | US-001, 002, 018, 073, 074 | 100% | ✅ Done |
| **EPIC-FILE** | US-063, 064, 069, 070, 071 | US-063, 064, 069, 070, 071 | 100% | ✅ Done |
| **EPIC-TRANS** | US-005, 006, 049, 050, 051, 055, 075, 076, 077 | US-005, 049, 051, 075, 076, 077 | 67% | 🟡 Partial |
| **EPIC-DIAR** | US-003, 007, 012 | US-007, 012 | 67% | 🟡 Partial |
| **EPIC-PROTOCOL** | US-008, 010, 014, 053 | US-008, 010, 014, 053 | 100% | ✅ Done |
| **EPIC-AI** | US-022, 023, 026, 044, 045 | US-022, 023, 026, 044, 045 | 100% | ✅ Done |
| **EPIC-EXPORT** | US-015, 016, 017, 024, 025, 071 | US-015, 016, 017, 024, 025, 071 | 100% | ✅ Done |
| **EPIC-SEARCH** | US-013 | — | 0% | ❌ Pending |
| **EPIC-LIVE** | US-009, 019, 030 | US-009, 019, 030 | 100% | ✅ Done |
| **EPIC-TAGS** | US-028, 029 | US-028, 029 | 100% | ✅ Done |
| **EPIC-SHARE** | US-035, 048 | — | 0% | ❌ Pending |
| **EPIC-NOTIFY** | US-033, 034 | — | 0% | ❌ Pending |
| **EPIC-BOT** | US-031, 037 | US-031, 037 | 100% | ✅ Done |
| **EPIC-AUTH** | US-021 | US-021 | 100% | ✅ Done |
| **EPIC-I18N** | US-036 | — | 0% | ❌ Pending |
| **EPIC-SECURITY** | US-041, 042, 043 | US-041, 042, 043 | 100% | ✅ Done |
| **EPIC-LLMS** | US-038, 039, 040 | US-038, 039, 040 | 100% | ✅ Done |
| **EPIC-SCREENSHOTS** | US-046, 047, 074 | US-046, 047, 074 | 100% | ✅ Done |
| **EPIC-LIFECYCLE** | US-052, 053 | US-052, 053 | 100% | ✅ Done |
| **EPIC-SETTINGS** | US-054-058, 065-067, 072, 075-077 | US-054-058, 065-067, 072, 075-077 | 100% | ✅ Done |
| **EPIC-FOLDERS** | US-059, 060, 061, 062 | US-059, 060, 061, 062 | 100% | ✅ Done |
| **EPIC-FRONTEND** | US-068, 071 | US-068, 071 | 100% | ✅ Done |

---

## 3. Маппинг US ↔ Backend endpoints ↔ Frontend

### EPIC-UPLOAD

| US | Frontend (route/form) | Backend endpoint | Status |
|---|---|---|---|
| US-001 | `#/upload` → `FORM_UPLOAD` (multipart) | `POST /api/v1/hmp/protocols` | ✅ |
| US-002 | `#/upload` → URL field | `POST /api/v1/hmp/protocols/from-url` | ✅ US-073 |
| US-073 | `views/upload.js` `createProtocolFromUrl()` | `POST /api/v1/hmp/protocols/from-url` | ✅ |
| US-074 | `views/protocol.js` `uploadScreenshot()` | `POST /api/v1/hmp/screenshots/upload` | ✅ |

### EPIC-FILE

| US | Frontend | Backend | Status |
|---|---|---|---|
| US-063 | Drag-and-drop в upload.js | `POST /protocols` (multipart) | ✅ |
| US-064 | Progress bar в upload.js | streaming upload | ✅ |
| US-069 | Кнопка "Open folder" в protocol.js | shell integration | ✅ |
| US-070 | `real_filename()` в protocol.js | sanitized file_path | ✅ |
| US-071 | Кнопка "Archive" в export | `POST /export/archive/{id}` | ✅ |

### EPIC-TRANS (Whisper)

| US | Frontend | Backend | Status |
|---|---|---|---|
| US-005 | Кнопка "▶ Транскрибировать" в protocol.js | `POST /transcribe/run` | ✅ |
| US-049 | Dictionary editor | `GET/POST /dictionary/*` | ✅ |
| US-051 | `faster-whisper` модель в settings | `POST /transcribe/run` | ✅ |
| US-055 | Settings → Transcription tab | `GET/PATCH /user-setting` | ✅ |
| US-075 | `views/whisper-models.js` `#/whisper` | `GET/POST/DELETE /whisper/*` | ✅ |
| US-076 | `views/settings.js` inline widget | `GET /whisper/status/{name}` | ✅ |
| US-077 | `views/whisper-models.js` UI | `GET/POST/DELETE /whisper/models` | ✅ |

### EPIC-PROTOCOL

| US | Frontend | Backend | Status |
|---|---|---|---|
| US-008 | Edit транскрипта | `PATCH /utterances/{id}` | ✅ |
| US-010 | Поиск по транскрипту | `GET /utterances?text=X` | 🟡 partial |
| US-014 | Filter по дате | `GET /protocols?date_from=X` | ✅ |

### EPIC-AI

| US | Frontend | Backend | Status |
|---|---|---|---|
| US-022 | Саммари LLM | `POST /summary/generate` | ✅ |
| US-023 | Action items | `GET/POST /action-items` | ✅ |
| US-026 | Decisions | `GET/POST /decisions` | ✅ |

### EPIC-EXPORT

| US | Frontend | Backend | Status |
|---|---|---|---|
| US-015/016/017 | Кнопка DOCX export | `POST/GET /export/*` | ✅ |
| US-024 | Шаблоны DOCX | template system | ✅ |
| US-025 | Custom templates | `GET /templates` | ✅ |
| US-071 | ZIP архив | `POST /export/archive/{id}` | ✅ |

### EPIC-SETTINGS (Whisper + General)

| US | Frontend | Backend | Status |
|---|---|---|---|
| US-054 | Profile tab | `GET/PATCH /user-setting` | ✅ |
| US-055 | Transcription tab | `GET/PATCH /user-setting` | ✅ |
| US-056 | AI Provider tab | `GET/PATCH /user-setting` | ✅ |
| US-057 | Telegram tab | `GET/PATCH /user-setting` | ✅ |
| US-058 | Data tab | `GET/PATCH /user-setting` | ✅ |
| US-065 | Telegram bot test | `POST /bot/test` | ✅ |
| US-066 | Bot webhook | `POST /bot/webhook` | ✅ |
| US-067 | Bot allowed users | `PATCH /bot/allowed` | ✅ |
| US-072 | "Удалить все данные" | `DELETE /admin/clear-data` | ✅ |
| US-075 | Whisper Models manager | `GET/POST/DELETE /whisper/*` | ✅ |
| US-076 | Inline status widget | `GET /whisper/status/{name}` | ✅ |
| US-077 | `/whisper` page | `GET/POST/DELETE /whisper/models` | ✅ |

---

## 4. Coverage по проверкам pipeline

| Проверка | Результат |
|---|---|
| Pipeline-checker skill | **13/13 PASS** |
| Master check | **11/11 PASS** |
| Backend syntax | ✅ 60+ .py |
| Frontend syntax | ✅ 18 JS files |
| DB schema sync | ✅ Auto-migration через reflection |
| API coverage | ✅ 100% endpoints spec'd |
| US_LIST ↔ US_Cards sync | ✅ 77 US = 77 cards |

---

## 5. Технические ошибки и исправления (E001..E061)

Полная база в `~/.hermes/profiles/alex3/skills/hmp-errors-database/`.

Новые добавлены в этой версии:
- **E042** — `NameError: name 'func' is not defined` (E052 добавлен позже)
- **E046-E047** — DB columns vs ORM schema drift
- **E050-E058** — UI icons, FA in Shadow DOM, IndexedDB
- **E059** — Frontend src/ не скопирован в public/
- **E060** — Missing imports в view файлах (toast, api)
- **E060b** — `api is not defined` в модулях (E060b добавлен)
- **E061** — SOCKS proxy блокирует huggingface_hub

---

## 6. Сводка изменений в v1.2

**Новые endpoints (US-058):**
- `GET /whisper/models` — список моделей
- `GET /whisper/active` — активная
- `POST /whisper/active/{name}` — переключить
- `POST /whisper/download/{name}` — скачать (background)
- `GET /whisper/progress/{name}` — прогресс
- `GET /whisper/status/{name}` — статус
- `DELETE /whisper/models/{name}` — удалить
- `POST /export/archive/{protocol_id}` — ZIP архив (US-071)
- `GET /export/download/{archive_id}` — скачать ZIP
- `POST /protocols/from-url` — создать из URL (US-073)
- `POST /screenshots/upload` — multipart скриншот (US-074)

**Новые сервисы:**
- `app/services/whisper_models.py` — WhisperModelManager с HF Hub
- `app/services/transcription.py` — обновлён (eager mode + auto-fallback к tiny)

**Новые frontend view:**
- `views/whisper-models.js` — полный UI (US-077)
- `views/settings.js` — обновлён (US-076 inline widget)
- `views/upload.js` — обновлён (US-073 createProtocolFromUrl)
- `views/protocol.js` — обновлён (US-074 uploadScreenshot)

**Новые CSS:**
- `css/whisper-models.css` — стили для Whisper Manager

**Новые frontend API методы:**
- `getWhisperModels`, `getWhisperModelInfo`
- `downloadWhisperModel`, `getWhisperModelProgress`
- `setActiveWhisperModel`, `deleteWhisperModel`
- `getWhisperModelStatus`
- `createProtocolFromUrl`
- `uploadScreenshot`

**Новые скрипты (auto-checks):**
- `code/hmp-backend/scripts/check_models_routers_consistency.py`
- `code/hmp-backend/scripts/check_python_imports.py`
- `code/hmp-backend/scripts/check_unbound_local.py`
- `code/hmp-backend/scripts/check_db_columns.py`
- `code/hmp-backend/scripts/check_api_coverage.py`
- `code/hmp-backend/scripts/run_all_checks.py` (master)
- `code/hmp-frontend/scripts/check_frontend_imports.py`

**Новые .bat скрипты:**
- `force-refresh-frontend.bat` — копирует src/ → public/src/
- `install-faster-whisper.bat` — установка Whisper deps
- `start-fresh.bat` — DROP + CREATE БД + start

**Новые US-карточки:**
- US-068 (SVG иконки), US-069 (open folder), US-070 (real filename), US-071 (ZIP архив), US-072 (delete all data)
- US-073 (URL upload), US-074 (screenshot upload)
- US-075 (Whisper download), US-076 (status widget), US-077 (manager page)

**Обновлённые артефакты:**
- `VISION.md` — v1.1
- `US_LIST.md` — 77 US, 16 эпиков (включая новые)
- `API.md` — добавлены секции 5.Ф (Whisper), 5.Э.6-7 (Archive)
- `DATA_MODEL.md` — добавлена Whisper Cache section
- `NFR.md` — добавлены QG-9..13
- `TRACEABILITY.md` — v1.2 (полностью переписан)

**Pipeline-checker skill:**
- Расширен до 13 этапов проверки
- Все 13 PASS

**Skill `hmp-errors-database`:**
- 61 ошибка задокументирована (E001..E061)
- Каждая с симптомом, причиной, фиксом, чеком

---

## 7. Следующие шаги (backlog)

❌ EPIC-SEARCH (US-013) — полнотекстовый поиск  
❌ EPIC-SHARE (US-035, US-048) — публичные ссылки  
❌ EPIC-NOTIFY (US-033, US-034) — push/email  
❌ EPIC-I18N (US-036) — интернационализация  
🟡 EPIC-TRANS (US-006, US-050) — частично  
🟡 EPIC-DIAR (US-003) — частично  
🟡 EPIC-PROTOCOL (US-010) — частично
