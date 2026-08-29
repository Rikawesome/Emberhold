import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TroopStackEntry(BaseModel):
    troop_type_id: uuid.UUID
    quantity: int = Field(gt=0)


class MarchRequest(BaseModel):
    origin_tile_id: uuid.UUID
    target_tile_id: uuid.UUID
    troop_stack: list[TroopStackEntry] = Field(min_length=1)
    march_type: str

    @field_validator("troop_stack")
    @classmethod
    def validate_troop_stack(cls, value):
        troop_type_ids = [entry.troop_type_id for entry in value]

        if len(troop_type_ids) != len(set(troop_type_ids)):
            raise ValueError("Duplicate troop types are not allowed")

        return value


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