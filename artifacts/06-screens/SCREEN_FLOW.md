# Screen Flow: HTML_MeetingProtokol

## 1. Метаинформация

| Поле | Значение |
|---|---|
| **Проект** | HTML_MeetingProtokol |
| **Дата** | 2026-09-14 |
| **Источники** | artifacts/03-user-stories/1_us_list/US_LIST.md, artifacts/05-forms/, artifacts/04-processes/PROCESSES.md |
| **Персон** | 3 (P-01, P-02, P-03) |
| **Экранов** | 16 |
| **Сценариев** | 8 |
| **State-диаграмм** | 4 |
| **Автор** | Алексей |

---

## 2. Карта экранов

| ID | Экран | Форма / Тип | Платформа | Роли | Описание |
|---|---|---|---|---|---|
| S-001 | Home | Главная страница | Windows, Astra | P-01, P-02 | Навигация: список протоколов, календарь, Live Mode |
| S-002 | ProtocolList | FORM_PROTOCOL_LIST (нет спецификации — список) | Windows, Astra | P-01, P-02 | Хронологический список всех протоколов |
| S-003 | UploadForm | FORM_UPLOAD (F-HMP-1) | Windows | P-01 | Загрузка локального файла или по HTTPS-ссылке |
| S-004 | ProtocolView | FORM_PROTOCOL_VIEW (F-HMP-2) | Windows, Astra | P-01, P-02, P-03 | Просмотр протокола: видео, реплики, метаданные |
| S-005 | CalendarView | FORM_CALENDAR_VIEW (F-HMP-3) | Windows, Astra | P-01, P-02 | Календарь прошлых встреч (день/неделя/месяц) |
| S-006 | TranscriptView | FORM_TRANSCRIPT_VIEW (F-HMP-4) | Windows, Astra | P-01, P-02 | Список реплик с таймкодами, фильтры, поиск |
| S-007 | SpeakerEditor | Модальное окно | Windows | P-01 | Ручная корректировка меток ораторов |
| S-008 | TranscriptEditor | Модальное окно | Windows | P-01 | Ручная правка текста реплик |
| S-009 | ExportDialog | FORM_EXPORT_DIALOG (F-HMP-5) | Windows | P-01 | Настройка и запуск экспорта DOCX |
| S-010 | LiveMode | FORM_LIVE_MODE (F-HMP-6) | Windows | P-01 | Три панели: видео + темы + живая транскрипция |
| S-011 | SummaryButton | Модальное окно | Windows | P-01 | Саммари встречи через локальную LLM |
| S-012 | ActionItems | Модальное окно | Windows | P-01 | Список action items, сгенерированных AI |
| S-013 | TagEditor | Модальное окно | Windows | P-01 | Ручное тегирование протокола |
| S-014 | SearchBar | Глобальный компонент | Windows, Astra | P-01, P-02 | Поиск по всем протоколам |
| S-015 | OfflineIndicator | Глобальный компонент | Astra | P-02 | Индикатор офлайн-режима |
| S-016 | PrivacyBadge | Компонент в шапке | Windows | P-01, P-03 | Индикатор «Данные хранятся локально» |

**Всего экранов:** 16

### Распределение по типам

| Тип | Количество |
|---|---|
| Главная страница | 1 (S-001) |
| Формы (содержательные экраны) | 6 (S-003, S-004, S-005, S-006, S-009, S-010) |
| Модальные окна | 5 (S-007, S-008, S-011, S-012, S-013) |
| Глобальные компоненты | 3 (S-014, S-015, S-016) |
| Списки | 1 (S-002) |

---

## 3. UI-flow (основной граф навигации)

```mermaid
flowchart LR
    Start([Старт]) --> Home
    Home --> ProtocolList
    Home --> CalendarView
    Home --> UploadForm
    Home --> LiveMode

    ProtocolList --> ProtocolView
    ProtocolList --> UploadForm
    ProtocolList --> ExportDialog

    CalendarView --> ProtocolView

    ProtocolView --> ExportDialog
    ProtocolView --> SpeakerEditor
    ProtocolView --> TranscriptEditor
    ProtocolView --> SummaryButton
    ProtocolView --> ActionItems
    ProtocolView --> TagEditor
    ProtocolView --> TranscriptView

    TranscriptView --> ProtocolView

    UploadForm --> ProtocolView

    LiveMode --> ProtocolView

    SpeakerEditor --> ProtocolView
    TranscriptEditor --> ProtocolView
    SummaryButton --> ProtocolView
    ActionItems --> ProtocolView
    TagEditor --> ProtocolView
    ExportDialog --> Done([DOCX готов])
    ExportDialog --> ProtocolView

    Home --> SearchBar
    SearchBar --> ProtocolView

    subgraph "Глобальные компоненты"
        PrivacyBadge
        OfflineIndicator
    end
```

