import uuid
from datetime import datetime

from pydantic import BaseModel


class TroopStackEntry(BaseModel):
    troop_type_id: uuid.UUID
    quantity: int


class MarchRequest(BaseModel):
    origin_tile_id: uuid.UUID
    target_tile_id: uuid.UUID
    troop_stack: list[TroopStackEntry]
    march_type: str  # attack | reinforce | return


class MarchResponse(BaseModel):
    march_id: uuid.UUID
    departure_at: datetime
    arrival_at: datetime


class MarchStatusEntry(BaseModel):
    march_id: uuid.UUID
    origin_tile_id: uuid.UUID
    target_tile_id: uuid.UUID
    march_type: str
    status: str
    arrival_at: datetime
