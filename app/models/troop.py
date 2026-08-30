import uuid
from datetime import datetime

from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TroopType(Base):
    """Static reference data — seeded from app/data/troop_types.py. Signature troops
    require both a bloodline_id and a resonance-typed resource to train (enforced in services/).
    """

    __tablename__ = "troop_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bloodline_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bloodlines.id"), nullable=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(16))  # basic | support | signature
    ability_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)          # attack, defense, etc.
    resource_costs: Mapped[dict] = mapped_column(JSONB, default=dict)  # { "gold": 8, "wood": 4, ... }


class TrainingQueue(Base):
    __tablename__ = "training_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kingdom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"))
    tile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tiles.id"))
    troop_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("troop_types.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress | complete

class TroopQueue(TrainingQueue):
    """Backward compatible alias for TrainingQueue used in older tests.
    Inherit all fields and behavior unchanged.
    """
    pass
