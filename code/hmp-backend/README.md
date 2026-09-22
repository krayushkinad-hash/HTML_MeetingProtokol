# HTML_MeetingProtokol Backend

Backend для локального приложения протоколов совещаний.

**Стек:** Python 3.11+, FastAPI 0.115+, SQLAlchemy 2.x, PostgreSQL 15
**Архитектура:** см. `/artifacts/11-architecture/ARCHITECTURE.md`
**API:** см. `/artifacts/09-api/API.md`
**Модель данных:** см. `/artifacts/07-data-model/DATA_MODEL.md`

---

## 🚀 Quick Start

### 1. Системные требования

- **Python 3.11+**
- **PostgreSQL 15+** (или SQLite для разработки)
- **FFmpeg** (для декодирования видео)
- **CUDA GPU** (опционально, для ускорения Whisper)
- **8+ GB RAM** (для Whisper Large-v3)
- **8+ GB VRAM** (для GPU-режима)

### 2. Установка

```bash
# 1. Клонировать проект
cd hmp-backend

# 2. Скопировать env
cp .env.example .env
# Отредактировать .env — задать DATABASE_URL, ENCRYPTION_MASTER_KEY

# 3. Установить зависимости
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# или .venv\Scripts\activate  # Windows

pip install -e ".[dev]"

# 4. Поднять PostgreSQL через Docker
docker-compose up -d postgres

# 5. Применить миграции
alembic upgrade head

# 6. Запустить backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Открыть в браузере:
- **API docs:** http://127.0.0.1:8000/docs
- **Health check:** http://127.0.0.1:8000/health
- **ReDoc:** http://127.0.0.1:8000/redoc

### 3. Через Docker Compose (полный стек)

```bash
docker-compose up -d
# Backend + PostgreSQL + (опционально Ollama)
```

---

## 📁 Структура проекта

```
hmp-backend/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── core/                # Config, logging, middleware, monitoring
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── logging_config.py # structlog
│   │   ├── middleware.py    # CorrelationIdMiddleware, ProblemDetailsMiddleware
│   │   └── monitoring.py    # RSSMonitor (NFR §QG-7)
│   ├── db/                  # SQLAlchemy
│   │   ├── session.py       # AsyncSessionLocal
│   │   └── models.py        # 17 ORM models
│   ├── schemas/             # Pydantic schemas (request/response)
│   ├── services/            # Business logic
│   │   ├── transcription.py # Whisper integration (ADR-005)
│   │   └── llm_client.py    # Hermes/GigaChat/Ollama (ADR-004)
│   ├── routers/             # FastAPI routers (API endpoints)
│   │   ├── health.py
│   │   ├── protocols.py     # CRUD протоколов
│   │   ├── audio.py
│   │   ├── transcribe.py
│   │   ├── diarize.py
│   │   ├── utterances.py
│   │   ├── speakers.py
│   │   ├── calendar.py
│   │   ├── search.py
│   │   ├── actions.py
│   │   ├── decisions.py
│   │   ├── tags.py
│   │   ├── screenshots.py
│   │   ├── summary.py
│   │   ├── ai.py
│   │   ├── export.py
│   │   ├── dictionary.py
│   │   ├── user_setting.py
│   │   ├── live.py
│   │   └── bot.py
│   └── utils/               # Утилиты
├── alembic/                 # Database migrations
│   ├── env.py
│   └── versions/
├── tests/                    # pytest tests
├── infra/                    # Infrastructure configs
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml          # Зависимости + настройки инструментов
├── alembic.ini
├── .env.example
└── README.md
```

---

## 🔧 Разработка

### Линтинг и форматирование

```bash
# Ruff (линтер + форматтер)
ruff check app tests --fix
ruff format app tests

# Type checking
mypy app

# Pre-commit hooks
pre-commit install
pre-commit run --all-files
```

### Тестирование

```bash
# Все тесты
pytest

# С coverage
pytest --cov=app --cov-report=html

# Только unit-тесты
pytest tests/unit

# Только integration
pytest tests/integration
```

### Миграции БД

```bash
# Создать новую миграцию после изменения models.py
alembic revision --autogenerate -m "Add new field"

# Применить
alembic upgrade head

# Откатить
alembic downgrade -1

# История
alembic history
```

### Логи

Логи выводятся в stdout в структурированном JSON (для production):

```json
{
  "timestamp": "2026-09-14T20:00:00.123Z",
  "level": "info",
  "correlation_id": "550e8400-...",
  "method": "POST",
  "path": "/api/v1/hmp/protocols",
  "status": 201,
  "duration_ms": 145,
  "app": "HTML_MeetingProtokol API",
  "version": "1.0.0",
  "env": "development"
}
```

Для разработки используется pretty-print (цветной вывод).

---

## 🛡️ Безопасность

- **Шифрование токенов** (ADR-014): AES-256-GCM с мастер-ключом из `ENCRYPTION_MASTER_KEY`
- **Локальный backend** (ADR-007): только `127.0.0.1:8000`, нет remote access
- **Whitelist для Telegram-бота** (ADR-013): по `telegram_id`
- **TLS 1.3** для внешних вызовов (Hermes, GigaChat, Telegram, cloud storage)
- **CORS** настроен только для localhost origins

⚠️ **Перед production:**
1. Сгенерировать `ENCRYPTION_MASTER_KEY`:
   ```bash
   python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
   ```
2. Изменить пароль PostgreSQL (`POSTGRES_PASSWORD` в `docker-compose.yml`)
3. Установить `DEBUG=false` в `.env`
4. Установить `APP_ENV=production` в `.env`

---

## 📊 Мониторинг

### Health endpoints

```bash
# Simple
curl http://127.0.0.1:8000/health

# Deep check (DB + disk + RSS)
curl http://127.0.0.1:8000/health/deep
```

### Метрики RSS (NFR §QG-7)

В background работает `RSSMonitor`. При превышении 80% от лимита (4096 МБ по умолчанию) транскрипция автоматически паузится.

Логи покажут:
```json
{"level": "warning", "event": "rss_pause", "rss_mb": 3500.0, "threshold_mb": 3277.6}
```

---

## 🧪 Стек

| Компонент | Технология | ADR |
|---|---|---|
| Framework | FastAPI 0.115+ | ADR-001 |
| Database | PostgreSQL 15 + SQLAlchemy 2.x | ADR-002 |
| Transcription | faster-whisper (large-v3) | ADR-005 |
| Diarization | pyannote.audio 3.1 | — |
| LLM | Hermes (priority) / GigaChat (fallback) / Ollama (local) | ADR-004 |
| DOCX export | python-docx | ADR-011 |
| Encryption | cryptography (AES-256-GCM) | ADR-014 |
| Observability | structlog + Prometheus | — |
| Memory monitor | psutil | ADR-010 |

---

## 📞 Поддержка

- 📄 Архитектура: `../artifacts/11-architecture/ARCHITECTURE.md`
- 📄 API: `../artifacts/09-api/API.md`
- 📄 NFR: `../artifacts/08-nfr/NFR.md`
- 📄 Data Model: `../artifacts/07-data-model/DATA_MODEL.md`

---

## 📝 Лицензия

Proprietary. © 2026 Алексей Краюшкин.
