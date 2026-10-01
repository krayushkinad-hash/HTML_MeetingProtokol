"""Round1 tests for app/routers/live.py — push coverage past 60%.

Targets gaps left by test_internal_live_v2 + v3:

- _handle_stream `finally` block: hb_task.cancel() and hb_task await
  swallow (lines 228-233) — exercised on every clean disconnect.
- _handle_stream log "ws_event_received" (lines 211-215) — implicit
  when JSON ack is sent.
- _handle_stream log "ws_disconnected" (line 217) — via caplog.
- _handle_stream generic Exception branch + close(WS_1011) happy path
  (lines 218-227) — when close() itself doesn't raise.
- heartbeat_loop is created and runs until cancelled (lines 162-178).
- websocket.accept() is called (line 162) and ws_connected is logged
  (line 163) on every successful connection.
- live_stream_ws thin wrapper just delegates to _handle_stream (line 247).
- start_live() `started_at` is timezone-aware UTC (line 105).
- stop_live() happy path emits live_stopped log (line 140).
- start_live() minimal payload returns audio_device='default' effectively
  — verify response shape & DB status field is 'live' string.
- WS: nested JSON payload round-trips in ack.payload (lines 207-209).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.db.models import Protocol, ProtocolStatus
from app.routers import live as live_mod


# ---------------------------------------------------------------------------
# Local factory (matches v3 pattern)
# ---------------------------------------------------------------------------
@pytest.fixture
def make_protocol(db_session):
    async def _factory(
        title: str = "Live Round1",
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


class FakeWebSocket:
    """Minimal fake WebSocket: record-only sends, programmable receive."""

    def __init__(self, receive_side_effect):
        self.accept = AsyncMock()
        self.send_json = AsyncMock()
        self.send_text = AsyncMock()
        self.close = AsyncMock()
        self.receive_text = AsyncMock(side_effect=receive_side_effect)
        self._json_messages: list = []
        self._text_messages: list = []

        async def _capture_json(payload):
            self._json_messages.append(payload)

        async def _capture_text(text):
            self._text_messages.append(text)

        self.send_json.side_effect = _capture_json
        self.send_text.side_effect = _capture_text


# ===========================================================================
# POST /live/start — additional shape/DB coverage
# ===========================================================================

@pytest.mark.asyncio
async def test_live_start_response_started_at_is_utc_tz_aware(client):
    """POST /live/start — started_at is timezone-aware UTC."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/round1-ts",
        "title": "TS Check",
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 201, r.text
    started_at = datetime.fromisoformat(r.json()["started_at"])
    assert started_at.tzinfo is not None, "started_at must be tz-aware"


@pytest.mark.asyncio
async def test_live_start_persists_protocol_with_status_live(client, db_session):
    """POST /live/start — Protocol row written to DB with status='live'."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/round1-db",
        "title": "DB Persist",
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 201
    pid = uuid.UUID(r.json()["protocol_id"])

    # Reload via fresh query on the same session
    res = await db_session.execute(select(Protocol).where(Protocol.id == pid))
    p = res.scalar_one()
    assert p.title == "DB Persist"
    assert str(p.status) == "live" or p.status == ProtocolStatus.LIVE


@pytest.mark.asyncio
async def test_live_start_logs_live_started(capsys, client):
    """POST /live/start — info-level 'live_started' log emitted."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/log",
        "title": "Log Check",
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 201
    captured = capsys.readouterr().out
    assert "live_started" in captured


# ===========================================================================
# POST /live/{id}/stop — log coverage
# ===========================================================================

@pytest.mark.asyncio
async def test_live_stop_logs_live_stopped(client, make_protocol, capsys):
    """POST /live/{id}/stop — info-level 'live_stopped' log emitted."""
    p = await make_protocol(status=ProtocolStatus.LIVE)
    r = await client.post(f"/api/v1/hmp/live/{p.id}/stop")
    assert r.status_code == 200
    captured = capsys.readouterr().out
    assert "live_stopped" in captured


# ===========================================================================
# WS — log lines + nested JSON + close-failure swallow
# ===========================================================================

@pytest.mark.asyncio
async def test_ws_handle_stream_logs_ws_connected_and_disconnected(capsys):
    """WS: 'ws_connected' on accept, 'ws_disconnected' on clean close.

    Uses capsys because the app uses structlog → stdout, which caplog
    (stdlib logging) doesn't intercept.
    """
    ws = FakeWebSocket(receive_side_effect=[WebSocketDisconnect()])
    await live_mod._handle_stream(ws, uuid.uuid4())
    captured = capsys.readouterr().out
    assert "ws_connected" in captured
    assert "ws_disconnected" in captured


@pytest.mark.asyncio
async def test_ws_handle_stream_logs_ws_event_received(capsys):
    """WS: 'ws_event_received' info log on every JSON ack."""
    ws = FakeWebSocket(receive_side_effect=[
        json.dumps({"type": "screenshot", "data": {"x": 1}}),
        WebSocketDisconnect(),
    ])
    await live_mod._handle_stream(ws, uuid.uuid4())
    captured = capsys.readouterr().out
    assert "ws_event_received" in captured


