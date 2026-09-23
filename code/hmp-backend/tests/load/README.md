# k6 Load Tests — HTML_MeetingProtokol (HMP)

Нагрузочные тесты для backend API `HTML_MeetingProtokol` (FastAPI, `/api/v1/hmp`).
Скрипты написаны под **k6 v0.49+** (ES6 modules).

Все thresholds соответствуют **NFR §3.1**:

| Endpoint               | NFR p95  | Test threshold |
|------------------------|----------|----------------|
| `GET /protocols`       | < 100 ms | p95 < 100 ms   |
| `GET /calendar`        | < 100 ms | p95 < 100 ms   |
| `GET /search`          | < 150 ms | p95 < 250 ms (env.) |
| `GET /utterances`      | < 150 ms | (через `getProtocol`) |
| AI транскрибация       | < 10 s   | p95 < 2 s на status-poll |
| Синхронные (overall)   | < 200 ms | p95 < 200 ms   |

---

## Содержимое

```
tests/load/
├── config.js                  ← общий config + helpers (getJSON, postJSON, uploadFile)
├── smoke.js                   ← 5 VU × 10s, /health
├── api_read.js                ← ramp 10→50→100 VU × 30s, list + calendar
├── api_search.js              ← 20 VU × 20s, /search
├── api_upload.js              ← 5 VU × 10s, POST /protocols multipart ~100KB
├── transcribe_status.js       ← 30 VU × 60s, polling /transcribe/status/{uuid}
├── stress.js                  ← ramp 10→300→500 VU × 5min, mixed traffic
├── spike.js                    ← 0→200→0 VU за 30s, burst
├── soak.js                    ← 30 VU × 10min, leak detection
├── setup.js                   ← seed 10 протоколов (init stage)
├── fixtures/
│   └── sample-meeting.mp4     ← 100 KB binary blob для upload-тестов
├── scripts/
│   └── run-all.sh             ← orchestration всех тестов
├── results/
│   └── .gitkeep
└── README.md
```

---

## Установка k6

### macOS
```bash
brew install k6
```

### Ubuntu / Debian
```bash
sudo gpg --no-default-keyring \
  --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 \
  --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install k6
```

### Windows (winget)
```powershell
winget install k6 --source winget
```

### Docker
```bash
docker run --rm -i grafana/k6 run - <tests/load/smoke.js
```

Проверка: `k6 version` → должно быть `k6 v0.49.0` или выше.

---

## Быстрый старт

### 1. Smoke (самая базовая проверка)
```bash
k6 run tests/load/smoke.js
```

### 2. Read-heavy
```bash
k6 run tests/load/api_read.js
```

### 3. Полный прогон (orchestrator)
```bash
./tests/load/scripts/run-all.sh
```

Скрипт прогонит все тесты последовательно, агрегирует результаты в
`tests/load/results/` и завершится с exit-code `0` только если **все thresholds passed**.

---

## Параметры окружения

Все скрипты читают `BASE_URL` (default `http://127.0.0.1:8000`).
Также поддерживаются:

| Переменная      | Назначение                                              |
|-----------------|---------------------------------------------------------|
| `BASE_URL`      | URL бэкенда (default `http://127.0.0.1:8000`)          |
| `DURATION`      | Длительность soak (default `10m`)                       |
| `FIXTURE_PATH`  | Путь к fixture-файлу для upload (default `./fixtures/sample-meeting.mp4`) |
| `PROTOCOL_IDS`  | CSV uuid-ов для `stress.js` — id известных протоколов   |

Пример:
```bash
BASE_URL=https://staging.example.com \
PROTOCOL_IDS="a1...,b2...,c3..." \
k6 run tests/load/stress.js
```

---

## Подготовка данных

Перед запуском `stress.js` / `soak.js` / `api_read.js` рекомендуется
засеять тестовые данные:

```bash
k6 run tests/load/setup.js
```

Скрипт создаст 10 протоколов через API (id логируются в stdout).
Затем их можно скормить в `stress.js`:

```bash
PROTOCOL_IDS="$(k6 run tests/load/setup.js 2>&1 | grep 'seeded id=' | sed -E 's/.*id=([0-9a-f-]+).*/\1/' | paste -sd, -)"
k6 run -e PROTOCOL_IDS="$PROTOCOL_IDS" tests/load/stress.js
```

---

## Когда прогонять

| Событие                                          | Тесты                                                |
|--------------------------------------------------|------------------------------------------------------|
| Перед каждым PR в `main`                         | `smoke.js`                                           |
| Перед релизом                                    | `smoke.js`, `api_read.js`, `api_search.js`, `api_upload.js` |
| Раз в неделю (staging)                           | `stress.js`, `soak.js`                               |
| После изменения infra / scaling policy           | `spike.js`, `stress.js`                              |
| После изменений в `transcribe` pipeline          | `transcribe_status.js`                               |

---

## Интерпретация thresholds

k6 выводит в конце каждого прогона блок `THRESHOLDS`:

```
     ✓ http_req_duration............: avg=87ms  p(95)=140ms  p(99)=210ms
     ✓ http_req_failed..............: 0.00%    0 out of 1234
```

- ✅ **passed** (`✓`) — порог соблюдён;
- ❌ **failed** (`✗`) — порог превышен, тест возвращает ненулевой exit-code.

Что означают метрики:

| Метрика                | Что измеряет                                        |
|-----------------------|-----------------------------------------------------|
| `http_req_duration`   | Полное время запроса (connect + send + wait + recv) |
| `http_req_failed`     | Доля запросов со статусом ≥ 400 или сетевыми ошибками |
| `http_reqs`           | Общее число выполненных HTTP-запросов                |
| `iterations`          | Сколько раз VU выполнил `default`-функцию           |
| `data_received`       | Объём скачанных байт                                |
| `data_sent`           | Объём отправленных байт                             |

Тэги `endpoint`, `op`, `method` позволяют строить per-endpoint отчёты
через `handleSummary` или внешние sinks (InfluxDB / Prometheus / Grafana Cloud).

### Кастомный handleSummary (опционально)

Чтобы писать JSON-отчёты в `results/`, добавьте в любой тест:

```js
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.4/index.js';

export function handleSummary(data) {
  return {
    'stdout':                  textSummary(data, { indent: ' ', enableColors: true }),
    'tests/load/results/<name>.json': JSON.stringify(data, null, 2),
  };
}
```

`run-all.sh` уже подхватит JSON-файлы из `results/`.

---

## Troubleshooting

| Симптом                                         | Решение                                                       |
|-------------------------------------------------|---------------------------------------------------------------|
| `ERRO[0001] ... connection refused`             | Бэкенд не запущен или `BASE_URL` указывает не туда            |
| `Cannot open fixture file: ...`                | `cd` в корень репозитория или задайте `FIXTURE_PATH`          |
| Все запросы 404                                  | Проверьте, что API-prefix совпадает: должен быть `/api/v1/hmp` |
| Threshold fail: `p(95)>200ms` на `/search`      | Возможно, БД не проиндексирована — см. NFR §3.1               |
| Threshold fail: `http_req_failed` > 1%          | Часто признак того, что бэкенд упал под нагрузкой — смотрите его логи |

---

## Расширение

- Добавить custom-metrics (`Trend`, `Counter`, `Rate`) — импорт из `k6/metrics`.
- Подключить Grafana Cloud / InfluxDB output:

```bash
k6 run --out influxdb=http://localhost:8086/k6 tests/load/api_read.js
```

- WebSocket-тесты — `k6/ws` модуль.
- gRPC — `k6/net/grpc`.