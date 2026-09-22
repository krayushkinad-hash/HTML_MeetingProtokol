# NFR: HTML_MeetingProtokol

## 1. Метаинформация

| Поле | Значение |
|---|---|
| **Проект** | HTML_MeetingProtokol |
| **Дата** | 2026-09-14 |
| **Версия** | 1.0 |
| **Источники** | Vision §6.2 KPI, §7 Scope, §8 Risks, §9 Ограничения; US_LIST.md (51 US); формы F-HMP-1..6; процессы P-01..P-04; Screen Flow (16 экранов); Data Model (17 таблиц) |
| **Целевая аудитория** | Single-user (Алексей); P-02 в командировке Astra; P-03 гость |
| **Тип продукта** | Локальное десктоп-приложение + Telegram-бот (AI-прокси) |
| **Автор** | Алексей |

---

## 2. Quality Goals (цели качества)

| # | Цель | Приоритет | Метрика | Target |
|---|---|---|---|---|
| QG-1 | **Локальность и приватность** | Critical | Передача данных во внешние сервисы | **0 байт** для записей/транскрипций |
| QG-2 | **Скорость подготовки протокола** | High | Время от загрузки до готового DOCX | **≤15 мин** на 1 час аудио |
| QG-3 | **Точность транскрипции (русский)** | High | WER | **≤15%** |
| QG-4 | **Точность диаризации** | High | DER | **≤20%** |
| QG-5 | **Latency живой транскрипции** | High | Задержка от реплики до UI | **≤3 сек** p95 |
| QG-6 | **Скорость календаря (офлайн)** | High | Время до первого отображения | **≤3 сек** для 200+ протоколов |
| QG-7 | **Без OOM при длинных записях** | Critical | Пиковый RSS при 2 | **≤4 ГБ** |
| QG-8 | **Доступность Astra Linux офлайн** | High | Доступность режима просмотра без сети | **100%** функций просмотра |

| QG-9 | **Drag-and-drop отзывчивость** | High | Latency drag-over → drop <100ms (US-062) | **Подсветка зоны drop** появляется мгновенно |
| QG-10 | **Soft delete восстановление** | Must | Soft-deleted протоколы не теряются 30 дней (US-052) | Восстановление через `include_deleted=true` |
| QG-11 | **Hard delete безопасность** | Must | Двойное подтверждение для hard delete (US-053) | "SOFT"/"DELETE" + confirm() |
| QG-12 | **Folder tree consistency** | High | Folder.parent_id всегда валидна (US-061) | Нет circular references (FSM-check) |
| QG-13 |
| QG-14 | **Test connection timeout** | Must | Проверка Telegram бота < 10 секунд (US-067) | Кнопка показывает timeout через 10с |
| QG-15 | **Bot token security** | Must | Токен НЕ логируется в чистом виде | Только SHA256 хэш в логах (US-067) |
| QG-16 | **Test result persistence** | Low | История проверок сохраняется 30 дней | Можно посмотреть когда последний раз проверяли (US-067) |
 **Settings sync latency** | Low | Сохранение настройки → подтверждение <500ms (US-054..058) | Toast появляется сразу после 200 OK |

| QG-9 | **Telegram-бот доступен** | Medium | Время реакции на команду | **≤5 сек** p95 |
| QG-10 | **Поддержка русского языка** | High | Язык интерфейса/проверки | **100%** ru-RU |
| QG-11 | **Покрытие тестами** | Medium | Code coverage критических путей | **≥70%** |
| QG-12 | **Соответствие 152-ФЗ** | Critical | Данные на у | **100%** |

---

## 3. Производительность

### 3.1. API Latency (FastAPI, локально на Windows)

