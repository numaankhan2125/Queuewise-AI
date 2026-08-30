"""WebSocket endpoint: clients subscribe to topics and receive live events."""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.ws import hub

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, topic: str):
    await hub.connect(topic, ws)
    try:
        while True:
            # keepalive; client messages are ignored (or could ping/pong)
            await asyncio.sleep(3600)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        hub.disconnect(topic, ws)
