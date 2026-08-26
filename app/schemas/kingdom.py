import uuid
from datetime import datetime

from pydantic import BaseModel


class ResourceSnapshot(BaseModel):
    emberlight: float
    sustenance: float
    scrap: float
    # resonance amount uses the bloodline's own key, e.g. "emberdust" — added dynamically,
    # kept out of the fixed schema here since it varies by bloodline.


class KingdomResponse(BaseModel):
    id: uuid.UUID
    name: str
    bloodline: str
    world_id: uuid.UUID
    capital_tile_id: uuid.UUID | None
    kindling_shield_expires_at: datetime
    resources: dict[str, float]

    class Config:
        from_attributes = True


class BloodlineStatusEntry(BaseModel):
    key: str
    status: str  # strong | stable | struggling | at_risk
    total_income: float
    total_upkeep: float
    in_fade: bool


class BloodlineStatusResponse(BaseModel):
    bloodlines: list[BloodlineStatusEntry]