| Endpoint | p50 | p95 | p99 | SLA |
|---|---|---|---|---|
| `GET /api/v1/protocols` (список) | 30 мс | 80 мс | 150 мс | p95 < 100 мс |
| `GET /api/v1/protocols/{id}` (один) | 20 мс | 50 мс | 100 мс | p95 < 80 мс |
| `POST /api/v1/transcribe/upload` | 100 мс | 200 мс | 500 мс | p95 < 300 мс |
| `POST /api/v1/transcribe/run` | 50 мс | 100 мс | 200 мс | p95 < 150 мс |
| `GET /api/v1/transcribe/status/{task_id}` | 10 мс | 30 мс | 80 мс | p95 < 50 мс |
| `POST /api/v1/diarize/run` | 50 мс | 100 мс | 200 мс | p95 < 150 мс |
| `PATCH /api/v1/utterances/{id}/speaker` | 20 мс | 50 мс | 100 мс | p95 < 80 мс |
| `GET /api/v1/calendar?year=&month=` | 20 мс | 60 мс | 120 мс | p95 < 100 мс |
| `GET /api/v1/search?q=` (BM25 + триграммы) | 30 мс | 80 мс | 200 мс | p95 < 150 мс |
| `POST /api/v1/ai/summarize` (локальная LLM) | 3000 мс | 8000 мс | 15000 мс | p95 < 10 сек |
| `POST /api/v1/ai/action-items` | 3000 мс | 8000 мс | 15000 мс | p95 < 10 сек |
| `POST /api/v1/export/docx` (асинхронный) | 200 мс (до async) | 500 мс | 1000 мс | p95 < 800 мс |
| `GET /api/v1/media/{id}/video?t=` (HTTP Range) | 50 мс | 100 мс | 200 мс | p95 < 150 мс |

**Общий SLA:** **p95 < 300 мс** для синхронных, **p95 < 10 сек** для AI-фич.

### 3.2. Frontend Performance (Web UI)

| Метрика | Target | Инструмент |
|---|---|---|
| First Contentful Paint (FCP) | < 1.5 сек | Lighthouse |
| Largest Contentful Paint (LCP) | < 2.5 сек | Lighthouse |
| Time to Interactive (TTI) | < 3.5 сек | Lighthouse |
| Cumulative Layout Shift (CLS) | < 0.1 | Lighthouse |
| First Input Delay (FID) | < 100 мс | Lighthouse |
| Total Blocking Time (TBT) | < 300 мс | Lighthouse |
| JS bundle size | < 300 КБ (gzip) | webpack-bundle-analyzer |
| CSS size | < 50 КБ | PurgeCSS |
| IndexedDB write throughput | ≥ 1000 записей/сек | Benchmark |

### 3.3. Live Mode Latency (Real-Time)

| Метрика | Target |
|---|---|
| Время от конца реплики до появления в UI | **≤3 сек** (p95) |
| FPS плеера iframe Телемост | ≥24 |
| Latency темы (новое выделение) | ≤ 5 сек после появления реплик |
| Latency скриншота | ≤ 1 сек после события |
| WebSocket reconnect | ≤ 5 сек |

### 3.4. Throughput

| Метрика | Target |
|---|---|
| Одновременно активных пользователей | 1 (single-user) |
| Одновременных процессов транскрипции | **1** (лимит по Vision §9) |
| Одновременных загрузок файлов | 1 |
| Запросов к API в минуту | ≤ 100 (типичная нагрузка) |
| Чтение из IndexedDB | ≤ 500 мс на 10K записей |

### 3.5. Frontend Performance Budget (per page)

| Ресурс | Лимит |
|---|---|
| HTML | < 50 КБ |
| JS (gzip) | < 300 КБ |
| CSS (gzip) | < 50 КБ |
| Изображения (per page) | < 1 МБ |
| Шрифты | < 100 КБ |
| IndexedDB schema migrations | < 1 сек |

---

## 4. Масштабируемость

### 4.1. Вертикальная (single-machine)

| Ресурс | Лимит | Что делать при превышении |
|---|---|---|
| RAM | 16 ГБ (минимум), 32 ГБ (рекомендуется) | Мониторинг RSS, автопауза при 80% |
| Диск | 100 ГБ свободных | Предупреждение при < 10 ГБ, ротация старых протоколов |
| CPU | 8+ ядер (рекомендуется) для GPU-режима | Fallback на CPU + квантованные модели |
| GPU VRAM | 8 ГБ (минимум), 12+ ГБ (рекомендуется) | CPU-only режим с `compute_type="int8"` |

