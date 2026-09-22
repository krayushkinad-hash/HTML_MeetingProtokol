# HTML_MeetingProtokol

Локальное приложение для ведения базы протоколов совещаний с хронологической историей, транскрипцией аудио/видео, идентификацией ораторов и AI-саммари.

> **Версия:** v1.1 (2026-09-21)
> **Эпиков:** 15 | **US:** 72 | **Размер кодовой базы:** ~25 000 строк

---

## 🎯 Назначение

Приложение для профессионалов, которые ведут протоколы совещаний. Позволяет:

- Загружать аудио/видео записи совещаний
- Автоматически транскрибировать речь (Whisper)
- Идентифицировать ораторов (NeMo Sortformer / pyannote)
- Генерировать саммари и action items (Hermes/GigaChat)
- Экспортировать протоколы в DOCX
- Хранить всё локально (152-ФЗ: 0 байт утечки в базовом сценарии)

---

## 🛠 Стек

### Backend
- **Python 3.10+**
- **FastAPI 0.115** — REST API
- **PostgreSQL 15** — хранение данных (в Docker)
- **SQLAlchemy 2.0 + asyncpg** — ORM
- **Alembic** — миграции БД
- **structlog** — структурированное логирование
- **Whisper (large-v3)** — транскрипция
- **NeMo Sortformer / pyannote.audio** — диаризация

### Frontend
- **Vanilla JS (ES2020+)** — без фреймворков
- **CSS3** — кастомные стили
- **Font Awesome 6.5** — иконки
- **IndexedDB** — локальный кэш
- **Fetch API + XHR** — HTTP-клиент

### DevOps
- **Docker Compose** — PostgreSQL
- **uvicorn** — ASGI-сервер с reload
- **pyproject.toml** — управление зависимостями

---

## 📁 Структура

```
HTML_MeetingProtokol/
├── README.md                       ← этот файл
├── artifacts/                      ← артефакты пайплайна (Vision → US → Код)
│   ├── 01-vision/                  ← Vision-документ
│   ├── 02-personas/                ← архетипы пользователей
│   ├── 03-user-stories/
│   │   ├── 1_us_list/US_LIST.md    ← перечень всех 72 US
│   │   └── 2_us_cards/US_NNN.md    ← детальные US-карточки
│   ├── 04-processes/               ← BPMN-диаграммы
│   ├── 05-forms/                   ← спецификации форм
│   ├── 06-screens/                 ← карта экранов
│   ├── 07-data-model/              ← модель данных
│   ├── 08-nfr/                     ← нефункциональные требования
│   ├── 09-api/                     ← спецификация REST API
│   ├── 10-traceability/            ← матрица трассировки US↔код
│   └── 11-architecture/            ← C4-диаграммы + ADR
│
├── code/
│   ├── hmp-backend/                ← FastAPI приложение
│   │   ├── app/
│   │   │   ├── core/               ← config, middleware, security
│   │   │   ├── db/                 ← SQLAlchemy models, session
│   │   │   ├── routers/            ← 20+ endpoint модулей
│   │   │   ├── schemas/            ← Pydantic модели
│   │   │   ├── services/           ← бизнес-логика
│   │   │   └── main.py             ← entrypoint
│   │   ├── scripts/                ← утилиты (auto-migration, verify)
│   │   └── tests/                  ← pytest
│   └── hmp-frontend/               ← Vanilla JS приложение
│       ├── public/                 ← static (index.html, favicon)
│       └── src/
│           ├── css/                ← стили
│           └── js/                 ← модули
│
├── scripts/                        ← PowerShell скрипты установки
├── deploy/                         ← Docker / systemd / k8s конфиги
└── legacy/                         ← старая версия (vanilla HTML-only, до v1.0)
    └── src/                        ← исходники v0.x
```

---

## 🚀 Быстрый старт (Windows)

### 1. Распаковать архив

```powershell
Rename-Item C:\HTML_Protokol C:\HTML_Protokol_OLD -ErrorAction SilentlyContinue
Expand-Archive .\HTML_MeetingProtokol-v1.0.0.zip -DestinationPath C:\ -Force
cd C:\HTML_Protokol
```

### 2. Запустить

```cmd
.\restart.bat
```

Автоматически:
- Запускает PostgreSQL (Docker)
- Запускает FastAPI backend на `http://127.0.0.1:8000`
- Запускает frontend HTTP-сервер на `http://127.0.0.1:5173`
- Открывает браузер

### 3. Открыть в браузере

```
http://127.0.0.1:5173/
```

---

## 🔧 Ежедневное использование

| Команда | Что делает |
|---|---|
| `start.bat` | Запустить backend + frontend |
| `stop.bat` | Остановить |
| `restart.bat` | Перезапустить (с auto-обновлением frontend) |
| `force-refresh-frontend.bat` | Копировать `src/*` → `public/src/` |
| `kill-all-nuclear.bat` | Убить все Python процессы |
| `test-endpoints.bat` | Проверить все API endpoints |

### Диагностика и устранение проблем

