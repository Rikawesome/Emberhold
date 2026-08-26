"""Live event push per kingdom: march arrived, incoming attack, Circle chat,
bloodline status changes. See Section 10 of the API reference doc for message shapes.

TODO: this in-memory connection registry works for a single process. Once you run
more than one API instance, swap it for Redis pub/sub (settings.redis_url is already
in config for this) so events broadcast across processes.
"""

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])

_connections: dict[uuid.UUID, list[WebSocket]] = {}


@router.websocket("/ws/kingdoms/{kingdom_id}")
async def kingdom_events(websocket: WebSocket, kingdom_id: uuid.UUID):
    # TODO: authenticate the connection (token as a query param or first message)
    # before accepting — this scaffold accepts unconditionally.
    await websocket.accept()
    _connections.setdefault(kingdom_id, []).append(websocket)
    try:
        while True:
            await websocket.receive_text()  # currently unused; keeps the connection alive
    except WebSocketDisconnect:
        _connections[kingdom_id].remove(websocket)


async def push_event(kingdom_id: uuid.UUID, event: dict) -> None:
    """Call this from services/jobs after something happens that a kingdom's
    client should know about immediately (march arrived, incoming attack, etc.).
    """
    for ws in _connections.get(kingdom_id, []):
        await ws.send_json(event)