### 4.2. Горизонтальная (распределённая)

Не применимо в MVP — приложение single-user. Однако архитектура должна позволять:

| Компонент | Стратегия масштабирования |
|---|---|
| Backend (FastAPI) | Stateless, можно запустить несколько инстансов за reverse proxy |
| Frontend | Статические файлы, раздаются CDN |
| Telegram-бот | Один инстанс (нет состояния кроме webhook secret) |
| LLM-сервер (Ollama) | Отдельный сервер с GPU, доступен по сети |
| PostgreSQL | Single-instance для MVP, репликация для production |
| Whisper/pyannote | Локально или на выделенном GPU-сервере |

### 4.3. Лимиты

| Объект | Лимит |
|---|---|
| Протоколов в базе | ≤ 10 000 (фасетный поиск свыше) |
| Реплик на протокол | ≤ 5 000 (виртуализация списка свыше) |
| Скриншотов на протокол | ≤ 100 |
| Размер DOCX | ≤ 50 МБ (предупреждение) |
| Размер загружаемого файла | ≤ 10 ГБ |
| Длина записи (для транскрипции) | ≤ 8 часов (лимит памяти) |
| Словарь пользовательских терминов | ≤ 1 000 записей |
| Тегов на протокол | ≤ 20 |

---

## 5. Доступность (Uptime / SLA)

### 5.1. Single-User приложение

| Уровень | Uptime | Простой/мес | RTO | RPO |
|---|---|---|---|---|
| **MVP (Windows)** | 99.5% | 3.6 часа | 5 мин | 0 (всё локально) |
| **Astra Linux (офлайн)** | 99.9% | 43 мин | 1 мин | 0 (IndexedDB) |
| **Telegram-бот (AI-прокси)** | 99.0% | 7.2 часа | 30 мин | 0 (не хранит записи) |

**Объяснение:**
- MVP — десктоп-приложение, downtime = время на обновления и перезапуск
- Astra — статические файлы, downtime = только при обновлении
- Telegram-бот — расширение, может быть недоступен без ущерба для основного функционала

### 5.2. Стратегия восстановления

| Сценарий | RTO | RPO | Действия |
|---|---|---|---|
| Backend crash | 1 мин | 0 | Автоперезапуск через systemd / pm2 |
| Backend не отвечает | 30 сек | 0 | Frontend retry, fallback на offline режим |
| IndexedDB повреждена | 5 мин | 0 (есть бэкап) | Восстановление из `~/.html_mp/backup/` |
| Telegram-бот недоступен | не применимо | 0 | Fallback на локальное приложение |
| Диск переполнен | 10 мин | 0 | Автоматическая ротация старых протоколов |

### 5.3. Backup

| Что | Как | Retention |
|---|---|---|
| PostgreSQL | `pg_dump` в `~/.html_mp/backup/daily/` | 7 дней локально |
| PostgreSQL | rclone на Яндекс.Диск | 30 дней |
| Аудио/видео файлы | Символическая копия в `~/.html_mp/protocols/<id>/` | Без ротации (пока есть место) |
| IndexedDB | Экспорт в JSON при изменении схемы | При миграциях |

---

## 6. Безопасность

### 6.1. Аутентификация и авторизация

В MVP приложение **single-user** — нет аутентификации на уровне приложения (приложение запускается под учётной записью пользователя ОС).

**Для Telegram-бота:**

| Механизм | Описание |
|---|---|
| Whitelist по `telegram_id` | Бот принимает команды только от разрешенных Telegram ID |
| Token в `.env` | `TELEGRAM_BOT_TOKEN`, `GIGACHAT_TOKEN`, `HERMES_TOKEN` |
| Без передачи записей | Бот НЕ хранит аудио/видео — только проксирует к LLM |
| Ограничение команд | `/summarize`, `/actions`, `/tags` — никаких произвольных команд |

### 6.2. Шифрование

