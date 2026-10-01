# HMP Backend — Coverage Report

**Date:** 2025-09-29
**Measurement command:**
```
cd /root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend
/tmp/.hmp-venv/bin/python3 -m pytest tests/ --cov=app \
    --cov-report=term --cov-report=html --cov-report=xml --tb=line
```

---

## 1. Headline numbers

| Metric | Value |
|---|---|
| **Total coverage** | **32.51%** (1660 / 5106 statements) |
| Tests collected | 76 |
| Tests passed | **76** |
| Tests failed | **0** (3 fixed in `tests/`) |
| Tests skipped | **1** (`tests/test_monitoring.py` — module removed from `app/`) |
| Reports generated | `htmlcov/index.html` (26 KB), `coverage.xml` (192 KB) |

Note: The task brief mentioned ~110 additional tests from parallel subagents
(`test_services.py`, `test_api_integration.py`, `test_e2e_workflows.py`).
Those files were not present when this measurement ran, so coverage reflects
only the tests that already exist (`test_models.py`, `test_llm_client.py`,
`test_smoke.py`, `test_screenshots.py`, `test_user_setting.py`,
`test_video_screenshots_service.py`, `test_monitoring.py`).

---

## 2. Tests fixed in this pass (in `tests/` only — `app/` untouched)

1. **`tests/test_user_setting.py`** — `UserSettingResponse` was being imported
   from `app.schemas`, but the class actually lives in
   `app.routers.user_setting`. Fixed the import. Two tests also failed because
   the schema has 9 required fields; updated them to supply valid values.
