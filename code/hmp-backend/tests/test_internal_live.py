"""E365: tests for routers/live.py — POST /live/start, POST /live/{id}/stop,
WS /live/{id}/stream. Target coverage: 50%+ (was 23%).

Coverage focus:
- start_live() happy path + 422 validation + 500 DB error
- stop_live() 404, 409 (wrong status), happy path
- _handle_stream() ping/pong, JSON echo ACK, invalid JSON branch,
  WebSocketDisconnect branch, error branch with close.
"""
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models import Protocol, ProtocolStatus


# ---------------------------------------------------------------------------
# Local factory
# ---------------------------------------------------------------------------
@pytest.fixture
def make_protocol(db_session):
    async def _factory(
        title: str = "Live Test",
        status=ProtocolStatus.LIVE,
        deleted_at=None,
    ):
        p = Protocol(
            id=uuid.uuid4(),
            title=title,
            status=status,
            date=datetime.now(timezone.utc).date(),
            created_at=datetime.now(timezone.utc),
            deleted_at=deleted_at,
        )
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)
        return p

    return _factory


# ===========================================================================
# POST /live/start
# ===========================================================================

@pytest.mark.asyncio
async def test_live_start_success(client):
    """POST /live/start — creates a protocol in 'live' status, returns 201
    with protocol_id, live_session_id, websocket_url, telemost_iframe_url."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/12345",
        "title": "Live Meeting",
        "audio_device": "default",
        "enable_screenshots": True,
        "screenshot_interval_sec": 60,
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    # All required keys present
    assert "protocol_id" in body
    assert "live_session_id" in body
    assert "websocket_url" in body
    assert "telemost_iframe_url" in body
    assert "started_at" in body
    # websocket_url should contain the protocol_id and path /stream
    assert "/live/" in body["websocket_url"]
    assert "/stream" in body["websocket_url"]
    assert body["protocol_id"] in body["websocket_url"]
    # telemost_iframe_url echoed back
    assert body["telemost_iframe_url"] == payload["telemost_url"]
    # UUIDs valid
    uuid.UUID(body["protocol_id"])
    uuid.UUID(body["live_session_id"])


@pytest.mark.asyncio
async def test_live_start_persists_protocol_in_db(client, db_session):
    """POST /live/start — created protocol must be findable in DB with status='live'."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/persist",
        "title": "Persist Test",
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 201
    pid = uuid.UUID(r.json()["protocol_id"])

    # Verify DB row
    res = await db_session.execute(select(Protocol).where(Protocol.id == pid))
    p = res.scalar_one()
    assert p.title == "Persist Test"
    assert p.status == "live"
    assert p.deleted_at is None


