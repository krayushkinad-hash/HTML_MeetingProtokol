# Decisions & Multilingual Architecture (E146-E149, 2026-09-23)

## Диаграмма

```
┌────────────────────────────────────────────────────────────────┐
│ Frontend                                                       │
│                                                                │
│  Transcript panel:                                             │
│  [Speaker 1] 03:55  ███░░░░  [＋ ⚖️] [🇷🇺 Ру ▼] [🌍→EN ▼]  │
│                                                                │
│  [+ ⚖️] клик                                                  │
│    ↓                                                            │
│  POST /decisions {text, source_utterance_id}                  │
│    ↓                                                            │
│  ⚖️ on card, .is-decision class, зелёная рамка               │
│                                                                │
│  [🤖 Найти решения] клик                                       │
│    ↓                                                            │
│  POST /ai/extract-decisions {protocol_id}                     │
│    ↓  MOCK эвристика: "решили", "договорились", ...            │
│  for each: POST /decisions (с дедупликацией)                  │
│                                                                │
│  [🌐 Перевести] клик                                            │
│    ↓                                                            │
│  POST /ai/translate {target: "en"}                            │
│    ↓  MOCK: "[en] {original_text}" + кэширование              │
│  Показ под оригиналом                                          │
│  ┌──────────────────────────────────────────┐                  │
│  │ 🌐 EN: [en] We agreed to use PostgreSQL. │                  │
│  └──────────────────────────────────────────┘                  │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ Backend (PostgreSQL)                                           │
│                                                                │
│  protocol.language         = "ru" | "en" | ...                 │
│  protocol.translation_lang = "en" | null                       │
│  utterance.text               = "Договорились использовать PostgreSQL." │
│  utterance.translation_text   = "[en] We agreed to use PostgreSQL." │
│  utterance.translation_lang   = "en"                           │
│                                                                │
│  decision.text              = "..."                            │
│  decision.source_utt_id     = uuid-u1 (ссылка)                │
│  decision.timestamp_sec     = 235.5 (денормализованный)       │
│  decision.decided_by        = "AI (авто)" | null | "Username" │
└────────────────────────────────────────────────────────────────┘
```

## Sequence diagram (translation)

```
User              Frontend              POST /ai/translate     Backend LLM (mock)
│                      │                       │                       │
│ Клик "Перевести"    │                       │                       │
├────────────────────▶│ translateUtterances   │                       │
│                      ├──────────────────────▶│                       │
│                      │  POST /ai/translate    │                       │
│                      │  {target: "en"}       │                       │
│                      │                       │ ──── mock LLM ──────▶│
│                      │                       │                       │
│                      │  200                  │                       │
│                      │  {translations: [...]}│                      │
│                      │◀──────────────────────│                       │
│                      │ Update DOM (append)   │                       │
│                      │ translation_block     │                       │
│                      │ под каждой репликой   │                       │
│                      │                       │                       │
│                      │ Set Protocol.translation_language="en"      │
│                      │ (PATCH /protocols)    │                       │
```

## Версионирование

- **v0:** MOCK с ключевыми словами → 70% accuracy
- **v1 (next):** LLM через `llm_router.generate(target_language=...)`
- **v2:** Кэширование переводов в БД с инвалидацией по text_changed_hash
