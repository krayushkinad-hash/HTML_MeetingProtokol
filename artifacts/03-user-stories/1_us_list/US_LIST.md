# Перечень User Stories: HTML_MeetingProtokol

| ID | US-текст | Эпик | Приоритет | SP | Персона | Форма | API |
|---|---|---|---|---|---|---|---|
| US-001 | Как Алексей (P-01), я хочу загрузить локальный аудио/видеофайл (mp3/wav/mp4/mkv), чтобы получить протокол встречи без записи в облако | EPIC-FILE | Must | 3 | P-01 Алексей (Windows) | FORM_UPLOAD | POST /api/v1/transcribe/upload |
| US-002 | Как Алексей (P-01), я хочу загрузить файл по HTTPS-ссылке из Яндекс.Диска/Google Drive/Mail.ru, чтобы не скачивать его вручную | EPIC-FILE | Must | 5 | P-01 Алексей (Windows) | FORM_UPLOAD | POST /api/v1/transcribe/from-url |
| US-003 | Как Алексей (P-01), я хочу видеть прогресс загрузки файла по ссылке, чтобы понимать, сколько ещё ждать | EPIC-FILE | Should | 2 | P-01 Алексей (Windows) | FORM_UPLOAD | GET /api/v1/transcribe/progress/{task_id} |
| US-004 | Как Алексей (P-01), я хочу получить предупреждение, если файл больше 2 ГБ, чтобы не допустить OOM при транскрипции | EPIC-FILE | Must | 2 | P-01 Алексей (Windows) | FORM_UPLOAD | — |
| US-005 | Как Алексей (P-01), я хочу, чтобы транскрипция русского языка дала WER ≤15%, чтобы протокол был читаемым без правок | EPIC-TRANS | Must | 8 | P-01 Алексей (Windows) | FORM_PROTOCOL_VIEW | POST /api/v1/transcribe/run |
| US-006 | Как Алексей (P-01), я хочу, чтобы транскрипция работала в фоне с прогрессом и возможностью отмены для записей >2 ч, чтобы не блокировать работу | EPIC-TRANS | Must | 5 | P-01 Алексей (Windows) | FORM_PROTOCOL_VIEW | GET /api/v1/transcribe/status/{task_id}, DELETE /api/v1/transcribe/{task_id} |
| US-007 | Как Алексей (P-01), я хочу, чтобы автодиаризация определила ораторов по голосовому профилю с DER ≤20%, чтобы не размечать вручную | EPIC-TRANS | Must | 8 | P-01 Алексей (Windows) | FORM_PROTOCOL_VIEW | POST /api/v1/diarize/run |
| US-008 | Как Алексей (P-01), я хочу вручную поправить метки ораторов после автодиаризации, чтобы исправить ошибки | EPIC-MANUAL | Must | 3 | P-01 Алексей (Windows) | FORM_DIARIZATION_REVIEW | PATCH /api/v1/utterances/{id}/speaker |
| US-009 | Как Алексей (P-01), я хочу вручную поправить текст реплик (ошибки распознавания), чтобы итоговый DOCX был точным | EPIC-MANUAL | Should | 3 | P-01 Алексей (Windows) | FORM_TRANSCRIPT_EDITOR | PATCH /api/v1/utterances/{id}/text |
| US-010 | Как Алексей (P-01), я хочу видеть все протоколы в хронологическом списке, чтобы быстро найти нужный | EPIC-HISTORY | Must | 2 | P-01 Алексей (Windows) | FORM_PROTOCOL_VIEW | GET /api/v1/protocols |
| US-011 | Как Алексей (P-01), я хочу видеть календарь прошлых встреч (месяц/неделя/день), чтобы за 2 секунды найти «что было в прошлый вторник» | EPIC-HISTORY | Must | 5 | P-01 Алексей (Windows), P-02 Алексей (Astra) | FORM_CALENDAR_VIEW | GET /api/v1/calendar?year=&month= |
| US-012 | Как Алексей (P-02, Astra Linux офлайн), я хочу, чтобы календарь открывался за ≤3 секунды без сети, чтобы быстро подготовиться к встрече | EPIC-HISTORY | Must | 3 | P-02 Алексей (Astra, офлайн) | FORM_CALENDAR_VIEW | — (только локальный IndexedDB) |
| US-013 | Как Алексей (P-01), я хочу искать по тексту транскрипции (по слову/фразе), чтобы за ≤10 сек найти нужное решение | EPIC-HISTORY | Must | 5 | P-01, P-02 | FORM_PROTOCOL_VIEW | GET /api/v1/search?q= |
| US-014 | Как Алексей (P-01), я хочу кликнуть по реплике и увидеть видео с этой секунды, чтобы услышать контекст | EPIC-HISTORY | Must | 3 | P-01, P-02 | FORM_TRANSCRIPT_VIEW | GET /api/v1/media/{protocol_id}/video?t= |
| US-015 | Как Алексей (P-01), я хочу экспортировать протокол в DOCX с таймкодами и репликами по ораторам, чтобы отправить участникам | EPIC-DOCX | Must | 5 | P-01, P-03 | FORM_EXPORT_DIALOG | POST /api/v1/export/docx |
| US-016 | Как Алексей (P-01), я хочу, чтобы в DOCX были встроены скриншоты экрана демонстранта с привязкой к моменту реплики | EPIC-DOCX | Should | 8 | P-01 | FORM_EXPORT_DIALOG | POST /api/v1/export/docx?screenshots=true |
| US-017 | Как Алексей (P-01), я хочу, чтобы DOCX содержал гиперссылку «открыть видео с HH:MM:SS» на локальный файл, чтобы участник мог перейти к нужному моменту | EPIC-DOCX | Should | 5 | P-01 | FORM_EXPORT_DIALOG | POST /api/v1/export/docx |
| US-018 | Как Алексей (P-01), я хочу подключиться к Яндекс Телемост по ссылке из приложения, чтобы не переключаться между окнами | EPIC-TELEMOST | Must | 5 | P-01 | FORM_PROTOCOL_VIEW | GET /api/v1/telemost/embed?url= |
| US-019 | Как Алексей (P-01), я хочу видеть три панели в режиме онлайн: видео участников, темы встречи, живая транскрипция | EPIC-TELEMOST | Must | 8 | P-01 | FORM_LIVE_MODE | WebSocket /ws/transcribe/live |
| US-020 | Как Алексей (P-01), я хочу видеть латентность живой транскрипции ≤3 сек, чтобы транскрипция не отставала от речи | EPIC-TELEMOST | Must | 3 | P-01 | FORM_LIVE_MODE | (метрика на бэкенде) |
| US-021 | Как Алексей (P-01), я хочу захватывать скриншоты экрана демонстранта во время встречи, чтобы потом вставить их в DOCX | EPIC-TELEMOST | Could | 8 | P-01 | FORM_LIVE_MODE | POST /api/v1/screenshots/capture |
| US-022 | Как Алексей (P-01), я хочу получить саммари встречи одной кнопкой (через локальную LLM), чтобы не читать весь протокол | EPIC-AI | Should | 5 | P-01 | FORM_SUMMARY_VIEW | POST /api/v1/ai/summarize |
| US-023 | Как Алексей (P-01), я хочу получить автоматически сгенерированный список action items, чтобы не забыть договорённости | EPIC-AI | Should | 5 | P-01, P-03 | FORM_ACTION_ITEMS_LIST | POST /api/v1/ai/action-items |
| US-024 | Как Алексей (P-01), я хочу семантический поиск по смыслу реплик (эмбеддинги), чтобы найти «что решили про бюджет», даже если слово «бюджет» не звучало | EPIC-AI | Could | 8 | P-01 | FORM_PROTOCOL_VIEW | POST /api/v1/search/semantic |
| US-025 | Как Алексей (P-01), я хочу автоматическое тегирование протокола (темы/проекты), чтобы группировать встречи | EPIC-AI | Could | 5 | P-01 | FORM_PROTOCOL_VIEW | POST /api/v1/ai/tags |
| US-026 | Как Алексей (P-01), я хочу, чтобы приложение работало на Windows 10/11, Astra Linux без Windows-only API, чтобы быть кросс-платформенным | EPIC-CROSSPLAT | Must | 3 | P-01, P-02 | — | — |
| US-027 | Как Алексей (P-02, Astra Linux офлайн), я хочу, чтобы режим просмотра (календарь + поиск + реплики) работал полностью без интернета | EPIC-CROSSPLAT | Must | 5 | P-02 | FORM_PROTOCOL_VIEW | — |
| US-028 | Как Алексей (P-02), я хочу установить приложение в Astra Linux без sudo (через pip в ~/.local или AppImage), чтобы не нарушать политику безопасности | EPIC-CROSSPLAT | Should | 3 | P-02 | FORM_UPLOAD | — |
| US-029 | Как Гость (P-03), я хочу быть уверенным, что данные хранятся локально и не передаются в чужие облака, чтобы согласиться на запись встречи | EPIC-PRIVACY | Must | 3 | P-03 Гость | FORM_PROTOCOL_VIEW | (сетевой аудит) |
| US-030 | Как Гость (P-03), я хочу видеть явный индикатор «запись идёт / запись остановлена» в окне встречи, чтобы знать, когда меня записывают | EPIC-PRIVACY | Must | 2 | P-03 | FORM_LIVE_MODE | — |
| US-031 | Как Гость (P-03), я хочу получить копию итогового DOCX по email, чтобы увидеть, что записано, и попросить правки | EPIC-PRIVACY | Should | 3 | P-03 | FORM_EXPORT_DIALOG | POST /api/v1/share/send-docx |
| US-032 | Как Алексей (P-01), я хочу, чтобы пиковый RSS при транскрипции 2-часовой записи не превышал 4 ГБ, чтобы не было OOM | EPIC-RES | Must | 5 | P-01 | — | (мониторинг на бэкенде) |
| US-033 | Как Алексей (P-01), я хочу, чтобы загрузка файла шла потоково (chunk ≤8 МБ) на диск, а не в RAM, чтобы не «съесть» память | EPIC-RES | Must | 3 | P-01 | FORM_UPLOAD | (внутри POST /api/v1/transcribe/upload) |
| US-034 | Как Алексей (P-01), я хочу, чтобы мониторинг RSS автоматически ставил транскрипцию на паузу при превышении 80% RAM, чтобы не уронить систему | EPIC-RES | Must | 5 | P-01 | — | (мониторинг + автопауза) |
| US-035 | Как Алексей (P-01), я хочу, чтобы эмбеддинги для семантического поиска считались батчами по ≤64 реплики, чтобы контролировать память | EPIC-RES | Should | 3 | P-01 | — | (внутри POST /api/v1/search/semantic) |
| US-036 | Как Алексей (P-01), я хочу, чтобы локальная LLM работала с `num_ctx` ≤4096 и `num_batch` ≤128, чтобы не превышать лимит VRAM | EPIC-RES | Should | 2 | P-01 | — | (конфиг LLM) |
| US-037 | Как Алексей (P-01), я хочу получить саммари встречи через Telegram-бота командой `/summarize <protocol_id>`, чтобы не открывать desktop-приложение | EPIC-TELEGRAM | Must | 5 | P-01 Алексей (Windows) | — | POST https://api.gigachat.devices.sberbank.ru/v1/chat/completions |
| US-038 | Как Алексей (P-01), я хочу получить автоматически сгенерированный список action items через Telegram-бота командой `/actions <protocol_id>`, чтобы фиксировать договорённости на ходу | EPIC-TELEGRAM | Should | 5 | P-01 | — | POST https://api.gigachat.devices.sberbank.ru/v1/chat/completions |
| US-039 | Как Алексей (P-01), я хочу получить уведомление в бот, когда backend закончил обработку длинной записи, чтобы не сидеть и ждать | EPIC-TELEGRAM | Should | 3 | P-01 | — | https://api.telegram.org/bot<token>/sendMessage |
| US-040 | Как Алексей (P-01), я хочу отправить голосовое сообщение боту и получить транскрипцию + action items, чтобы фиксировать мысли в дороге | EPIC-TELEGRAM | Should | 5 | P-01 | — | https://api.telegram.org/bot<token>/getFile + Whisper |
| US-041 | Как Алексей (P-01), я хочу, чтобы Telegram-бот принимал только мои сообщения (whitelist по Telegram ID), чтобы никто другой не мог пользоваться | EPIC-TELEGRAM | Must | 2 | P-01 | — | — |
| US-042 | Как Алексей (P-01), я хочу получить теги протокола через Telegram-бота командой `/tags <protocol_id>`, чтобы быстро категоризовать встречи | EPIC-TELEGRAM | Could | 3 | P-01 | — | POST https://api.gigachat.devices.sberbank.ru/v1/chat/completions |
| US-043 | Как Алексей (P-01), я хочу загрузить файл в Telegram-бот (если локальное приложение недоступно) и получить протокол, когда обработка завершится | EPIC-TELEGRAM | Could | 5 | P-01 | — | https://api.telegram.org/bot<token>/getFile |
| US-044 | Как Алексей (P-01), я хочу, чтобы после транскрипции каждая реплика с низкой уверенностью (word confidence < 0.7) была подсвечена жёлтым цветом, чтобы я сразу видел сомнительные места | EPIC-CORRECT | Must | 5 | P-01 | FORM_TRANSCRIPT_VIEW | — |
| US-045 | Как Алексей (P-01), я хочу автоматическое исправление опечаток и слов-паразитов через локальную LLM (например, «ну-у», «э-э-э», «как бы»), чтобы текст был чище | EPIC-CORRECT | Should | 8 | P-01 | FORM_TRANSCRIPT_VIEW | POST /api/v1/ai/cleanup-text |
| US-046 | Как Алексей (P-01), я хочу восстановление пунктуации (запятые, точки, тире) через NLP-обработку, чтобы текст можно было сразу читать без правок | EPIC-CORRECT | Should | 5 | P-01 | FORM_TRANSCRIPT_VIEW | POST /api/v1/ai/restore-punctuation |
| US-047 | Как Алексей (P-01), я хочу создать словарь пользовательских терминов (фамилии клиентов, названия продуктов, аббревиатуры) и передавать его в Whisper как prompt, чтобы улучшить распознавание специфических слов | EPIC-CORRECT | Must | 5 | P-01 | FORM_DICTIONARY_EDITOR | POST /api/v1/transcribe/run?prompt=... |
| US-048 | Как Алексей (P-01), я хочу отредактировать текст реплики в удобном интерфейсе (как в Word) с историей изменений (undo), чтобы быстро поправить ошибки без выхода из протокола | EPIC-CORRECT | Must | 5 | P-01 | FORM_TRANSCRIPT_EDITOR | PATCH /api/v1/utterances/{id}/text |
| US-049 | Как Алексей (P-01), я хочу автоматическую проверку всей транскрипции через LLM (повторное «прослушивание» — модель читает текст и предлагает исправления), чтобы улучшить качество без ручного труда | EPIC-CORRECT | Should | 8 | P-01 | — | POST /api/v1/ai/review-transcript |
| US-050 | Как Алексей (P-01), я хочу, чтобы реплики с пометкой `[?]` (сомнительные) были выделены жёлтым фоном в DOCX-экспорте, чтобы участники видели, что нужно перепроверить | EPIC-CORRECT | Should | 3 | P-01 | FORM_EXPORT_DIALOG | POST /api/v1/export/docx?mark_doubtful=true |
| US-051 | Как Алексей (P-01), я хочу видеть метрику качества транскрипции (WER в % для русского) на странице протокола, чтобы понимать, насколько можно доверять тексту | EPIC-CORRECT | Should | 3 | P-01 | FORM_PROTOCOL_VIEW | (метрика в backend, расчёт через jiwer) |