2. **`tests/test_monitoring.py`** — `app.core.monitoring.RSSMonitor` was
   removed from `app/` (per `app/main.py:109` note: "RSSMonitor не реализует
   реальную паузу, отключён"). The test file is now `pytest.skip(..., allow_module_level=True)`
   with an explanatory comment.
3. **`tests/test_llm_client.py::test_hermes_generate_success`** — Created
   `HermesClient()` without mocking `settings.hermes_api_key`, so
   `generate()` raised `ValueError`. Wrapped construction in the same
   `patch("app.services.llm_client.settings", ...)` pattern used by the
   other passing tests in the file.

---

## 3. Per-module coverage

### 3.1 Best-covered files (≥50%)

| File | Stmts | Missed | Cover |
|---|---:|---:|---:|
| `app/__init__.py` | 1 | 0 | 100% |
| `app/db/__init__.py` | 2 | 0 | 100% |
| `app/db/models.py` | 300 | 0 | 100% |
| `app/schemas/__init__.py` | 160 | 0 | 100% |
| `app/routers/transcribe/__init__.py` | 8 | 0 | 100% |
| `app/core/config.py` | 78 | 4 | 95% |
| `app/services/llm_client.py` | 62 | 4 | 94% |
| `app/core/logging_config.py` | 19 | 5 | 74% |
| `app/main.py` | 109 | 37 | 66% |
| `app/routers/calendar.py` | 20 | 9 | 55% |
| `app/routers/whisper_models.py` | 100 | 47 | 53% |
| `app/core/middleware.py` | 25 | 12 | 52% |
| `app/routers/user_setting.py` | 110 | 54 | 51% |
| `app/db/types.py` | 38 | 19 | 50% |

### 3.2 Top-10 most-uncovered files (by coverage %)

| Rank | File | Stmts | Missed | Cover |
|---:|---|---:|---:|---:|
| 1 | `app/services/auto_screenshots.py` | 125 | 125 | **0%** |
| 2 | `app/services/diarization.py` | 56 | 56 | **0%** |
| 3 | `app/services/task_status.py` | 24 | 24 | **0%** |
| 4 | `app/services/transcription_progress.py` | 52 | 52 | **0%** |
| 5 | `app/services/transcription.py` | 425 | 389 | 8% |
| 6 | `app/db/session.py` | 182 | 166 | 9% |
| 7 | `app/services/video_screenshots.py` | 208 | 187 | 10% |
| 8 | `app/routers/protocols.py` | 254 | 227 | 11% |
| 9 | `app/routers/transcribe/local.py` | 240 | 210 | 12% |
| 10 | `app/routers/transcribe/progress.py` | 121 | 104 | 14% |

Four files (`auto_screenshots`, `diarization`, `task_status`,
`transcription_progress`) are entirely uncovered because they have **no
tests at all** — the `test_services.py` planned by another subagent was
not delivered yet.

---

## 4. Recommendations to reach 80% coverage

**Gap analysis:** 32.51% → 80% requires ~2425 more statements covered
out of 5106. Even covering the **top-5** biggest modules 100% only
reaches ~57%. Reaching 80% requires touching **~15 files** (or
substantial partial coverage on the top ~10).

### 4.1 Priority-5 files — each gives the largest single-step gain

| File | Uncovered stmts | pp gain if 100% |
|---|---:|---:|
| `app/services/transcription.py` | 389 | +7.6 pp |
| `app/services/whisper_models.py` | 238 | +4.7 pp |
| `app/routers/protocols.py` | 227 | +4.4 pp |
| `app/routers/transcribe/local.py` | 210 | +4.1 pp |
| `app/services/video_screenshots.py` | 187 | +3.7 pp |

Cumulative if all 5 covered at 100%: **57.0%**.

### 4.2 What the pending subagent tests should add

When the parallel subagents deliver the missing test files, the projected
jump (based on already-collected filenames) is large:

* **`test_services.py`** — expected to drive coverage on the four
  0%-covered services (`auto_screenshots`, `diarization`, `task_status`,
  `transcription_progress`) and on `transcription.py`,
  `whisper_models.py`, `video_screenshots.py`. Combined these are
  ~1075 uncovered stmts — +21 pp of theoretical coverage.
* **`test_api_integration.py`** — expected to hit the routers
  (`protocols`, `audio`, `export`, `folders`, `utterances`, `bot`,
  `admin`) using the FastAPI ASGI client via `conftest.py`'s
  `httpx.ASGITransport`. ~1300 uncovered stmts — +25 pp.
* **`test_e2e_workflows.py`** — slow path tests; covers glue code in
  `main.py`, `middleware.py`, `transcribe/*` end-to-end. ~400 stmts.

If all three deliver as planned and reach ~70% line coverage on their
target files, total coverage lands near **70–75%**.

### 4.3 Concrete next steps

1. Wait for / request delivery of `test_services.py`,
   `test_api_integration.py`, `test_e2e_workflows.py` from the parallel
   subagents (they're the only realistic path from 33% to 80%).
2. Once present, add targeted tests for the four 0%-covered files:
   * `app/services/auto_screenshots.py` — task orchestration, mocked subprocess
   * `app/services/diarization.py` — speaker-diarization wrapper
   * `app/services/task_status.py` — in-memory task tracker
   * `app/services/transcription_progress.py` — progress emitter
3. Add API-integration tests using the existing `conftest.py` fixtures
   (StaticPool SQLite + `httpx.ASGITransport`) for the 11–14% routers
   (`protocols`, `transcribe/local`, `transcribe/progress`, `admin`,
   `export`).
4. Re-run this same measurement command to refresh `htmlcov/index.html`.

### 4.4 What is realistically *not* worth covering for the 80% goal

* `app/main.py` lifespan / startup hooks (covered indirectly by
  `test_import_app`).
* `app/core/config.py` (95% already; remaining 4 stmts are pydantic edge
  cases).
* `app/routers/calendar.py` (55%, only 9 stmts remaining).

---

## 5. Files modified by this measurement task

* `tests/test_user_setting.py` — fixed import + added required schema fields.
* `tests/test_monitoring.py` — added module-level `pytest.skip(...)`
  with explanatory docstring.
* `tests/test_llm_client.py` — fixed one test to mock `settings`.

No `app/` files modified.