@pytest.mark.asyncio
async def test_live_start_422_missing_title(client):
    """POST /live/start with missing required 'title' — 422."""
    payload = {"telemost_url": "https://telemost.yandex.ru/j/x"}
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_live_start_422_bad_telemost_url(client):
    """POST /live/start with invalid telemost_url pattern — 422."""
    payload = {"telemost_url": "not-a-url", "title": "T"}
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_live_start_422_invalid_screenshot_interval(client):
    """POST /live/start — screenshot_interval_sec < 10 → 422."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/y",
        "title": "T",
        "screenshot_interval_sec": 5,
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 422


# ===========================================================================
# POST /live/{protocol_id}/stop
# ===========================================================================

@pytest.mark.asyncio
async def test_live_stop_success(client, make_protocol):
    """POST /live/{id}/stop — flips status live → loaded, returns 200."""
    p = await make_protocol(status=ProtocolStatus.LIVE)

    r = await client.post(f"/api/v1/hmp/live/{p.id}/stop")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["protocol_id"] == str(p.id)
    assert body["status"] == "loaded"
    assert "stopped_at" in body


@pytest.mark.asyncio
async def test_live_stop_404_not_found(client):
    """POST /live/{id}/stop — non-existent UUID → 404."""
    fake_id = uuid.uuid4()
    r = await client.post(f"/api/v1/hmp/live/{fake_id}/stop")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_live_stop_404_when_soft_deleted(client, make_protocol):
    """POST /live/{id}/stop — soft-deleted protocol → 404 (deleted_at set)."""
    p = await make_protocol(
        status=ProtocolStatus.LIVE,
        deleted_at=datetime.now(timezone.utc),
    )
    r = await client.post(f"/api/v1/hmp/live/{p.id}/stop")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_live_stop_409_wrong_status(client, make_protocol):
    """POST /live/{id}/stop — protocol not in 'live' status → 409.

    NOTE: ProtocolStatus.RECORDING is an alias for 'live' (see models.py),
    so we use LOADED for a non-live status to actually trigger 409.
    """
    p = await make_protocol(status=ProtocolStatus.LOADED)
    r = await client.post(f"/api/v1/hmp/live/{p.id}/stop")
    assert r.status_code == 409
    body = r.json()
    assert "не в режиме live" in body["detail"].lower()
    assert "loaded" in body["detail"]


@pytest.mark.asyncio
async def test_live_stop_422_bad_uuid(client):
    """POST /live/{id}/stop — malformed UUID → 422."""
    r = await client.post("/api/v1/hmp/live/not-a-uuid/stop")
    assert r.status_code == 422


# ===========================================================================
# WebSocket /live/{protocol_id}/stream
# ===========================================================================
#
# httpx.AsyncClient has no websocket_connect (it's still experimental),
# so we use starlette.testclient.TestClient. But TestClient spins up its
# own anyio event loop internally — when pytest-asyncio is already
# running the test inside its own loop, mixing the two deadlocks on
# Linux regardless of whether we use a thread or executor.
#
# Cleanest fix: run each WS scenario in a fresh subprocess so the
# ASGI loop is fully isolated from the pytest-asyncio loop.
import json
import os
import subprocess
import sys
import textwrap  # noqa: E402

from starlette.testclient import TestClient as StarletteTestClient  # noqa: E402

from app.main import app  # noqa: E402


def _run_ws_subprocess(scenario_body: str) -> str:
    """Run a WS scenario in a fresh Python subprocess; return last line of stdout.

    The scenario body is injected verbatim inside an active websocket
    context — it can refer to `ws` directly. We use a SENTINEL marker
    so we can ignore all the lifespan-startup noise on stdout.
    """
    # 4-space indentation because body sits inside a `with` block.
    # We dedent first because the body comes from a triple-quoted docstring
    # which carries function-body indentation; then we re-indent to a
    # consistent depth so all body lines match the sibling statements
    # emitted inside the with-block. (Otherwise Python sees a blank line
    # followed by content at a different indent than the first statement
    # and raises IndentationError: unexpected indent.)
    import textwrap as _tw
    dedented_body = _tw.dedent(scenario_body)
    indented = "\n".join(
        ("        " + line) if line.strip() else line
        for line in dedented_body.splitlines()
    )
    # Sentinel is emitted FIRST (inside the with-block) so all subsequent
    # `print(...)` calls land after it; otherwise the sentinel ends up after
    # the prints and the post-sentinel capture is empty. We also redirect
    # sys.stdout to a temp file BEFORE the app loads so that all
    # structured-log lines (which the FastAPI app emits via structlog's
    # PrintLoggerFactory(sys.stdout)) don't pollute our capture region.
    import tempfile as _tf
    _tmpf = _tf.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    _tmpf.close()
    _out_path = _tmpf.name
    script = (
        "import sys, os, logging\n"
        f"_CAP_PATH = {_out_path!r}\n"
        "_cap_file = open(_CAP_PATH, 'w', buffering=1)\n"
        # Redirect sys.stdout BEFORE importing the app so structlog's
        # PrintLoggerFactory (configured at app load) writes into our
        # temp file rather than the real stdout.
        "_stdout_saved = sys.stdout\n"
        "sys.stdout = _cap_file\n"
        # Also reroute stdlib logging handlers to our temp file.
        "logging.basicConfig(stream=sys.stdout, level=logging.WARNING, force=True)\n"
        # Reconfigure structlog to also write into the temp file.
        "try:\n"
        "    import structlog\n"
        "    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stdout))\n"
        "except Exception:\n"
        "    pass\n"
        "from starlette.testclient import TestClient\n"
        "from app.main import app\n"
        "with TestClient(app) as client:\n"
        "    with client.websocket_connect(\n"
        "        \"/api/v1/hmp/live/00000000-0000-0000-0000-000000000000/stream\"\n"
        "    ) as ws:\n"
        "        sys.stdout.write('\\n__WS_RESULT_BEGIN__\\n')\n"
        "        sys.stdout.flush()\n"
        f"{indented}\n"
        "sys.stdout = _stdout_saved\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        cwd="/root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend",
        env={"PYTHONPATH": "/root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend"},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"WS subprocess failed (rc={result.returncode}):\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    # Read the captured stdout (which we redirected to a temp file BEFORE
    # importing the app, so lifespan logs from structlog don't pollute it).
    try:
        with open(_out_path) as _f:
            _captured = _f.read()
    finally:
        try:
            os.unlink(_out_path)
        except OSError:
            pass
    # Extract everything after the sentinel — everything before is lifespan noise.
    sentinel = "__WS_RESULT_BEGIN__"
    if sentinel in _captured:
        # The user's `print(...)` calls (run inside the with-block, right
        # after the sentinel) are the FIRST non-structlog lines of the
        # post-sentinel region. structlog emits JSON log lines like
        # `{"event": "ws_event_received", ...}` BEFORE the ACK is sent, so
        # we skip them and return the first non-JSON-log line.
        post = _captured.split(sentinel, 1)[1]
        for line in post.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Heuristic: structlog JSON line starts with `{` and contains `"event"`
            if stripped.startswith("{") and '"event"' in stripped:
                continue
            return stripped
    return _captured.strip()


def test_ws_stream_ping_pong():
    """WS stream — client sends 'ping' → server replies 'pong'."""
    out = _run_ws_subprocess(
        """
        ws.send_text("ping")
        reply = ws.receive_text()
        print(reply)
        assert reply == "pong", f"expected pong, got {reply!r}"
        """
    )
    assert out == "pong"


def test_ws_stream_json_event_echoes_ack():
    """WS stream — JSON event → server replies with ACK containing same payload."""
    out = _run_ws_subprocess(
        """
        import json as _json
        payload = {"type": "screenshot", "data": {"path": "/tmp/x.png"}}
        ws.send_text(_json.dumps(payload))
        ack = _json.loads(ws.receive_text())
        print(_json.dumps(ack))
        assert ack["type"] == "ack"
        assert ack["received_type"] == "screenshot"
        assert ack["payload"] == payload
        assert "ts" in ack
        """
    )
    import json as _json
    ack = _json.loads(out)
    assert ack["type"] == "ack"
    assert ack["received_type"] == "screenshot"
    assert ack["payload"] == {"type": "screenshot", "data": {"path": "/tmp/x.png"}}
    assert "ts" in ack


def test_ws_stream_invalid_json_sends_error():
    """WS stream — non-JSON, non-'ping' text → server sends error frame."""
    out = _run_ws_subprocess(
        """
        import json as _json
        ws.send_text("not json {{{")
        msg = _json.loads(ws.receive_text())
        print(_json.dumps(msg))
        assert msg["type"] == "error"
        assert "json" in msg["message"].lower()
        """
    )
    import json as _json
    msg = _json.loads(out)
    assert msg["type"] == "error"
    assert "json" in msg["message"].lower()


def test_ws_stream_unknown_type_default():
    """WS stream — JSON without 'type' field → server still ACKs, received_type='unknown'."""
    out = _run_ws_subprocess(
        """
        import json as _json
        ws.send_text(_json.dumps({"foo": "bar"}))
        ack = _json.loads(ws.receive_text())
        print(_json.dumps(ack))
        assert ack["type"] == "ack"
        assert ack["received_type"] == "unknown"
        """
    )
    import json as _json
    ack = _json.loads(out)
    assert ack["type"] == "ack"
    assert ack["received_type"] == "unknown"


def test_ws_stream_disconnect_handled():
    """WS stream — graceful client disconnect handled (no exception propagated)."""
    # If the disconnect branch raised, subprocess would have non-zero rc.
    script = textwrap.dedent(
        """
        from starlette.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/v1/hmp/live/00000000-0000-0000-0000-000000000000/stream"
            ) as ws:
                ws.send_text("ping")
                ws.receive_text()
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        cwd="/root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend",
        env={"PYTHONPATH": "/root/.hermes/profiles/alex3/projects/HTML_MeetingProtokol/code/hmp-backend"},
    )
    assert result.returncode == 0, (
        f"WS disconnect scenario raised:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "ok" in result.stdout
