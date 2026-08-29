import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TrainRequest(BaseModel):
    troop_type_id: uuid.UUID
    quantity: int = Field(gt=0)


class TrainingQueueEntry(BaseModel):
    queue_id: uuid.UUID
    tile_id: uuid.UUID
    troop_type: str
    quantity: int
    completes_at: datetime