# API Endpoints - HTML_MeetingProtokol

## ✅ Реализованные endpoints

### Health
- `GET /health` — simple health check
- `GET /health/deep` — detailed health check

### Protocols
- `GET /protocols` — list protocols
- `GET /protocols/{id}` — get protocol
- `POST /protocols` — create protocol (upload)
- `PATCH /protocols/{id}` — update protocol
- `DELETE /protocols/{id}` — soft delete

### Audio
- `GET /audio/{protocol_id}` — download audio
- `GET /audio/{protocol_id}/stream` — streaming

### Transcribe
- `POST /transcribe/{protocol_id}` — start transcription
- `GET /transcribe/{protocol_id}` — get status
- `POST /transcribe/{protocol_id}/cancel` — cancel
- `GET /transcribe/{protocol_id}/segments` — get segments

### Diarize
- `POST /diarize/{protocol_id}` — start diarization
- `GET /diarize/{protocol_id}` — get status

### Utterances
- `GET /utterances?protocol_id=X` — list (limit 1-500)
- `GET /utterances/{id}` — get one
- `PATCH /utterances/{id}/text` — correct text
- `PATCH /utterances/{id}/speaker` — assign speaker
- `GET /utterances/search?text=X` — full-text search
- `POST /utterances/bulk-update` — bulk update

### Speakers
- `GET /speakers?protocol_id=X` — list
- `PATCH /speakers/{id}` — update
- `DELETE /speakers/{id}` — delete
- `POST /speakers/{id}/merge` — merge speakers

### Calendar
- `GET /calendar?month=YYYY-MM` — month view

### Search
- `GET /search?q=X&protocol_id=Y` — global search

### Action Items
- `GET /action-items?protocol_id=X` — list
- `GET /action-items/{id}` — get one
- `POST /action-items` — create
- `PATCH /action-items/{id}` — update
- `DELETE /action-items/{id}` — delete

### Decisions
- `GET /decisions?protocol_id=X` — list
- `GET /decisions/{id}` — get one
- `DELETE /decisions/{id}` — delete

### Tags
- `GET /tags?protocol_id=X` — list
- `POST /tags` — create
- `DELETE /tags/{id}` — delete

### Screenshots
- `GET /screenshots?protocol_id=X` — list
- `GET /screenshots/{id}` — get one
- `POST /screenshots` — upload
- `DELETE /screenshots/{id}` — delete

### Summary
- `GET /protocols/{id}/summary` — get summary (404 if not generated)
- `POST /protocols/{id}/summary` — create/regenerate

### AI
- `POST /ai/summarize` — AI summarization
- `POST /ai/extract` — AI extraction
- `POST /ai/chat` — chat with AI
- `POST /ai/correct` — correct transcript

### Export
- `POST /export/docx` — start DOCX export
- `GET /export/{job_id}` — get export status
- `GET /export/{job_id}/download` — download DOCX

### Dictionary
- `GET /dictionary` — list terms
- `POST /dictionary` — add term
- `PATCH /dictionary/{id}` — update term
- `DELETE /dictionary/{id}` — delete term

### User Settings
- `GET /user-setting` — get current user settings
- `PATCH /user-setting` — update settings

### Live Mode
- `WS /live/{protocol_id}/stream` — WebSocket for live streaming
- `POST /live/start` — start live mode
- `POST /live/stop` — stop live mode

### Bot (Telegram)
- `POST /bot/users` — register bot user
- `GET /bot/users/{telegram_id}` — get bot user
- `PATCH /bot/users/{telegram_id}` — update
- `DELETE /bot/users/{telegram_id}` — delete
- `POST /bot/users/{telegram_id}/link` — link to web user
- `POST /bot/sessions` — create bot session
- `GET /bot/sessions/{token}` — get session
- `PATCH /bot/sessions/{token}` — update session
- `DELETE /bot/sessions/{token}` — close session

## ⚠️ Известные проблемы

### 422 на `GET /utterances?limit=N`
- Backend принимает `limit` от 1 до 500
- Frontend отправляет `limit=100` (в норме)
- 422 возникает периодически — проверьте Query параметры

### 404 на `GET /protocols/{id}/summary`
- Нормальное поведение если саммари ещё не создано
- Для создания используйте `POST /protocols/{id}/summary`

## 🚀 Полный список

Swagger UI: http://127.0.0.1:8000/docs

**Всего: 65+ endpoints**