@pytest.mark.asyncio
async def test_ws_handle_stream_logs_ws_error_on_unexpected_exception(capsys):
    """WS: 'ws_error' exception log on RuntimeError + close(WS_1011)."""
    ws = FakeWebSocket(receive_side_effect=RuntimeError("boom"))
    await live_mod._handle_stream(ws, uuid.uuid4())
    captured = capsys.readouterr().out
    assert "ws_error" in captured
    ws.close.assert_called_once()
    args, kwargs = ws.close.call_args
    code = kwargs.get("code") if kwargs else (args[0] if args else None)
    assert code == status.WS_1011_INTERNAL_ERROR


@pytest.mark.asyncio
async def test_ws_handle_stream_swallows_close_failure_during_error():
    """WS: if websocket.close() itself raises inside error branch, swallowed."""
    ws = FakeWebSocket(receive_side_effect=RuntimeError("boom"))

    async def _boom_close(*args, **kwargs):
        raise RuntimeError("close failed too")

    ws.close.side_effect = _boom_close

    # Should NOT raise — the inner `except Exception: pass` catches it.
    await live_mod._handle_stream(ws, uuid.uuid4())
    ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_ws_handle_stream_heartbeat_task_cancelled_in_finally():
    """WS: heartbeat_loop is cancelled & awaited cleanly on disconnect.

    Covers lines 228-233 (finally: hb_task.cancel(); await hb_task with
    the broad `except (CancelledError, Exception)` swallow).
    """
    from unittest.mock import patch

    # First receive sleeps briefly so the heartbeat-loop fires at least
    # once, THEN raises WebSocketDisconnect so we hit the finally block.
    async def _slow_then_disconnect():
        await asyncio.sleep(0.05)
        raise WebSocketDisconnect()

    ws = FakeWebSocket(receive_side_effect=_slow_then_disconnect)

    with patch.object(live_mod, "HEARTBEAT_INTERVAL_SEC", 0.01):
        # Should complete cleanly without raising CancelledError.
        await live_mod._handle_stream(ws, uuid.uuid4())

    # Heartbeat fired at least once → loop was alive then cancelled
    heartbeat = [m for m in ws._json_messages if m.get("type") == "heartbeat"]
    assert len(heartbeat) >= 1


@pytest.mark.asyncio
async def test_ws_handle_stream_ack_payload_round_trip_with_nested_data():
    """WS: nested JSON payload is preserved verbatim in ACK."""
    nested = {
        "type": "screenshot",
        "data": {
            "frame_id": 42,
            "ocr_text": "Привет",
            "boxes": [[0, 0, 100, 100], [10, 20, 30, 40]],
        },
    }
    ws = FakeWebSocket(receive_side_effect=[
        json.dumps(nested),
        WebSocketDisconnect(),
    ])
    await live_mod._handle_stream(ws, uuid.uuid4())

    acks = [m for m in ws._json_messages if m.get("type") == "ack"]
    assert len(acks) == 1
    assert acks[0]["received_type"] == "screenshot"
    assert acks[0]["payload"] == nested
    # ts parses as ISO
    datetime.fromisoformat(acks[0]["ts"])


@pytest.mark.asyncio
async def test_ws_handle_stream_accept_is_called_first():
    """WS: websocket.accept() is invoked before any receive_text."""
    order = []

    async def _accept():
        order.append("accept")

    async def _receive_text():
        order.append("receive_text")
        raise WebSocketDisconnect()

    async def _send_json(payload):
        order.append("send_json")

    ws = FakeWebSocket(receive_side_effect=_receive_text)
    ws.accept.side_effect = _accept
    ws.send_json.side_effect = _send_json

    await live_mod._handle_stream(ws, uuid.uuid4())

    assert order[0] == "accept"
    assert "receive_text" in order


# ===========================================================================
# live_stream_ws — thin wrapper that delegates to _handle_stream
# ===========================================================================

@pytest.mark.asyncio
async def test_live_stream_ws_delegates_to_handle_stream(monkeypatch):
    """WebSocket route `live_stream_ws` calls `_handle_stream` directly."""
    called = {"args": None}

    async def _fake_handle(websocket, protocol_id):
        called["args"] = (id(websocket), protocol_id)

    monkeypatch.setattr(live_mod, "_handle_stream", _fake_handle)

    ws = FakeWebSocket(receive_side_effect=[])
    pid = uuid.uuid4()
    await live_mod.live_stream_ws(ws, pid)
    assert called["args"] is not None
    assert called["args"][1] == pid


# ===========================================================================
# HEARTBEAT_INTERVAL_SEC constant is sane (lines 32, 168)
# ===========================================================================

def test_heartbeat_interval_constant_is_30_seconds():
    """HEARTBEAT_INTERVAL_SEC is 30 by design."""
    assert live_mod.HEARTBEAT_INTERVAL_SEC == 30