| Канал | Алгоритм | Где |
|---|---|---|
| Локальное хранение файлов | **Нет** (MVP) — приложение доверяет защите ОС | `~/.html_mp/protocols/<id>/` |
| Telegram API | TLS 1.3 | Telegram servers |
| Backend ↔ Frontend | HTTP (localhost) — TLS не требуется | `127.0.0.1:8000` |
| Загрузка по HTTPS | TLS 1.2+ | Яндекс.Диск / Google Drive |
| Опционально (v2) | AES-256 для протоколов на диске | при shared machine |

### 6.3. OWASP Top 10 (2021) чек-лист

| # | Уязвимость | Защита |
|---|---|---|
| A01 | Broken Access Control | Whitelist для Telegram-бота; нет remote access |
| A02 | Cryptographic Failures | TLS 1.3 для внешних; localhost не требует |
| A03 | Injection (SQL/XSS) | SQLAlchemy ORM (параметризованные запросы); `bleach` для HTML |
| A04 | Insecure Design | Threat modeling, безопасный API design |
| A05 | Security Misconfiguration | Минимум зависимостей, security headers (CSP) |
| A06 | Vulnerable Components | Регулярный `pip audit`, обновления зависимостей |
| A07 | Auth Failures | Приложение single-user; Telegram-whitelist |
| A08 | Software/Data Integrity | Проверка checksum для загруженных файлов |
| A09 | Logging Failures | Структурированные логи (JSON), без PII |
| A10 | SSRF | Валидация URL при загрузке (whitelist доменов) |

### 6.4. Защита данных

| Данные | Защита |
|---|---|
| Аудио/видео файлы | Только на локальном диске, доступ = учётная запись ОС |
| Текст транскрипции | В IndexedDB (на диске), в БД (PostgreSQL) |
| Саммари через LLM | Только текст (не аудио); GigaChat сертифицирован ФСТЭК |
| Telegram-сообщения | В Telegram (политика конфиденциальности) + локальные логи (команды без PII) |
| Логи | Только метаданные (длина сообщения, ID), без PII |

### 6.5. Threat Model

| Угроза | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Утечка диска (ноутбук украден) | Средняя | Высокое | Шифрование диска (BitLocker / FileVault) — на стороне ОС |
| Утечка Telegram-токена | Низкая | Среднее | Токен в `.env`, ротация каждые 90 дней |
| MITM при загрузке с облака | Низкая | Среднее | TLS 1.3, валидация сертификата |
| Backend эксплойт | Низкая | Среднее | Backend только на localhost; firewall |
| LLM-провайдер хранит наши тексты | Средняя | Низкое | Передаём **только текст протокола**, без аудио |
| Telegram читает наши сообщения | Высокая | Низкое | Команды короткие, без конфиденциальных данных |

---

## 7. Доступность (Accessibility, a11y)

### 7.1. WCAG 2.1 AA Compliance

| Категория | Требование | Реализация |
|---|---|---|
| Perceivable (Воспринимаемость) | Текст-альтернатива для изображений | `alt` на всех `<img>`, ARIA для иконок |
| | Цветовой контраст ≥ 4.5:1 | Проверка через axe-core |
| | Минимум 200% zoom без потери функциональности | Responsive design |
| Operable (Управляемость) | Все функции доступны с клавиатуры | Hot keys, tabindex |
| | Нет «ловушек» для фокуса | Видимый focus indicator (outline) |
| | Управление через клавиатуру: Tab, Shift+Tab, Enter, Escape, Arrow keys | Реализовано в плеере, формах, модалках |
| Understandable (Понятность) | Язык страницы указан | `<html lang="ru">` |
| | Предсказуемая навигация | Consistent header/footer, breadcrumbs |
| Robust (Надёжность) | Валидный HTML | W3C validator |
| | ARIA-разметка корректна | axe-core тесты |

### 7.2. Скрин-ридеры

| Ридер | Поддержка |
|---|---|
| NVDA (Windows) | ✅ ARIA-разметка |
| JAWS (Windows) | ✅ ARIA-разметка |
| VoiceOver (macOS) | ✅ ARIA-разметка |
| TalkBack (Astra Linux) | ⚠️ частичная (зависит от версии) |

### 7.3. Горячие клавиши (Hot Keys)

