import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    DateTime,
    func,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Tile(Base):
    __tablename__ = "tiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("worlds.id"))
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    terrain_type: Mapped[str] = mapped_column(String(16))  # wellspring | grove | ashfield | plain
    resonance_affinity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_kingdom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kingdoms.id"), nullable=True
    )
    base_yield: Mapped[dict] = mapped_column(JSONB, default=dict)

    # optimistic concurrency — checked during combat resolution so two simultaneous
    # marches against the same tile can't double-resolve
    version: Mapped[int] = mapped_column(Integer, default=0)


class TileGarrison(Base):
    __tablename__ = "tile_garrisons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tiles.id"))
    kingdom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"))
    troop_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("troop_types.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)


class Building(Base):
    __tablename__ = "buildings"

    __table_args__ = (
        UniqueConstraint(
            "tile_id",
            name="uq_buildings_tile_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tiles.id"),
    )
    building_type: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(Integer, default=1)
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

class BuildingQueue(Base):
    __tablename__ = "building_queue"

    __table_args__ = (
        Index(
            "uq_building_queue_active_tile",
            "tile_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tiles.id"),
    )
    building_type: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16),
        default="in_progress",
    )