import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class March(Base):
    __tablename__ = "marches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("worlds.id"))
    kingdom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"))
    origin_tile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tiles.id"))
    target_tile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tiles.id"))
    troop_stack: Mapped[list] = mapped_column(JSONB)  # [{ "troop_type_id": ..., "quantity": ... }]
    march_type: Mapped[str] = mapped_column(String(16))  # attack | reinforce | return
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="marching")  # marching | resolved | recalled

    version: Mapped[int] = mapped_column(Integer, default=0)


class CombatLog(Base):
    __tablename__ = "combat_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    march_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("marches.id"))
    attacker_kingdom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"))
    defender_kingdom_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"), nullable=True)
    result: Mapped[dict] = mapped_column(JSONB)  # full breakdown: power totals, abilities applied, outcome
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