**Описание UI-flow:**
- **S-001 Home** — точка входа для всех сценариев.
- **S-002 ProtocolList, S-005 CalendarView** — две независимые навигации к протоколу (список или календарь).
- **S-003 UploadForm** — единственный путь для создания нового протокола.
- **S-010 LiveMode** — отдельный режим для онлайн-встреч; после завершения редирект на S-004 ProtocolView.
- **S-004 ProtocolView** — главный «хаб» для всех операций над протоколом (просмотр, экспорт, правка, AI).
- **S-007..S-013** — модальные окна для действий над протоколом; всегда возвращаются в S-004.
- **S-009 ExportDialog** — единственный путь к результату «DOCX готов».

---

## 4. Sequence-диаграммы по сценариям

### 4.1. SC-01: Загрузка локального файла (US-001)

```mermaid
sequenceDiagram
    actor User as Алексей (P-01)
    participant UI as UploadForm
    participant Storage as IndexedDB
    participant FS as Файловая система
    participant Backend as FastAPI

    User->>UI: Клик «Загрузить файл»
    UI->>User: Открыть диалог выбора
    User->>UI: Выбран meeting.mp4 (500 MB)
    UI->>UI: Проверка расширения и размера
    alt Файл > 2 ГБ
        UI->>User: Предупреждение + подтверждение
        User->>UI: «Да, продолжить»
    end
    UI->>Backend: POST /api/v1/transcribe/upload (multipart)
    Backend->>FS: Потоковое сохранение chunk 8MB
    FS-->>Backend: Файл сохранён в protocols/<id>/source.mp4
    Backend->>Storage: Создание записи протокола
    Storage-->>Backend: protocol_id
    Backend-->>UI: 200 OK { protocol_id, status: loaded }
    UI->>User: Редирект на ProtocolView
```

### 4.2. SC-02: Загрузка по HTTPS-ссылке (US-002)

```mermaid
sequenceDiagram
    actor User as Алексей (P-01)
    participant UI as UploadForm
    participant Backend as FastAPI
    participant Cloud as Яндекс.Диск

    User->>UI: Вставить HTTPS-ссылку
    UI->>UI: Валидация URL и домена
    UI->>Backend: POST /api/v1/transcribe/from-url
    Backend->>Cloud: HEAD (проверка Content-Length)
    Cloud-->>Backend: 2.5 GB
    alt Content-Length > 2 ГБ
        Backend->>UI: Предупреждение
        UI->>User: «Продолжить?»
        User->>UI: «Да»
    end
    Backend->>Cloud: GET (chunked download)
    Cloud-->>Backend: 2.5 GB поток
    Backend->>Backend: Сохранение chunk ≤ 8 MB на диск
    Backend->>UI: 200 OK { protocol_id, status: downloading }
    loop Каждые 200 мс
        UI->>Backend: GET /progress/{task_id}
        Backend-->>UI: { percent: 45 }
    end
    Backend->>UI: { status: loaded }
    UI->>User: Редирект на ProtocolView
```

### 4.3. SC-03: Транскрипция и диаризация (US-005, US-007)

