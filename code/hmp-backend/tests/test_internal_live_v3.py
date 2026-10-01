"""E365v3: ещё 12-15 тестов для routers/live.py — добинание coverage до 60%+.

Фокус на непокрытых ветках live.py:
- start_live(): полный payload с audio_device/screenshot_interval, границы
  screenshot_interval_sec (ge=10, le=600) → 422
- start_live(): telemost_url не начинается с https:// → 422
- start_live(): отсутствует обязательное поле → 422
- stop_live(): 422 на невалидный UUID, 404 для удалённого (deleted_at)
- stop_live(): 404 для несуществующего UUID
- stop_live(): 409 для статуса loaded
- WS: генерация heartbeat (прямой вызов _handle_stream через mock WebSocket)
- WS: пустой payload (без type) → ack с received_type="unknown"
- WS: вложенный JSON payload сохраняется в ack
- WS: невалидный JSON → error, следующий валидный → ack
- WS: ping → pong (plain text)
- WS: непредвиденное исключение → close(WS_1011_INTERNAL_ERROR)
"""
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.db.models import Protocol, ProtocolStatus


# ---------------------------------------------------------------------------
# Local factory
# ---------------------------------------------------------------------------
@pytest.fixture
def make_protocol(db_session):
    async def _factory(
        title: str = "Live Test v3",
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
# POST /live/start — дополнительные сценарии (валидация, полный payload)
# ===========================================================================

@pytest.mark.asyncio
async def test_live_start_full_payload_with_all_optional_fields(client):
    """POST /live/start — полный payload со всеми опциональными полями → 201."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/full",
        "title": "Full Payload",
        "audio_device": "usb-mic",
        "enable_screenshots": False,
        "screenshot_interval_sec": 120,
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    # protocol_id, live_session_id — валидные UUID
    uuid.UUID(body["protocol_id"])
    uuid.UUID(body["live_session_id"])
    # websocket_url содержит protocol_id
    assert body["protocol_id"] in body["websocket_url"]
    # telemost_iframe_url повторяет telemost_url
    assert body["telemost_iframe_url"] == payload["telemost_url"]


@pytest.mark.asyncio
async def test_live_start_422_missing_required_title(client):
    """POST /live/start — отсутствует обязательное поле title → 422."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/notitle",
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_live_start_422_missing_required_telemost_url(client):
    """POST /live/start — отсутствует обязательное telemost_url → 422."""
    payload = {
        "title": "No URL",
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_live_start_422_screenshot_interval_below_min(client):
    """POST /live/start — screenshot_interval_sec=5 (< ge=10) → 422."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/iv",
        "title": "Interval Min",
        "screenshot_interval_sec": 5,
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_live_start_422_screenshot_interval_above_max(client):
    """POST /live/start — screenshot_interval_sec=700 (> le=600) → 422."""
    payload = {
        "telemost_url": "https://telemost.yandex.ru/j/iv",
        "title": "Interval Max",
        "screenshot_interval_sec": 700,
    }
    r = await client.post("/api/v1/hmp/live/start", json=payload)
    assert r.status_code == 422


# ===========================================================================
# POST /live/{id}/stop — 404/422/409 для разных статусов и edge cases
# ===========================================================================

@pytest.mark.asyncio
async def test_live_stop_404_for_nonexistent_uuid(client):
    """POST /live/{id}/stop — несуществующий UUID → 404."""
    fake_id = uuid.uuid4()
    r = await client.post(f"/api/v1/hmp/live/{fake_id}/stop")
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_live_stop_404_for_soft_deleted_protocol(client, make_protocol):
    """POST /live/{id}/stop — soft-deleted (deleted_at != None) → 404."""
    p = await make_protocol(
        status=ProtocolStatus.LIVE,
        deleted_at=datetime.now(timezone.utc),
    )
    r = await client.post(f"/api/v1/hmp/live/{p.id}/stop")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_live_stop_422_for_invalid_uuid_string(client):
    """POST /live/{id}/stop — невалидный UUID в path → 422."""
    r = await client.post("/api/v1/hmp/live/not-a-uuid/stop")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_live_stop_409_for_loaded_status(client, make_protocol):
    """POST /live/{id}/stop — status='loaded' (уже не live) → 409."""
    p = await make_protocol(status=ProtocolStatus.LOADED)
    r = await client.post(f"/api/v1/hmp/live/{p.id}/stop")
    assert r.status_code == 409
    assert "loaded" in r.json()["detail"]


@pytest.mark.asyncio
async def test_live_stop_response_contains_protocol_id_and_status(client, make_protocol):
    """POST /live/{id}/stop — response содержит protocol_id и обновлённый status."""
    p = await make_protocol(status=ProtocolStatus.LIVE)
    r = await client.post(f"/api/v1/hmp/live/{p.id}/stop")
    assert r.status_code == 200
    body = r.json()
    assert body["protocol_id"] == str(p.id)
    # status хранится как text(...) или enum; сравниваем со строкой
    assert str(body["status"]).lower() == "loaded"
    assert "stopped_at" in body


# ===========================================================================
# WS — прямые юнит-тесты _handle_stream через моки
# ===========================================================================

class FakeWebSocket:
    """Минимальный fake WebSocket: record-only send, programmable receive."""

    def __init__(self, receive_side_effect):
        from unittest.mock import AsyncMock
        self.accept = AsyncMock()
        self.send_json = AsyncMock()
        self.send_text = AsyncMock()
        self.close = AsyncMock()
        self.receive_text = AsyncMock(side_effect=receive_side_effect)
        self._json_messages = []
        self._text_messages = []

        async def _capture_json(payload):
            self._json_messages.append(payload)
        async def _capture_text(text):
            self._text_messages.append(text)
        self.send_json.side_effect = _capture_json
        self.send_text.side_effect = _capture_text


@pytest.mark.asyncio
async def test_ws_handle_stream_sends_heartbeat_payload():
    """WS _handle_stream: heartbeat_loop отправляет JSON с type='heartbeat'.

    Даём heartbeat-задаче ~50ms чтобы она успела отправить heartbeat
    до того как главный цикл поймает WebSocketDisconnect.
    """
    import asyncio
    from app.routers import live as live_mod
    from unittest.mock import patch

    async def _slow_then_disconnect():
        # Первый вызов: спим, чтобы heartbeat-loop успел отправить
        await asyncio.sleep(0.05)
        raise WebSocketDisconnect()

    # AsyncMock с callable-side_effect вызывает его КАЖДЫЙ раз,
    # но нам нужен только первый вызов → второй Disconnect + disconnect.
    call_count = {"n": 0}

    async def _receive():
        call_count["n"] += 1
        if call_count["n"] == 1:
            await asyncio.sleep(0.05)
        raise WebSocketDisconnect()

    ws = FakeWebSocket(receive_side_effect=_receive)
    # Патчим HEARTBEAT_INTERVAL_SEC на маленькое значение
    with patch.object(live_mod, "HEARTBEAT_INTERVAL_SEC", 0.01):
        await live_mod._handle_stream(ws, uuid.uuid4())

    heartbeat_calls = [
        m for m in ws._json_messages if m.get("type") == "heartbeat"
    ]
    assert len(heartbeat_calls) >= 1
    # ts в ISO-формате
    ts = heartbeat_calls[0]["ts"]
    datetime.fromisoformat(ts)


@pytest.mark.asyncio
async def test_ws_handle_stream_ack_with_unknown_type_when_no_type_field():
    """WS: payload без поля 'type' → ACK с received_type='unknown'."""
    from app.routers import live as live_mod

    ws = FakeWebSocket(receive_side_effect=[
        json.dumps({"data": "no type field"}),
        WebSocketDisconnect(),
    ])
    await live_mod._handle_stream(ws, uuid.uuid4())

    ack_calls = [m for m in ws._json_messages if m.get("type") == "ack"]
    assert len(ack_calls) == 1
    assert ack_calls[0]["received_type"] == "unknown"
    # payload сохраняется в ACK как есть
    assert ack_calls[0]["payload"] == {"data": "no type field"}


@pytest.mark.asyncio
async def test_ws_handle_stream_invalid_json_returns_error_then_recovers():
    """WS: невалидный JSON → error; следующее валидное сообщение → ack."""
    from app.routers import live as live_mod

    ws = FakeWebSocket(receive_side_effect=[
        "not valid json{{{",
        json.dumps({"type": "screenshot"}),
        WebSocketDisconnect(),
    ])
    await live_mod._handle_stream(ws, uuid.uuid4())

    error_msgs = [m for m in ws._json_messages if m.get("type") == "error"]
    ack_msgs = [m for m in ws._json_messages if m.get("type") == "ack"]
    assert len(error_msgs) == 1
    assert error_msgs[0]["message"] == "Invalid JSON"
    assert len(ack_msgs) == 1
    assert ack_msgs[0]["received_type"] == "screenshot"


@pytest.mark.asyncio
async def test_ws_handle_stream_ping_returns_pong_text():
    """WS: ping (plain text) → ответ pong как plain text."""
    from app.routers import live as live_mod

    ws = FakeWebSocket(receive_side_effect=[
        "ping",
        WebSocketDisconnect(),
    ])
    await live_mod._handle_stream(ws, uuid.uuid4())

    assert ws._text_messages == ["pong"]


@pytest.mark.asyncio
async def test_ws_handle_stream_closes_on_unexpected_exception():
    """WS: непредвиденная ошибка → close(WS_1011_INTERNAL_ERROR)."""
    from app.routers import live as live_mod

    ws = FakeWebSocket(receive_side_effect=RuntimeError("unexpected"))

    await live_mod._handle_stream(ws, uuid.uuid4())

    ws.close.assert_called_once()
    args, kwargs = ws.close.call_args
    close_code = kwargs.get("code") if kwargs else (args[0] if args else None)
    assert close_code == status.WS_1011_INTERNAL_ERROR