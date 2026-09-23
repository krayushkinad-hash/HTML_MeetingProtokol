# Pause/Resume Architecture (E150-E153, 2026-09-23)

## State Machine

```
           ┌──────────────────────────────────────────┐
           │                                          │
           ▼                                          │
       ┌────────┐                                ┌────┴────┐
       │ queued │ ──── start BG-task ──────────▶ │ running │
       └────────┘                                └────┬────┘
                                                      │
                                ┌─────────────────────┼──────────────────┐
                                │                     │                  │
                                ▼                     ▼                  ▼
                          ┌──────────┐         ┌──────────┐       ┌──────────┐
                          │  paused  │         │completed │       │ failed   │
                          └─────┬────┘         └──────────┘       └──────────┘
                                │
                                │ resume
                                │
                                ▼
                          ┌──────────┐
                          │ running  │
                          └──────────┘
```

## Cross-session Resume

```
User Session A (Chrome)              Backend                User Session B (Firefox)
       │                                │                            │
       │ POST /transcribe/run           │                            │
       ├───────────────────────────────▶│ DB: clean reset (E153)    │
       │                                │ DB: insert task            │
       │                                │ start BG-task              │
       │ Polling progress: 42%          │                            │
       │ ◀──────────────────────────────│                            │
       │                                │                            │
       │ POST /transcribe/pause         │                            │
       ├───────────────────────────────▶│ cancel BG-task             │
       │ ◀─ status="paused" ───────────│ DB: paused_at, last_sec    │
       │                                │                            │
       │ User closes browser            │                            │
       │                                │                            │
       │                                │  ← opens Firefox           │
       │                                │                            │
       │                                │ GET /progress/{id}         │
       │                                │ ◀──────────────────────────┤
       │                                │ 200 status="paused"        │
       │                                │                            │
       │                                │ POST /transcribe/resume    │
       │                                │ ◀──────────────────────────┤
       │                                │ verify audio_hash (E151)   │
       │                                │ start new BG-task          │
       │                                │                            │
       │                                │ 200 status="running"       │
       │                                │ ─────────────────────────▶│
```

## DB Schema

```sql
ALTER TABLE transcription_task ADD COLUMN
    paused_at TIMESTAMP WITH TIME ZONE,
    last_processed_sec FLOAT,
    segments_so_far_json TEXT,
    audio_hash VARCHAR(64);
```

## Limitations

### E152: Whisper не умеет "resume с произвольной секунды"

Whisper модели не имеют параметра `t_offset` или подобного.
Workaround для production:
1. Audio segmentation через ffmpeg (вырезать отрезок [last_sec, end])
2. Transcribe только этот отрезок
3. Дедупликация по (start_sec, end_sec)

Текущая реализация:
- Перетранскрибация с нуля + фильтр уже имеющихся segments
- Время = полная длительность (без выигрыша), но state сохраняется для crash recovery

### E151: Audio hash защищает

Если пользователь:
1. Начал транскрибацию одного файла
2. Загрузил новый файл (replace)
3. Resume → hash не совпадает → reset to 0