```mermaid
sequenceDiagram
    participant UI as ProtocolView
    participant Backend as FastAPI
    participant Whisper as Whisper Large-v3
    participant Pyannote as pyannote
    participant Monitor as RSS Monitor

    UI->>Backend: POST /api/v1/transcribe/run { protocol_id }
    Backend->>Backend: Аудио → 16 kHz mono
    Backend->>Monitor: Старт мониторинга RSS

    loop По 30 сек аудио
        Backend->>Whisper: Чанк аудио
        Whisper->>Whisper: Распознавание (fp16, beam=1)
        Whisper-->>Backend: { text, start, end, words }
        Backend->>Monitor: RSS check
        alt RSS > 80%
            Monitor->>Backend: Warning
            Backend->>Backend: Переключение на chunk 10 сек
        end
        Backend->>UI: WebSocket: utterance
    end

    Backend->>Pyannote: Полное аудио + embeddings
    Pyannote->>Pyannote: Speaker diarization
    Pyannote-->>Backend: { speaker_id per word }
    Backend->>UI: WebSocket: транскрипция + ораторы готовы
    UI->>UI: Отрисовка реплик с цветовыми метками
```

### 4.4. SC-04: Просмотр протокола в Astra Linux офлайн (US-027)

```mermaid
sequenceDiagram
    actor User as Алексей (P-02)
    participant UI as CalendarView
    participant Storage as IndexedDB
    participant FS as Файловая система

    User->>UI: Открыть HTML_MeetingProtokol
    UI->>Storage: Загрузка всех протоколов из IndexedDB
    Storage-->>UI: 200 протоколов за ≤ 1 сек
    UI->>UI: Отрисовка календаря (≤3 сек до первого отображения)

    User->>UI: Клик по дате 25 августа
    UI->>UI: Подгрузка списка встреч за день
    UI-->>User: Показ 3 встреч

    User->>UI: Клик по встрече с Заказчик-X
    UI->>Storage: Загрузка utterances и speakers
    Storage-->>UI: Полная транскрипция
    UI->>FS: Запрос видео (file://)
    FS-->>UI: Видеопоток

    User->>UI: Поиск «срок»
    UI->>UI: Фильтрация реплик локально (≤300 мс)
    UI-->>User: Подсветка совпадений

    User->>UI: Клик по реплике
    UI->>FS: video.currentTime = 14:23
    FS-->>UI: Видео воспроизводится с 14:23
```

### 4.5. SC-05: Live Mode (Яндекс Телемост) (US-019, US-020)

```mermaid
sequenceDiagram
    actor Алексей as P-01
    actor Гость as P-03
    participant LiveMode as LiveMode (3 панели)
    participant Telemost as Яндекс Телемост (iframe)
    participant WS as WebSocket /ws/live
    participant Whisper as Whisper streaming
    participant LLM as Локальная LLM

    Алексей->>LiveMode: Вставить URL Телемост
    LiveMode->>Telemost: iframe embed (Левая панель)
    LiveMode->>LiveMode: Запрос микрофона (getUserMedia)

    par Поток аудио в реальном времени
        loop Каждые 0.5 сек
            Whisper->>WS: chunk аудио
            WS->>Whisper: streaming recognition
            Whisper-->>WS: { text, start, end }
            WS->>LiveMode: utterance (latency ≤3 сек)
            LiveMode->>LiveMode: Подсветка активной реплики
        end
    and Авто-выделение тем
        loop Каждые 30 сек
            LiveMode->>LLM: «Выдели темы из последних 10 реплик»
            LLM-->>LiveMode: [«бюджет Q4», «сроки MVP»]
            LiveMode->>LiveMode: Обновление центральной панели
        end
    and Захват экрана
        loop Каждые 60 сек (если включено)
            LiveMode->>getDisplayMedia: screenshot
            LiveMode->>IndexedDB: Сохранение скриншота
        end
    end

    Гость->>Telemost: Говорит
    note over Гость, LiveMode: Реплики появляются в реальном времени
```

### 4.6. SC-06: Ручная правка ораторов (US-008)

```mermaid
sequenceDiagram
    actor Алексей as P-01
    participant UI as ProtocolView
    participant Modal as SpeakerEditor
    participant Backend as FastAPI
    participant Storage as IndexedDB

    UI->>Алексей: Ошибка: SPEAKER_01 перепутан с SPEAKER_02
    Алексей->>UI: Клик «Редактировать ораторов»
    UI->>Modal: Открытие модального окна
    Modal->>Storage: Загрузка utterances + speakers
    Storage-->>Modal: список
    Modal-->>Алексей: Таблица реплик с выпадающим списком ораторов

    Алексей->>Modal: Выбрать «SPEAKER_01 = Сидорова А.»
    Алексей->>Modal: Клик «Применить»
    Modal->>Backend: PATCH /api/v1/utterances/utt-002/speaker
    Backend->>Backend: Сохранение голосового профиля Сидоровой
    Backend-->>Modal: 200 OK
    Modal->>Storage: Обновление IndexedDB
    Modal-->>Алексей: Тост «Оратор обновлён для N реплик»
```

