"""Live Mode (Телемост) — US-018..021, API §18.

Endpoints:
    POST /live/start                  — create a protocol in 'live' status
    POST /live/{protocol_id}/stop     — stop live mode (status → 'loaded')
    WS   /live/{protocol_id}/stream   — bidirectional event stream + heartbeat

The WebSocket endpoint is intentionally simple (ping/pong + echo) so the
contract is testable end-to-end. Replace the body of `_handle_stream()`
with real TTS/screenshot/STT dispatching when ready.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import Protocol
from app.db.session import get_db
from app.schemas import LiveStartRequest, LiveStartResponse

logger = get_logger(__name__)
router = APIRouter()

# Heartbeat interval — keep alive while no events flow (seconds)
HEARTBEAT_INTERVAL_SEC = 30


# ============================================================================
# POST /live/start
# ============================================================================


@router.post(
    "/live/start",
    response_model=LiveStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start Live Mode (Телемост)",
)
async def start_live(
    req: LiveStartRequest,
    db: AsyncSession = Depends(get_db),
) -> LiveStartResponse:
    """US-018 — create a protocol in 'live' status.

    Returns the WebSocket URL the client should connect to for the
    live event stream, plus the Телемост iframe URL.
    """
    from datetime import date as date_cls

    protocol_id = uuid.uuid4()
    protocol = Protocol(
        id=protocol_id,
        title=req.title,
        date=date_cls.today(),
        status="live",
        agenda=None,
    )
    db.add(protocol)
    await db.commit()
    await db.refresh(protocol)

    websocket_url = f"ws://{settings.backend_host}:{settings.backend_port}{settings.api_prefix}/live/{protocol_id}/stream"

    logger.info(
        "live_started",
        protocol_id=str(protocol_id),
        title=req.title,
        telemost_url=req.telemost_url,
    )

    return LiveStartResponse(
        protocol_id=protocol_id,
        live_session_id=uuid.uuid4(),  # session-specific id; could be persisted later
        websocket_url=websocket_url,
        telemost_iframe_url=req.telemost_url,
        started_at=datetime.now(timezone.utc),
    )


# ============================================================================
# POST /live/{protocol_id}/stop
# ============================================================================


@router.post(
    "/live/{protocol_id}/stop",
    summary="Stop Live Mode",
)
async def stop_live(
    protocol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """US-020 — stop live mode for a protocol. Status → 'loaded'."""
    protocol = await db.get(Protocol, protocol_id)
    if not protocol or protocol.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Протокол не найден",
        )

    if protocol.status != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Протокол не в режиме live (status={protocol.status})",
        )

    protocol.status = "loaded"
    await db.commit()
    await db.refresh(protocol)

    logger.info("live_stopped", protocol_id=str(protocol_id))
    return {
        "protocol_id": str(protocol_id),
        "status": protocol.status,
        "stopped_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# WebSocket /live/{protocol_id}/stream
# ============================================================================


async def _handle_stream(websocket: WebSocket, protocol_id: uuid.UUID) -> None:
    """WebSocket handler: heartbeat every 30s + echo events.

    Wireframe:
        client → server: JSON {"type": "screenshot", "data": {...}}
        client → server: "ping"             → server: "pong"
        server → client: JSON {"type": "heartbeat", "ts": ...}  every 30s
        server → client: echoes JSON {"type": "ack", ...}
    """
    await websocket.accept()
    logger.info("ws_connected", protocol_id=str(protocol_id))

    async def heartbeat_loop() -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                )
        except (asyncio.CancelledError, Exception):
            # Connection closed mid-loop; swallow.
            return

    hb_task = asyncio.create_task(heartbeat_loop())
    try:
        while True:
            # Wait for next message
            raw = await websocket.receive_text()

            # Plain-text ping/pong (cheap liveness check)
            if raw == "ping":
                await websocket.send_text("pong")
                continue

            # Try to parse as JSON
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "message": "Invalid JSON"}
                )
                continue

            msg_type = payload.get("type", "unknown")

            # Echo with ACK so client knows the server received it
            await websocket.send_json(
                {
                    "type": "ack",
                    "received_type": msg_type,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "payload": payload,
                }
            )

            logger.info(
                "ws_event_received",
                protocol_id=str(protocol_id),
                type=msg_type,
            )
    except WebSocketDisconnect:
        logger.info("ws_disconnected", protocol_id=str(protocol_id))
    except Exception as e:
        logger.exception(
            "ws_error",
            protocol_id=str(protocol_id),
            error=str(e),
        )
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass


@router.websocket("/live/{protocol_id}/stream")
async def live_stream_ws(
    websocket: WebSocket,
    protocol_id: uuid.UUID,
) -> None:
    """US-021 — WebSocket endpoint for live protocol stream.

    Accepts the connection regardless of protocol existence (we don't
    enforce DB lookup here because the session might be very short-lived).
    Add a DB check if your threat model requires it.
    """
    await _handle_stream(websocket, protocol_id)
