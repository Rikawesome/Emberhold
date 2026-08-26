import uuid
from datetime import datetime

from pydantic import BaseModel


class TileResponse(BaseModel):
    id: uuid.UUID
    x: int
    y: int
    terrain_type: str
    resonance_affinity: str | None
    owner_kingdom_id: uuid.UUID | None
    garrison_summary: int  # a count only — full breakdown is owner/Wardens-scout only


class TileListResponse(BaseModel):
    tiles: list[TileResponse]


class BuildRequest(BaseModel):
    building_type: str


class BuildQueueEntry(BaseModel):
    queue_id: uuid.UUID
    tile_id: uuid.UUID
    building_type: str
    completes_at: datetime