| US-052 | Как Алексей (P-01), я хочу иметь возможность пометить протокол как удалённый (soft delete), чтобы убрать его из основных списков и поиска, но сохранить возможность восстановления | EPIC-LIFECYCLE | Must | 2 | P-01 | FORM_PROTOCOL_VIEW | DELETE /api/v1/hmp/protocols/{id} |
| US-053 | Как Алексей (P-01), я хочу полностью удалить протокол вместе со всеми связанными данными (реплики, саммари, скриншоты, файлы), чтобы освободить место на диске и убрать ненужные записи навсегда | EPIC-LIFECYCLE | Must | 3 | P-01 | FORM_PROTOCOL_VIEW | DELETE /api/v1/hmp/protocols/{id}/permanent |
| US-054 | Как Алексей (P-01), я хочу настроить свой профиль (имя, email, часовой пояс), чтобы система корректно отображала мои данные и временные метки в протоколах | EPIC-SETTINGS | Should | 2 | P-01 | FORM_BOT_SETTINGS | GET/PATCH /api/v1/hmp/user-setting |
| US-055 | Как Алексей (P-01), я хочу настроить модель Whisper, язык и использование GPU, чтобы транскрипция была оптимальной для моего оборудования и языка встреч | EPIC-SETTINGS | Must | 2 | P-01 | FORM_BOT_SETTINGS | GET/PATCH /api/v1/hmp/user-setting |
| US-056 | Как Алексей (P-01), я хочу выбрать AI провайдер (Hermes/GigaChat/Ollama) и задать API ключи, чтобы саммари и AI-функции работали через выбранный сервис | EPIC-SETTINGS | Must | 2 | P-01 | FORM_DICTIONARY_EDITOR | GET/PATCH /api/v1/hmp/user-setting |
| US-057 | Как Алексей (P-01), я хочу настроить Telegram бота (токен, webhook, разрешённых пользователей), чтобы управлять протоколами через мессенджер | EPIC-SETTINGS | Could | 2 | P-01 | FORM_BOT_SETTINGS | GET/PATCH /api/v1/hmp/user-setting |
| US-058 | Как Алексей (P-01), я хочу экспортировать все протоколы и настройки в JSON-файл и импортировать их обратно, чтобы делать резервные копии или переносить данные на другой компьютер | EPIC-SETTINGS | Should | 3 | P-01 | FORM_BOT_SETTINGS | GET /api/v1/hmp/protocols |
| US-059 | Как Алексей (P-01), я хочу создавать папки для группировки протоколов, чтобы структурировать встречи по проектам, командам или любой другой логике | EPIC-FOLDERS | Should | 2 | P-01 | FORM_PROTOCOL_VIEW | POST /api/v1/hmp/folders |
| US-060 | Как Алексей (P-01), я хочу перетаскивать протоколы в нужную папку, чтобы организовать встречи без долгих кликов | EPIC-FOLDERS | Should | 2 | P-01 | FORM_PROTOCOL_VIEW | PUT /api/v1/hmp/protocols/{id}/folder |
| US-061 | Как Алексей (P-01), я хочу удалять ненужные папки и переименовывать существующие, чтобы поддерживать чистоту в организационной структуре | EPIC-FOLDERS | Must | 2 | P-01 | FORM_PROTOCOL_VIEW | DELETE/PATCH /api/v1/hmp/folders/{id} |
| US-062 | Как Алексей (P-01), я хочу перетаскивать протоколы между папками прямо в списке с визуальной обратной связью, чтобы интуитивно понимать куда я перемещаю и видеть результат сразу | EPIC-FOLDERS | Should | 3 | P-01 | FORM_PROTOCOL_VIEW | PUT /api/v1/hmp/protocols/{id}/folder |
| US-063 | Как Алексей (P-01), я хочу видеть полный путь к файлу видео на диске на странице протокола, чтобы найти его вручную | EPIC-FILE | Should | 2 | P-01 | FORM_PROTOCOL_VIEW | GET /api/v1/hmp/audio-files/{id} |
| US-064 | Как Алексей (P-01), я хочу просмотреть загруженное видео/аудио в браузере, чтобы увидеть содержимое во время чтения транскрипции | EPIC-FILE | Must | 3 | P-01 | FORM_PROTOCOL_VIEW | GET /api/v1/hmp/media/protocols/{id}/source.{ext} |
| US-065 | Как Алексей (P-01), я хочу, чтобы настройки сохранялись мгновенно в браузере (черновик) и не терялись при переключении между вкладками | EPIC-SETTINGS | Must | 3 | P-01 | FORM_BOT_SETTINGS | PATCH /api/v1/hmp/user-setting |
| US-066 | Как Алексей (P-01), я хочу настраивать каждый AI провайдер отдельно с визуальной индикацией статуса, чтобы не вводить префиксы вручную и видеть какие провайдеры настроены | EPIC-SETTINGS | Should | 3 | P-01 | FORM_DICTIONARY_EDITOR | GET/PATCH /api/v1/hmp/user-setting |
| US-067 | Как Алексей (P-01), я хочу проверить правильность Telegram bot токена прямо из настроек, чтобы убедиться что бот работает до того как я начну им пользоваться | EPIC-TELEGRAM | Must | 3 | P-01 | FORM_BOT_SETTINGS | POST /api/v1/hmp/bot/test-connection |
| US-068 | Замена эмодзи на деловые SVG иконки (Material Design) для делового UI | EPIC-FRONTEND | Should | 3 | Алексей | Все UI компоненты | — (только UI) |
| US-069 | Открыть папку с исходным файлом видео прямо из протокола, чтобы быстро найти в проводнике без копирования пути | EPIC-FILE | Should | 2 | Алексей | FORM_PROTOCOL_VIEW | POST /api/v1/audio-files/{id}/open-folder |
| US-070 | Сохранение и отображение реального имени файла (без source.{ext}), чтобы UI и проводник совпадали | EPIC-FILE | Must | 2 | Алексей | FORM_PROTOCOL_VIEW | GET /api/v1/audio-files/{id} |
| US-071 | Замена эмодзи на Font Awesome 6.x outline стиль, единый деловой стиль | EPIC-FRONTEND | Should | 3 | Алексей | Все UI компоненты | — (только UI) |
| US-072 | Удаление всех данных одной кнопкой из настроек (БД + файлы) | EPIC-SETTINGS | Should | 3 | Алексей | FORM_BOT_SETTINGS | DELETE /api/v1/admin/clear-data |
| US-073 | Создать протокол по URL (backend streaming download) | EPIC-UPLOAD | Should | 3 | P-01 | FORM_UPLOAD | POST /api/v1/hmp/protocols/from-url |
| US-074 | Загрузить файл скриншота (multipart, PNG/JPG) | EPIC-SCREENSHOTS | Should | 2 | P-01 | FORM_PROTOCOL_VIEW | POST /api/v1/hmp/screenshots/upload |
| US-075 | Скачивание/управление моделями Whisper с прогрессом (9 моделей tiny-base-large-v3) | EPIC-SETTINGS | Must | 5 | P-01 Алексей | SettingsPage → TranscriptionTab | GET/POST /whisper/models, /whisper/download/{name} |
| US-076 | Виджет статуса модели в Settings (скачана/нет, размер на диске, кнопка скачать inline) | EPIC-SETTINGS | Should | 2 | P-01 Алексей | SettingsPage → TranscriptionTab | GET /whisper/status/{name} |
| US-077 | Страница управления моделями #/whisper — список карточками, статус скачивания, активация, удаление | EPIC-SETTINGS | Should | 3 | P-01 Алексей | WhisperModelsView | GET/POST/DELETE /whisper/* |