| Скрипт | Назначение |
|---|---|
| `cleanup-docker.ps1` | Полная очистка Docker (контейнеры, образы, volumes) |
| `fix-install.ps1` | Восстановление после сбоя установки |
| `fix-wsl-nowsl.ps1` | Конвертация WSL-путей в Windows и обратно |
| `install-docker-only.ps1` | Установка только Docker без Python |
| `resume-install.ps1` | Продолжить установку после сбоя |
| `deploy-windows.ps1` | Production-деплой на Windows-сервере |

---

## 🔍 Автоматические проверки

```bash
# E020: проверить что все callback-функции определены
python code/hmp-frontend/scripts/verify_callbacks.py verify

# E016-E019: проверить согласованность моделей и роутеров
python code/hmp-backend/scripts/check_models_routers_consistency.py

# Список бэкапов JS файлов
python code/hmp-frontend/scripts/verify_callbacks.py list

# Восстановить из бэкапа
python code/hmp-frontend/scripts/verify_callbacks.py restore --from backup_20260921_192100
```

Подробности — в skill `hmp-errors-database`.

---

## 📊 Архитектура

### Высокоуровневая

```
┌─────────────────┐    HTTP     ┌──────────────────┐
│   Browser       │ ──────────► │ Frontend:5173    │
│  (User Interface)│             │ (Vanilla JS)     │
└─────────────────┘             └────────┬─────────┘
                                         │ fetch
                                         ▼
                                ┌──────────────────┐
                                │ Backend:8000     │
                                │ (FastAPI)        │
                                └────────┬─────────┘
                                         │ asyncpg
                                         ▼
                                ┌──────────────────┐
                                │ PostgreSQL:5432  │
                                │ (Docker)         │
                                └──────────────────┘
                                         │
                                         ▼
                                ┌──────────────────┐
                                │ ~/.html_mp/      │
                                │ (файлы протоколов)│
                                └──────────────────┘
```

### Детально — см. `artifacts/11-architecture/`

- `diagrams/` — 11 PNG (C4, ADR, sequence)
- `ARCHITECTURE.md` — полное описание
- `ARCHITECTURE.docx` — версия для печати

---

## 📋 Pipeline (Vision → Production)

1. **Vision** → `artifacts/01-vision/`
2. **Personas** → `artifacts/02-personas/`
3. **User Stories** → `artifacts/03-user-stories/` (72 US, 15 эпиков)
4. **Business Processes** → `artifacts/04-processes/` (BPMN)
5. **Forms** → `artifacts/05-forms/`
6. **Screens** → `artifacts/06-screens/`
7. **Data Model** → `artifacts/07-data-model/` (18 таблиц)
8. **NFR** → `artifacts/08-nfr/`
9. **API** → `artifacts/09-api/`
10. **Traceability** → `artifacts/10-traceability/` (US ↔ код)
11. **Architecture** → `artifacts/11-architecture/`
12. **CODE** → `code/hmp-backend/`, `code/hmp-frontend/`

---

## 🔐 Безопасность

- Все данные хранятся локально (152-ФЗ)
- API доступен только с `127.0.0.1` (не сетевой)
- Токены — в `.env` (НЕ в коде, НЕ в git)
- Авто-миграция БД — при каждом старте backend
- Подробнее — `artifacts/09-api/API.md` (§ Аутентификация)

---



---

## 🔧 Устранение проблем

### Backend не запускается

```cmd
# 1. Проверить PostgreSQL
docker ps

# 2. Посмотреть логи backend
type C:\HTML_Protokol\logsackend.log

# 3. Убить все процессы и перезапустить
cd C:\HTML_Protokol
.\kill-all-nuclear.bat
.\restart.bat
```

### Frontend не обновляется

```cmd
# Принудительно пересобрать
.\force-refresh-frontend.bat

# В браузере — Ctrl+F5 (сброс кэша)
```

### Docker завис / порт занят

```powershell
# Очистить всё
.\cleanup-docker.ps1

# Убить процессы
.\kill-all-nuclear.bat

# Перезапустить
.\restart.bat
```

### Проверить работу API

```cmd
.\test-endpoints.bat
```

Откроет Swagger UI на http://127.0.0.1:8000/docs

## 📂 legacy/

Старая версия (`v0.x`) — полностью Vanilla HTML, без backend. Не используется в текущей версии v1.0+.

```
legacy/
├── src/    ← исходники (dev) — 7 файлов
└── dist/   ← собранная версия (production) — 9 файлов
```

### Пересборка dist из src

```cmd
cd legacy\src
python -m http.server 8001
# Открыть http://localhost:8001/index.html
```

**Структура dist/:** добавлены `calendar.html`, `live.html`, `assets/` — production-страницы.

---

## 📄 Документация

- **`artifacts/01-vision/VISION.md`** — что и зачем
- **`artifacts/03-user-stories/1_us_list/US_LIST.md`** — перечень US
- **`artifacts/03-user-stories/2_us_cards/US_NNN.md`** — детальные карточки
- **`artifacts/07-data-model/DATA_MODEL.md`** — модель данных
- **`artifacts/08-nfr/NFR.md`** — нефункциональные требования
- **`artifacts/09-api/API.md`** — спецификация REST API
- **`artifacts/10-traceability/TRACEABILITY.md`** — что реализовано
- **`artifacts/11-architecture/ARCHITECTURE.md`** — архитектура

---

## 📜 Лицензия

[Внутренний продукт]

---

**Версия документа:** 2026-09-21
