# SCAFFOLD REPORT: hmp-backend

**Дата:** 2026-09-14
**Версия:** 1.0.0
**Стек:** Python 3.11+ / FastAPI / SQLAlchemy 2.x / PostgreSQL 15

## 1. Обзор

- Проект: **hmp-backend**
- Расположение: `/root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend`
- Архитектурный стиль: 2-tier монолит (ADR-007)
- Всего файлов: **58**
  - Python: 43
  - Markdown: 2
  - YAML: 1
  - Общий размер: **310.5 КБ**

## 2. Структура папок

```
hmp-backend/
├── alembic/
│   ├── versions/
│   │   ├── .gitkeep (0.0 KB)
│   │   └── 0001_initial.py (4.3 KB)
│   ├── env.py (1.9 KB)
│   └── script.py.mako (0.6 KB)
├── app/
│   ├── core/
│   │   ├── __init__.py (0.0 KB)
│   │   ├── config.py (3.6 KB)
│   │   ├── logging_config.py (1.9 KB)
│   │   ├── middleware.py (2.3 KB)
│   │   └── monitoring.py (3.0 KB)
│   ├── db/
│   │   ├── __init__.py (0.2 KB)
│   │   ├── models.py (25.8 KB)
│   │   └── session.py (2.0 KB)
│   ├── models/
│   ├── routers/
│   │   ├── __init__.py (0.0 KB)
│   │   ├── actions.py (8.3 KB)
│   │   ├── ai.py (7.5 KB)
│   │   ├── audio.py (7.4 KB)
│   │   ├── bot.py (14.0 KB)
│   │   ├── calendar.py (1.8 KB)
│   │   ├── decisions.py (6.5 KB)
│   │   ├── diarize.py (5.7 KB)
│   │   ├── dictionary.py (7.8 KB)
│   │   ├── export.py (10.6 KB)
│   │   ├── health.py (1.4 KB)
│   │   ├── live.py (7.1 KB)
│   │   ├── protocols.py (8.2 KB)
│   │   ├── screenshots.py (8.9 KB)
│   │   ├── search.py (4.7 KB)
│   │   ├── speakers.py (7.6 KB)
│   │   ├── summary.py (8.2 KB)
│   │   ├── tags.py (4.6 KB)
│   │   ├── transcribe.py (11.4 KB)
│   │   ├── user_setting.py (4.5 KB)
│   │   └── utterances.py (12.2 KB)
│   ├── schemas/
│   │   └── __init__.py (10.1 KB)
│   ├── services/
│   │   ├── __init__.py (0.1 KB)
│   │   ├── llm_client.py (5.9 KB)
│   │   └── transcription.py (2.8 KB)
│   ├── utils/
│   ├── __init__.py (0.1 KB)
│   └── main.py (4.8 KB)
├── diagrams/
├── docs/
├── infra/
│   ├── migrations/
│   │   └── 0001_initial.sql (14.5 KB)
│   └── postgres-init/
│       └── 01-extensions.sql (0.3 KB)
├── logs/
│   └── .gitkeep (0.0 KB)
├── scripts/
│   ├── generate_schema.py (2.8 KB)
│   └── init_db.sh (0.5 KB)
├── tests/
│   ├── __init__.py (0.0 KB)
│   ├── conftest.py (1.4 KB)
│   ├── test_llm_client.py (3.2 KB)
│   ├── test_monitoring.py (1.4 KB)
│   └── test_smoke.py (1.5 KB)
├── .env.example (2.6 KB)
├── .gitignore (0.4 KB)
├── Dockerfile (0.9 KB)
├── README.md (7.4 KB)
├── SCAFFOLD_REPORT.docx (42.1 KB)
├── SCAFFOLD_REPORT.md (9.3 KB)
├── alembic.ini (0.8 KB)
├── docker-compose.yml (1.3 KB)
└── pyproject.toml (2.5 KB)
```

## 3. Стек и зависимости

| Компонент | Технология | ADR |
|---|---|---|
| Backend framework | FastAPI 0.115+ | ADR-001 |
| ASGI server | Uvicorn | — |
| ORM | SQLAlchemy 2.x (async) | ADR-002 |
| Database | PostgreSQL 15 | ADR-002 |
| Migrations | Alembic | — |
| Transcription | faster-whisper (large-v3) | ADR-005 |
| Diarization | pyannote.audio 3.1+ | — |
| LLM (priority) | Hermes API | ADR-004 |
| LLM (fallback) | GigaChat API (ФСТЭК) | ADR-004 |
| LLM (local) | Ollama (опционально) | ADR-004 |
| Encryption | cryptography (AES-256-GCM) | ADR-014 |
| DOCX export | python-docx | ADR-011 |
| Memory monitor | psutil | ADR-010 |
| Logging | structlog | NFR §9.3 |
| Testing | pytest + pytest-asyncio | — |
| Linting | ruff + mypy | — |

## 4. Реализованные компоненты

### 4.1. App Factory (`app/main.py`)
- ✅ FastAPI app factory с lifespan
- ✅ CORS middleware
- ✅ CorrelationIdMiddleware (NFR §5.9)
- ✅ ProblemDetailsMiddleware (RFC 7807)
- ✅ RSSMonitor startup/shutdown (NFR §QG-7)
- ✅ 20 роутеров (все подключены)

### 4.2. Core (`app/core/`)
- ✅ `config.py` — pydantic-settings, все env-переменные
- ✅ `logging_config.py` — structlog, JSON в production / pretty в dev
- ✅ `middleware.py` — X-Correlation-Id + Problem Details
- ✅ `monitoring.py` — RSSMonitor с auto-pause при 80% RAM