---

## Сводная статистика

| Метрика | Значение |
|---|---|
| **Всего US** | 77 |
| **Эпиков** | 16 |
| **Сумма Story Points** | 274 |
| **Средний SP** | 4.0 |
| **Приоритеты (MoSCoW)** | Must: 31 / Should: 26 / Could: 12 / Won't: 0 |
| **Персоны** | P-01 Алексей (Windows) — все 51; P-02 Алексей (Astra, офлайн) — US-011, 012, 013, 014, 026, 027, 028; P-03 Гость — US-029, 030, 031 |

### Распределение по эпикам

| Эпик | US | Sum SP |
|---|---|---|
| EPIC-FILE | US-001..004, 063, 064 | 6 US, 18 SP |
| EPIC-TRANS | US-005..007 | 3 US, 21 SP |
| EPIC-MANUAL | US-008..009 | 2 US, 6 SP |
| EPIC-HISTORY | US-010..014 | 5 US, 18 SP |
| EPIC-DOCX | US-015..017 | 3 US, 18 SP |
| EPIC-TELEMOST | US-018..021 | 4 US, 24 SP |
| EPIC-AI | US-022..025 | 4 US, 23 SP |
| EPIC-CROSSPLAT | US-026..028 | 3 US, 11 SP |
| EPIC-PRIV | US-029..031 | 3 US, 8 SP |
| EPIC-RES | US-032..036 | 5 US, 18 SP |
| **EPIC-TELEGRAM** | **US-037..043** | **7 US, 28 SP** |
| **EPIC-CORRECT** | **US-044..051** | **8 US, 42 SP** |
| **EPIC-LIFECYCLE** | **US-052..053** | **2 US, 5 SP** |
| **EPIC-SETTINGS** | **US-054..058, 065, 066** | **7 US, 17 SP** |
| **EPIC-FOLDERS** | **US-059..062** | **4 US, 9 SP** |

### Распределение по приоритетам

| Приоритет | Кол-во | Sum SP |
|---|---|---|
| Must | 27 | 130 |
| Should | 19 | 85 |
| Could | 12 | 33 |

---

## Связь с pipeline

- **Предыдущий шаг:** `user-persona-builder` (`artifacts/02-personas/PERSONAS.md`) ✅
- **Следующий шаг:** `business-process-modeler` (`artifacts/04-processes/`) — процессы as-is → to-be на основе этих US

## US-078: Whisper Models — Скачивание и управление моделями
- **Status:** Done
- **Файл:** `US_078.md`

## US-079: GPU ускорение Whisper
- **Status:** Documented
- **Файл:** `US_079.md`
- **Описание:** CUDA + cuDNN поддержка с auto-detect

## US-080: Heartbeat прогресс при транскрипции
- **Status:** Done
- **Файл:** `US_080.md`
- **Описание:** Живой прогресс каждые 2 сек с message "Обработка аудио... Nс"

## US-058: Whisper Models — VAD параметры
- **Status:** Done (E118)
- **Файл:** `US_058.md`
- **Описание:** Настраиваемые параметры VAD (min_silence, threshold, speech_pad)
