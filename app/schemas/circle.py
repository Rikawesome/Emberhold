import uuid

from pydantic import BaseModel


class CreateCircleRequest(BaseModel):
    name: str


class CircleInviteRequest(BaseModel):
    kingdom_id: uuid.UUID


class DeclareWarRequest(BaseModel):
    defender_circle_id: uuid.UUID


class CircleResponse(BaseModel):
    id: uuid.UUID
    world_id: uuid.UUID
    bloodline_id: uuid.UUID
    name: str

    class Config:
        from_attributes = True