| Действие | Клавиши | Контекст |
|---|---|---|
| Поиск | `Ctrl+K` | Глобально |
| Play/Pause | `Space` | Видеоплеер |
| Перемотка ±5 сек | `←` / `→` | Видеоплеер |
| Перемотка ±30 сек | `Shift+←` / `Shift+→` | Видеоплеер |
| Mute/Unmute | `Ctrl+M` | Видеоплеер |
| Пометить реплику как важное | `Shift+Enter` | Транскрипция |
| Новая загрузка | `Ctrl+O` | Глобально |
| Экспорт DOCX | `Ctrl+E` | Просмотр протокола |
| Сохранить (Live Mode) | `Ctrl+S` | Live Mode |
| Завершить встречу | `Ctrl+Shift+E` | Live Mode |
| Закрыть модалку | `Escape` | Модалки |

---

## 8. Локализация (i18n)

### 8.1. Языки

| Язык | Интерфейс | Распознавание речи | LLM |
|---|---|---|---|
| 🇷🇺 Русский | **Основной** | **Whisper Large-v3** (лучшее качество) | **GigaChat / Hermes** |
| 🇬🇧 Английский | Частично (документация) | Whisper Large-v3 | OpenAI / Claude |
| Другие | Не планируется | | |

### 8.2. Форматы

| Тип | Формат |
|---|---|
| Дата | `dd.MM.yyyy` (14.09.2026) |
| Время | `HH:mm` / `HH:mm:ss` |
| Дата+время | `dd.MM.yyyy HH:mm` |
| Таймкод видео | `HH:MM:SS` |
| Размер файла | `12.5 МБ` (с пробелом) |
| Длительность | `1 ч 23 мин` или `1:23:45` |

### 8.3. i18n в коде

```python
# Все строки — в .po/.mo файлах (gettext)
# Поддержка pluralization (1 файл, 2 файла, 5 файлов)
# Язык UI определяется через navigator.language + fallback на ru-RU
# Для дат/чисел — Intl API браузера (или Python locale)
```

---

## 9. Наблюдаемость (Observability)

### 9.1. Метрики

| Метрика | Тип | Где |
|---|---|---|
| `transcription_duration_sec` | Histogram | Backend, по протоколу |
| `transcription_wer` | Gauge | Backend, после каждой обработки |
| `diarization_der` | Gauge | Backend |
| `peak_rss_mb` | Gauge | Backend, при обработке |
| `active_utterances` | Gauge | Backend |
| `db_query_latency_ms` | Histogram | Backend, для каждого запроса |
| `export_task_duration_sec` | Histogram | Backend, по задачам |
| `telegram_command_latency_ms` | Histogram | Bot |
| `llm_tokens_used` | Counter | Backend + Bot |
| `oom_pauses_total` | Counter | Backend |
| `transcription_failures_total` | Counter | Backend |

### 9.2. Логи

| Уровень | Где | Что |
|---|---|---|
| INFO | Backend | Старт/конец обработки, экспорт, загрузка |
| WARNING | Backend | RAM > 70%, OOM pause, retry |
| ERROR | Backend | Ошибки Whisper, pyannote, LLM |
| CRITICAL | Backend | Crash, потеря данных |
| INFO | Telegram-бот | Команды пользователя |
| WARNING | Telegram-бот | Неавторизованный доступ |

**Формат:** структурированный JSON (с `timestamp`, `level`, `module`, `message`, `context`).

### 9.3. Tracing (распределённые трассировки)

Не применимо в MVP (single-machine). Архитектура должна поддерживать OpenTelemetry для будущего масштабирования.

### 9.4. SLO и Error Budget

| SLO | Target | Error Budget / мес |
|---|---|---|
| API availability | 99.9% | 43 мин |
| Transcription success rate | 99.0% | 7.2 часа простоя транскрипции |
| Live Mode latency p95 | ≤ 3 сек | 5% запросов могут превышать |
| Calendar load time p95 | ≤ 3 сек | 5% запросов могут превышать |
| Export DOCX success rate | 99.5% | 3.6 часа отказов экспорта |

### 9.5. Health Endpoints