### 4.7. SC-07: Экспорт DOCX со скриншотами (US-015, US-016, US-017)

```mermaid
sequenceDiagram
    actor Алексей as P-01
    participant Dialog as ExportDialog
    participant Backend as FastAPI
    participant DB as IndexedDB
    participant Files as Файловая система

    Алексей->>Dialog: Открыть экспорт
    Dialog->>DB: Загрузка метаданных протокола
    DB-->>Dialog: title, date, speakers, screenshots_count
    Dialog-->>Алексей: Оценка размера DOCX

    Алексей->>Dialog: Выбрать параметры
    Алексей->>Dialog: Клик «Экспортировать»
    Dialog->>Backend: POST /api/v1/export/docx
    Backend->>Backend: Запуск фоновой задачи (asyncio)
    Backend-->>Dialog: 202 { task_id }

    loop Каждые 500 мс
        Dialog->>Backend: GET /api/v1/exports/{task_id}/status
        Backend-->>Dialog: { percent: 35, status: processing }
    end

    Backend->>Backend: Формирование DOCX (python-docx, Краюшкин)
    Backend->>Files: Сохранение DOCX в exports/<id>/
    Backend->>Files: Копирование screenshots
    Backend->>Backend: Добавление гиперссылок на видео
    Backend->>DB: Обновление статуса
    Backend-->>Dialog: { status: completed, file_size: 5.2 MB }
    Dialog->>Алексей: Зелёный тост «DOCX готов»
    Алексей->>Dialog: Клик «Скачать»
    Dialog->>Backend: GET /api/v1/exports/{task_id}/download
    Backend-->>Dialog: DOCX-файл
```

### 4.8. SC-08: AI-саммари + action items (US-022, US-023)

```mermaid
sequenceDiagram
    actor Алексей as P-01
    participant UI as ProtocolView
    participant LLM as Ollama (локальная)
    participant Backend as FastAPI
    participant DB as IndexedDB

    Алексей->>UI: Клик «Саммари»
    UI->>Backend: POST /api/v1/ai/summarize { protocol_id }
    Backend->>Backend: Загрузка всех utterances (≤4096 токенов)
    Backend->>LLM: Prompt: «Сделай краткое резюме встречи»
    LLM->>LLM: num_ctx=4096, num_batch=128
    LLM-->>Backend: summary (2-3 параграфа)
    Backend->>DB: Сохранение summary
    Backend-->>UI: { summary: "..." }
    UI-->>Алексей: Отображение саммари в начале протокола

    Алексей->>UI: Клик «Action items»
    UI->>Backend: POST /api/v1/ai/action-items
    Backend->>LLM: Prompt: «Извлеки задачи (кто/что/когда)»
    LLM-->>Backend: [ { owner: "Петров", task: "Отправить отчёт", deadline: "15.09" } ]
    Backend->>DB: Сохранение action items
    Backend-->>UI: список
    UI-->>Алексей: Карточки action items с возможностью редактирования
```

---

## 5. Auth-flow / Онбординг

В MVP приложения нет регистрации и логина (это single-user приложение). Однако есть **онбординг при первом запуске**:

```mermaid
flowchart TD
    Start([Первый запуск]) --> CheckData{Данные в IndexedDB?}
    CheckData -->|Нет| Welcome[Экран приветствия]
    Welcome --> Hint[Подсказка: Загрузите первый файл]
    Hint --> Home
    CheckData -->|Да| Home

    Home --> FirstUse{Первый раз?}
    FirstUse -->|Да| QuickStart[Quick Start: загрузка + просмотр]
    QuickStart --> Home
    FirstUse -->|Нет| Home

    Home --> AboutProject[О проекте: локальность, приватность]
    AboutProject --> Home
```

**Особенности:**
- Нет регистрации/логина — single-user приложение.
- При первом запуске — экран приветствия с объяснением «всё локально, никаких облаков».
- Кнопка «О проекте» — на главной, объясняет приватность (важно для P-03).

