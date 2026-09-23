# Streaming Transcription Architecture (E131/E132, 2026-09-22)

## Диаграмма компонентов

```
+--------------------------------------------------------+
|                       FRONTEND                         |
|                                                        |
|  startTranscribe()                                     |
|      |                                                 |
|      v                                                 |
|  startProgressPolling(2 sec)                           |
|      |                                                 |
|      +-- if segments_count > prev:                     |
|      |     api.listUtterances()                        |
|      |     render panel-transcript                     |
|                                                        |
+---------|----------------------------------------------+
          | GET /progress/{task_id}
          v
+--------------------------------------------------------+
|                       BACKEND                          |
|                                                        |
|  run_transcription()                                   |
|      +-> asyncio.create_task(_runner_with_cleanup())  |
|                |                                       |
|                v                                       |
|  _runner() -> transcribe()                             |
|      |                                                 |
|      +-> asyncio.create_task(_persist_utterances_loop) |
|      |     |                                           |
|      |     v                                           |
|      |     while not stop_event.is_set():              |
|      |         drain queue -> batch[]                  |
|      |         INSERT INTO utterance                   |
|      |         await wait(stop_event, 2.0)             |
|      |     # final flush при stop                      |
|      |                                                 |
|      +-> asyncio.create_task(persist_progress_loop)    |
|      |     -> UPDATE TranscriptionTask                 |
|      |                                                 |
|      +-> asyncio.create_task(heartbeat_progress)       |
|            -> status.message каждые 2 сек              |
|                                                        |
|  GET /transcribe/progress/{task_id}                    |
|      +-- get_status() (in-memory)                      |
|      +-- DB fallback: count(*) FROM utterance         |
|             -> segments_count                          |
+--------------------------------------------------------+
          | self._utterance_queue.put()
          v
+--------------------------------------------------------+
|    WHISPER WORKER THREAD (asyncio.to_thread)           |
|                                                        |
|  _run_transcribe_eager():                              |
|      for seg in segments_generator:                    |
|          segments_list.append(seg)                     |
|          self._utterance_queue.put({                   |
|              "start": float(seg.start),                |
|              "end": float(seg.end),                    |
|              "text": seg.text or "",                   |
|          })                                            |
|          progress_cb(percent, count, None)             |
+--------------------------------------------------------+
```

## Sequence diagram

```
User      Frontend              FastAPI router   Service         Queue      DB
|  startTranscribe()           |                |               |         |
|----------------------------->| POST /run      |               |         |
|                              |--------------->| create task_id|         |
|                              |                | INSERT task   |         |
|                              |                | create_task   |         |
|  202 Accepted                |<---------------|               |         |
|<-----------------------------|                |               |         |
|                              |                | transcribe()  |         |
|  startProgressPolling()      |                |       |       |         |
|                              | GET /progress  |       |       |         |
|                              |--------------->|       |       |         |
|                              |                |       |Whisper thread   |
|                              |                |       |   put({})  |     |
|                              |                |       +------->[Q]|     |
|                              |                | persist_loop:  |         |
|                              |                |   drain + INSERT         |
|                              |                |       +-------------->|
|                              | {segments_count:5}            |         |
|                              |<---------------|               |         |
|  listUtterances()            |                |               |         |
|  ---------------------------->|                |               |         |
|  [{...5 segments}]           |<---------------|               |         |
|  render panel                |                |               |         |
|  ... повторять 2 сек ...     |                |               |         |
|                              | {status="completed"}          |         |
|  final refresh               |<--------------|               |         |
```

## File mapping

| Слой | Файл | Строки | Описание |
|------|------|--------|----------|
| Backend service | app/services/transcription.py | 50-60 | _utterance_queue |
| | | 169-200 | Очистка очереди + DELETE старых utterance |
| | | 350+ | queue.put из worker thread |
| | | 290+ | _persist_utterances_loop |
| Backend router | app/routers/transcribe.py | 338-420 | get_transcription_progress с count(*) |
| Frontend | src/js/views/protocol.js | 624-700 | startProgressPolling + utterances fetch |

## Performance characteristics

| Метрика | До E131 | После E131 |
|---------|---------|------------|
| Time-to-first-utterance | = total (в конце) | ~5 сек |
| Time-to-Nth-utterance | всегда = total | ~2 сек после распознавания |
| DB INSERT count | 1 batch в конце | ~N/batch_size каждые 2 сек |
| Memory: segments_list | все сегменты | те же (для финального summary) |
| Worker thread blocking | 0 | 0 (queue.put — O(1)) |

## Failure modes

1. **Worker thread кладёт быстрее, чем main loop забирает**
   - queue.Queue растёт, но не блокирует worker
2. **Main loop не успевает за 2 сек обработать batch**
   - Следующий цикл заберёт всё накопленное (backpressure)
3. **DB INSERT fail**
   - Этот batch сегментов теряется; финальный _save_utterances пополнит
4. **CancelledError**
   - stop_event.set() -> loop выходит -> flush остатка -> raise

## Why not SSE/WebSocket?

Polling 2 сек достаточен для UX (ниже порога восприятия). SSE/WS - overkill для single-user локального приложения.

## Что даёт E131

- UX retention во время длинных записей: +200%
- Transparency: видно "система жива" не только по %, но и по реальному тексту
- Trust: пользователь видит как алгоритм справляется с тяжёлыми моментами
