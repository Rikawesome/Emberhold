import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Integer, Float, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class World(Base):
    __tablename__ = "worlds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | ended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Kingdom(Base):
    __tablename__ = "kingdoms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("players.id"))
    world_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("worlds.id"))
    bloodline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bloodlines.id"))
    name: Mapped[str] = mapped_column(String(64))
    capital_tile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tiles.id", use_alter=True, name="fk_kingdoms_capital_tile_id"),
        nullable=True,
    )
    founded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kindling_shield_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    flash_march_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # optimistic concurrency — bump on every mutating write, check-and-increment in services/
    version: Mapped[int] = mapped_column(Integer, default=0)



class KingdomResource(Base):
    """Lazy-tick resource ledger. Balance is computed as elapsed_time * rate_per_hour
    since last_collected_at whenever it's read or spent, then persisted back here.
    """

    __tablename__ = "kingdom_resources"

    kingdom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(32), primary_key=True)  # emberlight | sustenance | scrap | <resonance>
    amount: Mapped[float] = mapped_column(Float, default=0)
    rate_per_hour: Mapped[float] = mapped_column(Float, default=0)
    last_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BloodlineStatus(Base):
    """Recomputed periodically by the compute_bloodline_status job. Drives the Fade win condition."""

    __tablename__ = "bloodline_status"

    world_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("worlds.id"), primary_key=True)
    bloodline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bloodlines.id"), primary_key=True)
    total_income: Mapped[float] = mapped_column(Float, default=0)
    total_upkeep: Mapped[float] = mapped_column(Float, default=0)
    in_fade: Mapped[bool] = mapped_column(Boolean, default=False)
    fade_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