### 4.3. Database (`app/db/`)
- ✅ `session.py` — async engine, AsyncSession, lifespan hooks
- ✅ `models.py` — все **17 ORM моделей** по DATA_MODEL.md:
  - UserSetting, AudioFile, Protocol, VoiceProfile, Speaker,
  - Utterance, Screenshot, Decision, ActionItem, Tag,
  - Summary, ProtocolVersion, DiarizationResult, Dictionary,
  - ApiUser, CommandLog, ExportTask

### 4.4. Schemas (`app/schemas/`)
- ✅ 40+ Pydantic schemas (request/response)
- ✅ ProblemDetails (RFC 7807)
- ✅ Pagination, PaginatedResponse
- ✅ Все CRUD-модели + специализированные (SummarizeRequest, ExportRequest, ...)

### 4.5. Services (`app/services/`)
- ✅ `transcription.py` — Whisper integration с lazy-loading
- ✅ `llm_client.py` — абстракция LLM с fallback (Hermes → GigaChat)

### 4.6. Routers (`app/routers/`) — 20 шт
**Реализованы полностью:**
- ✅ `health.py` — `/health`, `/health/deep`
- ✅ `protocols.py` — CRUD с загрузкой файлов (multipart, chunk 8MB)

**Заготовки (TODO: реализация по API.md):**
- ⏳ `audio.py`
- ⏳ `transcribe.py`
- ⏳ `diarize.py`
- ⏳ `utterances.py`
- ⏳ `speakers.py`
- ⏳ `calendar.py`
- ⏳ `search.py`
- ⏳ `actions.py`
- ⏳ `decisions.py`
- ⏳ `tags.py`
- ⏳ `screenshots.py`
- ⏳ `summary.py`
- ⏳ `ai.py`
- ⏳ `export.py`
- ⏳ `dictionary.py`
- ⏳ `user_setting.py`
- ⏳ `live.py`
- ⏳ `bot.py`

## 5. Миграции Alembic

- ✅ `alembic.ini` сконфигурирован
- ✅ `alembic/env.py` использует async engine и `Base.metadata`
- ✅ `alembic/script.py.mako` шаблон для новых миграций
- ⏳ Создать первую миграцию: `alembic revision --autogenerate -m "initial"`

## 6. Docker

- ✅ `Dockerfile` — multi-stage (хотя упрощённый single-stage)
- ✅ `docker-compose.yml` — PostgreSQL + Backend + (profile) Ollama
- ✅ `infra/postgres-init/01-extensions.sql` — uuid-ossp, pg_trgm

## 7. Тесты

- ✅ `tests/test_smoke.py` — базовый smoke-тест
- ⏳ Добавить: test_protocols, test_transcription, test_ai (по NFR §13)

## 8. Инструкция по запуску

### 8.1. Локальный запуск (рекомендуется для разработки)
```bash
cd code/hmp-backend

# Создать venv и установить зависимости
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Настроить .env
cp .env.example .env
# Отредактировать DATABASE_URL, ENCRYPTION_MASTER_KEY

# Поднять PostgreSQL
docker-compose up -d postgres

# Применить миграции
alembic upgrade head

# Запустить backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Тестирование
pytest
```

### 8.2. Полный стек через Docker
```bash
cd code/hmp-backend
docker-compose up -d  # Backend + PostgreSQL
# С Ollama:
docker-compose --profile with-ollama up -d
```

### 8.3. Проверка
```bash
# Health
curl http://127.0.0.1:8000/health

# Deep health
curl http://127.0.0.1:8000/health/deep

# OpenAPI docs (только в DEBUG=true)
open http://127.0.0.1:8000/docs
```

## 9. Связь с другими артефактами

- **API:** `../artifacts/09-api/API.md` — спецификация всех эндпоинтов
- **Data Model:** `../artifacts/07-data-model/DATA_MODEL.md` — 17 таблиц
- **NFR:** `../artifacts/08-nfr/NFR.md` — SLA, latency, security
- **Architecture:** `../artifacts/11-architecture/ARCHITECTURE.md` — ADR, диаграммы
- **Traceability:** `../artifacts/10-traceability/TRACEABILITY.md` — US ↔ API ↔ таблицы

## 10. Следующие шаги

1. ⏳ **Реализовать остальные 18 роутеров** по `API.md` (US-001..051)
2. ⏳ Создать первую Alembic миграцию: `alembic revision --autogenerate -m "initial"`
3. ⏳ Написать тесты: `pytest tests/` (NFR §QG-11 — coverage ≥70%)
4. ⏳ Запустить `alembic upgrade head` и проверить `psql \dt`
5. ⏳ Добавить кэш (Redis) при необходимости
6. ⏳ Настроить CI/CD через GitHub Actions

## 11. Готовность к реализации

| Компонент | Готовность |
|---|---|
| Конфигурация / Settings | ✅ 100% |
| Логирование (structlog) | ✅ 100% |
| Middleware (Correlation, Problem) | ✅ 100% |
| ORM-модели (17 таблиц) | ✅ 100% |
| Alembic setup | ✅ 100% (env, ini, mako) |
| Pydantic schemas (40+) | ✅ 100% |
| LLM client (Hermes + GigaChat + Ollama) | ✅ 100% (с fallback) |
| Whisper service (lazy-load) | ✅ 80% (нужен chunk loop) |
| Health endpoints | ✅ 100% |
| Protocols CRUD | ✅ 100% (полная реализация) |
| Остальные 18 роутеров | ⏳ 5% (заготовки с TODO) |
| Docker / Compose | ✅ 100% |
| Тесты | ⏳ 10% (только smoke) |
| **Общая готовность** | **~60%** |