---

## 6. State-диаграммы

### 6.1. ST-01: Транскрипция

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Loading: Клик «Транскрибировать»
    Loading --> Processing: Аудио готово
    Processing --> Monitor: RSS check
    Monitor --> Processing: RSS < 80%
    Monitor --> Throttle: RSS > 80%
    Throttle --> Processing: Переключение на 10 сек chunk
    Processing --> Done: Все чанки обработаны
    Processing --> Failed: Ошибка модели
    Processing --> Paused: Пользователь нажал «Пауза»
    Paused --> Processing: Клик «Продолжить»
    Failed --> Idle: Клик «Повторить»
    Done --> [*]
```

### 6.2. ST-02: Live Mode (встреча)

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Connecting: Вставка URL Телемост
    Connecting --> Streaming: Разрешения получены
    Connecting --> NoMic: Микрофон недоступен
    NoMic --> Idle: Показать инструкцию
    Streaming --> Streaming: Идёт встреча
    Streaming --> LowMemory: RSS > 80%
    LowMemory --> Streaming: RAM освобождена
    Streaming --> Saving: Клик «Завершить»
    Saving --> Done: Протокол сохранён
    Streaming --> Lost: WebSocket отключён
    Lost --> Streaming: Переподключение OK
    Lost --> Idle: Переподключение не удалось
    Done --> [*]
```

### 6.3. ST-03: Экспорт DOCX

```mermaid
stateDiagram-v2
    [*] --> Dialog
    Dialog --> Configuring: Изменение параметров
    Configuring --> Dialog: Настройка завершена
    Dialog --> Queued: Клик «Экспортировать»
    Queued --> Processing: Backend начал формирование
    Processing --> Processing: Прогресс 0-100%
    Processing --> Done: Файл готов
    Processing --> Failed: Ошибка (OOM, диск переполнен, таймаут)
    Failed --> Dialog: Клик «Повторить»
    Done --> Downloading: Клик «Скачать»
    Downloading --> Dialog: Скачано
    Done --> [*]
    Failed --> [*]
```

### 6.4. ST-04: Поиск

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Typing: Ввод символа
    Typing --> Typing: < 2 символов (не ищем)
    Typing --> Debounce: ≥ 2 символов
    Debounce --> Searching: 300 мс прошло
    Searching --> Results: Найдено
    Searching --> NoResults: Ничего не найдено
    Results --> Typing: Ввод нового символа
    NoResults --> Typing: Ввод нового символа
    Results --> [*]: Закрытие