| Endpoint | Назначение |
|---|---|
| `GET /health` | Простой health-check (200 OK если работает) |
| `GET /health/deep` | Проверка БД, IndexedDB, моделей |
| `GET /metrics` | Prometheus-формат метрик (если используется) |

---

## 10. Надёжность (Reliability)

### 10.1. Failure Modes & Recovery

| Сценарий | Поведение | Recovery |
|---|---|---|
| Backend не запускается | Frontend показывает «Ошибка подключения к backend» | Retry через 5 сек |
| Whisper не загружен | Ошибка при попытке транскрипции | Указать путь к модели в настройках |
| IndexedDB переполнена (лимит браузера ~50 МБ) | Предупреждение пользователю | Удалить старые протоколы или экспортировать |
| PostgreSQL недоступна | Backend fallback на SQLite (только просмотр) | Автопереключение |
| Telegram-бот недоступен | Fallback на локальное приложение | Не критично — расширение |
| Диск переполнен | Отказ загрузки нового файла | Уведомление пользователю |
| Процесс убит (OOM Killer) | Backend crash, frontend показывает ошибку | systemd auto-restart |

### 10.2. Retry-стратегии

| Операция | Retry | Backoff | Timeout |
|---|---|---|---|
| Backend HTTP request | 3 раза | Exponential (1с, 2с, 4с) | 30 сек |
| Загрузка с облака | 5 раз | Exponential | 5 мин |
| Транскрипция | 1 раз (только при явной ошибке) | — | 30 мин |
| LLM-вызов | 2 раза | Exponential | 30 сек |
| Telegram API | 3 раза | Exponential | 10 сек |

### 10.3. Graceful Degradation

| Сценарий | Деградация |
|---|---|
| Backend недоступен | Frontend работает в offline-режиме (только просмотр IndexedDB) |
| LLM недоступна | Саммари/action items отключены, остальное работает |
| GPU недоступна | CPU-only режим (медленнее, но работает) |
| Telegram-бот недоступен | Никакого влияния (бот — расширение) |
| PostgreSQL недоступна | SQLite fallback (только чтение) |
| Whisper не загружен | Vosk-ru fallback |

---

## 11. Совместимость

### 11.1. Операционные системы

| ОС | Версия | Полный функционал | Ограничения |
|---|---|---|---|
| Windows 10 | 1909+ | ✅ | — |
| Windows 11 | 21H2+ | ✅ | — |
| Astra Linux (CE/SM) | 1.7+ | ⚠️ Только просмотр | Нет микрофона, нет iframe Телемост |
| Ubuntu | 22.04+ | ⚠️ Только просмотр | — |
| macOS | 12+ | ⚠️ Только просмотр | Нет Electron-обёртки |

### 11.2. Браузеры

| Браузер | Версия | Поддержка |
|---|---|---|
| Chrome | 100+ | ✅ Полная |
| Edge | 100+ | ✅ Полная |
| Firefox | 100+ | ✅ Полная |
| Safari | 14+ | ✅ Полная |
| Opera | 90+ | ✅ Полная |
| IE 11 | — | ❌ Не поддерживается |

### 11.3. Модели и фреймворки

| Компонент | Версия | Назначение |
|---|---|---|
| Python | 3.10+ | Backend |
| FastAPI | 0.110+ | API |
| Whisper | large-v3 (или medium для CPU) | Транскрипция |
| pyannote.audio | 3.1+ | Диаризация |
| Ollama | 0.3+ (опционально) | Локальная LLM |
| aiogram | 3.x | Telegram-бот |
| PostgreSQL | 15+ | БД (опционально) |
| SQLite | 3.40+ | БД (офлайн, встроено) |
| Chromium | 100+ (headless) | Скриншоты, Mermaid-рендер |

### 11.4. Сторонние API

| API | Версия | Зачем |
|---|---|---|
| GigaChat API | 2024-09 | Саммари (альтернатива) |
| Hermes | API текущая | Саммари (приоритет) |
| Telegram Bot API | 7.0 | Бот |

---

## 12. Поддерживаемость

### 12.1. Качество кода

