# UX-полировка (E133-E144, 2026-09-22)

## Diagrama append-only rendering

```
Whisper (worker thread)  →  queue.Queue
                                ↓ every 2 sec
backend _persist_utterances_loop
                                ↓ group by pause ≤ 1.5s (E137)
backend → INSERT utterances
                                ↓
Polling /progress/{task_id}
                                ↓ segments_count > prev
GET /utterances?after_sec=N
                                ↓
Frontend appendUtteranceItems()
   list.insertAdjacentHTML(...)
                                ↓
renderUtteranceItem (3-level fallback)
   1. u.speaker_label
   2. u.speaker_id
   3. virtual color by hash
```

## Card layout (E143)

```
┌──────────────────────────────────────┐
│ [Speaker 1] 00:15:32 ████░░░░        │  ← 22px meta
│ Текст реплики                        │  ← 19px text
└──────────────────────────────────────┘  ← ~30px total
```

Padding 4px 10px, line-height 1.3, margin-bottom 2px.