```

---

## 7. User Journey Map

### 7.1. P-01 Алексей (Windows, основная)

**Цель:** Получить DOCX встречи за ≤15 минут после загрузки.

| Этап | Действия | Мысли | Эмоции | Боли |
|---|---|---|---|---|
| 1. Старт | Открывает приложение | «Что там нового?» | 😐 Нейтрально | Ничего |
| 2. Загрузка | Drag-n-drop файл | «Надеюсь, не упадёт» | 😐 | Файл большой |
| 3. Транскрипция | Ждёт 5 мин | «Работает, не трогаю» | 😌 Спокойно | Ничего |
| 4. Просмотр | Смотрит реплики | «О, всё на месте» | 😊 Радость | Не путает ораторов |
| 5. Правка | Исправляет 2 оратора | «Удобно» | 😌 | — |
| 6. Экспорт | Клик DOCX | «Скорее бы» | ⏳ | Долго ждать |
| 7. Готово | Скачивает файл | «Отлично!» | 🎉 | — |

**Wow-момент:** Автоматическое определение ораторов.

### 7.2. P-02 Алексей (Astra Linux, офлайн)

**Цель:** Найти детали прошлой встречи с заказчиком без интернета.

| Этап | Действия | Мысли | Эмоции | Боли |
|---|---|---|---|---|
| 1. Старт | Открывает приложение офлайн | «Откроется ли?» | 😟 Тревога | Без сети |
| 2. Календарь | Клик по дате | «О, открылся!» | 😊 | — |
| 3. Протокол | Клик по встрече | «Текст есть» | 😌 | Видео долго |
| 4. Поиск | Ищет «срок» | «Быстро нашёл!» | 😊 | — |
| 5. Клик по реплике | Видео с 14:23 | «О, точно!» | 🎉 | — |

**Wow-момент:** Полная функциональность офлайн.

### 7.3. P-03 Гость (на встрече)

**Цель:** Убедиться, что данные не уйдут в чужие облака.

| Этап | Действия | Мысли | Эмоции | Боли |
|---|---|---|---|---|
| 1. До встречи | Видит индикатор «ЗАПИСЬ ИДЁТ» | «Стоп, что это?» | 😟 | Смущение |
| 2. Видит PrivacyBadge | «Данные хранятся локально» | «Ок, не облако» | 😐 → 😌 | — |
| 3. Во время встречи | Забывает про запись | | 😐 Нейтрально | — |
| 4. После встречи | Получает DOCX | «Нормально написано» | 😊 | Может быть неточно |
| 5. Через полгода | Спрашивает копию | «Дайте протокол Х» | 😐 | Если не сохранили |

**Wow-момент:** Прозрачность «куда уходят данные».

---

## 8. Dead-ends и рекомендации

### Найденные потенциальные проблемы

| Экран | Проблема | Рекомендация |
|---|---|---|
| **S-007 SpeakerEditor** | Закрытие без сохранения — потеря правок | Подтверждение «Есть несохранённые правки. Закрыть?» |
| **S-009 ExportDialog** | Долгое формирование — пользователь закрывает вкладку | Предупреждение «Формирование идёт. Не закрывайте вкладку.» + WebSocket-уведомление о завершении |
| **S-010 LiveMode** | Зависание при потере WebSocket | Автопереподключение каждые 5 сек + явный индикатор «Переподключение…» |
| **S-011 SummaryButton** | LLM даёт плохой результат | Кнопка «Перегенерировать саммари» + редактирование |
| **S-016 PrivacyBadge** | Не виден гостю, если он не открывал приложение | Добавить в форму приглашения по email |
| **S-005 CalendarView** | Пусто при первом запуске | При первом открытии — экран приветствия с подсказкой «Загрузите первый файл» |

### Циклы в навигации

✅ **Циклов не обнаружено.** Все экраны либо ведут «дальше» (к действию), либо имеют явный выход (кнопка «Назад» или закрытие модалки).

### Рекомендации по улучшению

1. **S-001 Home** — добавить кнопку «Справка» с quick start tutorial.
2. **S-003 UploadForm** — добавить Drag & Drop для файлов (расширение, не в MVP).
3. **S-004 ProtocolView** — добавить кнопку «Следующий протокол» для быстрого перехода.
4. **S-010 LiveMode** — сохранять последний URL Телемоста для быстрого подключения.
5. **S-014 SearchBar** — добавить hot key Ctrl+K для фокуса.

---

## 9. Связь с другими артефактами

- **US_LIST.md:** 36 US → 16 экранов + 8 sequence + 4 state-диаграмм.
- **Формы:** S-003, S-004, S-005, S-006, S-009, S-010 — это 6 спецификаций из `artifacts/05-forms/`.
- **Процессы:** P-01..P-04 → основные сценарии (SC-01..SC-08).
- **Персоны:** P-01, P-02, P-03 → journey maps в §7.

---

## 10. Следующие шаги

1. ✅ `screen-flow-designer` — этот документ (`SCREEN_FLOW.md`).
2. ➡️ `data-model-designer` — модель данных на основе16 экранов и 6 форм.
3. ➡️ `api-detail-designer` — спецификация API (FastAPI эндпоинты).
4. ➡️ `nfr-spec-builder` — нефункциональные требования.
5. ➡️ `traceability-matrix` — матрица связей US ↔ формы ↔ API ↔ БД ↔ NFR.

## UX-полировка (E133-E144)

### Compact card layout

```
┌──────────────────────────────────────────────────────────────┐
│ [Speaker 1] 00:15:32 ███████░░░░░  [✨ AI] [👥 Diar]            │
│ Текст реплики в одну строку для быстрого чтения               │
├──────────────────────────────────────────────────────────────┤
│ [Speaker 2] 00:18:05 ██████░░░░░░░░░░░                  │
│ Другая реплика с badge Speaker 2 другого цвета                │
└──────────────────────────────────────────────────────────────┘
```

Высота: ~30px на реплику → 30 реплик помещаются без скролла.