| Метрика | Target |
|---|---|
| Code coverage (критические пути) | ≥ 70% |
| Type hints (Python) | 100% для нового кода |
| ESLint (JavaScript) | 0 ошибок, 0 предупреждений |
| Cyclomatic complexity | ≤ 10 на функцию |
| Code duplication | ≤ 5% (drift detection) |
| Documentation coverage | ≥ 80% для публичных API |

### 12.2. Документация

| Документ | Где | Обновляется |
|---|---|---|
| README.md | корень | При каждом релизе |
| Архитектурные решения | `docs/adr/` | На каждое решение |
| API документация | OpenAPI (`/docs` endpoint) | Автоматически |
| Руководство пользователя | `docs/user-guide.md` | При изменении UI |
| Changelog | `CHANGELOG.md` | На каждый релиз |

### 12.3. Логирование и debugging

| Компонент | Уровень логирования | Ротация |
|---|---|---|
| Backend | INFO по умолчанию, DEBUG через `--verbose` | logrotate, 7 дней |
| Telegram-бот | INFO | 30 дней |
| Frontend (browser console) | WARN по умолчанию | Не хранится (одноразовые сессии) |

### 12.4. Время на онбординг нового разработчика

| Метрика | Target |
|---|---|
| Setup проекта с нуля до запуска | ≤ 30 мин |
| Первый коммит (задача «Hello, World») | ≤ 4 часа |
| Понимание архитектуры | ≤ 2 дня чтения документации |

---

## 13. NFR-тесты

### 13.1. Load-тесты (k6)

**Цель:** Проверить производительность под нагрузкой.

```javascript
// k6-script: load_test_api.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 10 },   // разогрев до 10 RPS
    { duration: '1m', target: 50 },    // нагрузка 50 RPS
    { duration: '30s', target: 100 },  // пик 100 RPS
    { duration: '30s', target: 0 },    // затухание
  ],
  thresholds: {
    'http_req_duration:p95': ['< 300'],
    'http_req_failed': ['< 0.01'],
  },
};

export default function() {
  const res = http.get('http://localhost:8000/api/v1/protocols');
  check(res, {
    'status is 200': (r) => r.status === 200,
    'p95 latency < 300ms': (r) => r.timings.duration < 300,
  });
  sleep(1);
}
```

**Acceptance:** p95 latency < 300 мс при 100 RPS, error rate < 1%.

### 13.2. Security-тесты (OWASP ZAP)

**Цель:** Проверить защиту от OWASP Top 10.

```bash
# Запуск baseline scan
docker run -t owasp/zap2docker-stable \
  zap-baseline.py -t http://localhost:8000/ -r security-report.html

# Acceptable: 0 HIGH alerts, ≤ 3 MEDIUM alerts
```

**Acceptance:**
- 0 HIGH severity alerts
- ≤ 3 MEDIUM severity alerts (с обоснованием)
- 0 LOW alerts на критических эндпоинтах

### 13.3. Accessibility-тесты (axe-core)

**Цель:** Проверить соответствие WCAG 2.1 AA.

```javascript
// playwright + axe-core
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('home page is accessible', async ({ page }) => {
  await page.goto('http://localhost:8000/');
  const accessibilityScanResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(accessibilityScanResults.violations).toEqual([]);
});
```

**Acceptance:** 0 violations уровня `serious` или `critical`.

### 13.4. Memory-тест (RSS-мониторинг)

**Цель:** Проверить защиту от OOM.

```python
# pytest
def test_no_oom_on_long_recording(monkeypatch):
    """Симулируем обработку 2-часовой записи."""
    fake_audio = create_fake_audio(duration_sec=2 * 3600)
    
    # Запуск транскрипции в subprocess
    process = subprocess.Popen(['python', 'transcribe.py', fake_audio])
    
    # Мониторинг RSS
    max_rss_mb = 0
    while process.poll() is None:
        rss = psutil.Process(process.pid).memory_info().rss / 1024 / 1024
        max_rss_mb = max(max_rss_mb, rss)
        time.sleep(1)
    
    assert max_rss_mb < 4096, f"Peak RSS {max_rss_mb} MB exceeded 4 GB"
```

