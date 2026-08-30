"""In-process WebSocket hub: topic-based pub/sub for live queue updates.

Topics:
    token:{id}      -> one student's token page
    counter:{id}    -> staff workspace
    display:{loc}   -> public "NOW SERVING" board
    location:{loc}  -> portal live-queue cards
    cqdcc           -> administrator command center KPIs
"""
import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket


class ConnectionHub:
    def __init__(self):
        self._conns: dict[str, set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self):
        self._loop = asyncio.get_running_loop()

    async def connect(self, topic: str, ws: WebSocket):
        await ws.accept()
        self._conns[topic].add(ws)

    def disconnect(self, topic: str, ws: WebSocket):
        self._conns[topic].discard(ws)

    async def _send(self, ws: WebSocket, payload: dict):
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            pass

    def publish(self, topics: list[str], event_type: str, data: dict):
        """Thread/task-safe fire-and-forget broadcast."""
        if self._loop is None or self._loop.is_closed():
            return
        message = {"type": event_type, **data}
        for topic in topics:
            for ws in list(self._conns.get(topic, ())):
                asyncio.run_coroutine_threadsafe(self._send(ws, message), self._loop)

    async def publish_direct(self, topic: str, event_type: str, data: dict):
        message = {"type": event_type, **data}
        for ws in list(self._conns.get(topic, ())):
            await self._send(ws, message)


hub = ConnectionHub()


def topics_for_token(token) -> list[str]:
    return [
        f"token:{token.id}",
        f"counter:{token.counter_id}",
        f"display:{token.location_id}",
        f"location:{token.location_id}",
        "cqdcc",
    ]