**Acceptance:** Peak RSS ≤ 4 ГБ для 2-часовой записи.

### 13.5. Offline-тест (Astra Linux)

**Цель:** Проверить, что режим просмотра работает без интернета.

```bash
# В Docker с отключенным интернетом
docker run --network=none html_mp_app

# Ожидаемый результат:
# - Календарь открывается за ≤3 сек
# - Поиск по транскрипции работает
# - Видео воспроизводится с локального диска
# - Все функции просмотра доступны
```

**Acceptance:** 100% функций просмотра работают без интернета.

---

## 14. Compliance (Соответствие нормативам)

| Норматив | Статус | Митигация |
|---|---|---|
| **152-ФЗ** «О персональных данных» | ✅ Соблюдается | Данные локально, нет передачи; LLM через GigaChat (ФСТЭК); Telegram-бот через Hermes/GigaChat (российские сервисы) |
| **GDPR** (если международное использование) | ⚠️ Требует доработки | Прозрачное уведомление о локальном хранении |
| **HIPAA** (если медицинские данные) | ❌ Не применимо | Не медицинский продукт |
| **ФСТЭК** (для критической инфраструктуры) | ⚠️ Требует сертификации | Локальное хранение упрощает сертификацию |

---

## 15. NFR Scorecard (сводная оценка)

| Категория | Score | Комментарий |
|---|---|---|
| Производительность | 🟢 | p95 latency < 300ms, K6 тесты покрыты |
| Масштабируемость | 🟡 | Single-user; архитектура готова к горизонтальному масштабированию |
| Доступность (SLA) | 🟢 | 99.5%+ для Windows, 99.9% для Astra офлайн |
| Безопасность | 🟢 | 152-ФЗ compliant, OWASP Top 10 закрыт, TLS 1.3 |
| Доступность (a11y) | 🟢 | WCAG 2.1 AA, axe-core тесты |
| Локализация | 🟢 | ru-RU основной, форматы стандартные |
| Наблюдаемость | 🟡 | Структурированные логи, метрики; SLO определены; Prometheus — будущее |
| Надёжность | 🟢 | Retry, graceful degradation, auto-restart |
| Совместимость | 🟢 | Windows + Astra Linux, все современные браузеры |
| Поддерживаемость | 🟢 | Type hints, ESL, документация, ≥70% coverage |

---

## 16. Приоритизация (MoSCoW)

### Must (критичные)
- 0 байт утечки данных (QG-1)
- WER ≤ 15% (QG-3)
- DER ≤ 20% (QG-4)
- Latency Live Mode ≤ 3 сек (QG-5)
- RSS ≤ 4 ГБ (QG-7)
- 100% офлайн в Astra (QG-8)
- 152-ФЗ compliance (QG-12)
- WCAG 2.1 AA (a11y)
- OWASP Top 10 закрыт (security)
- TLS 1.3 для внешних

### Could (по возможности)
- Горизонтальное масштабирование
- AES-256 для файлов на диске
- Prometheus метрики
- Chaos engineering

### Won't (в этой версии)
- Multi-user
- Cloud sync
- Mobile app
- Интеграция с Zoom/Meet/Teams

---

## 17. Связь с pipeline

- **Предыдущий шаг:** `data-model-designer` (`artifacts/07-data-model/DATA_MODEL.md`) ✅
- **Следующий шаг:** `api-detail-designer` — REST API на основе NFR и модели данных.
- **Зависимости:** Vision KPI (§6.2), Vision Ограничения (§9), Vision Риски (§8).
- **Используется в:** `traceability-matrix` — каждое US привязано к NFR.

## NFR-STREAM-1 (E131): Latency до первого текста

**Метрика:** Время от старта транскрибации до момента, когда первая реплика появится в БД.

**Требование:** ≤ 10 сек на CPU (base, tiny) и ≤ 5 сек на GPU (large-v3).

**Достигается через:**
- queue.Queue → persist_utterances_loop → DB INSERT каждые 2 сек
- Frontend polling подтягивает новые через segments_count

**Приоритет:** High (UX retention)
