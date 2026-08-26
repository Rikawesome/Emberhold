import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Circle(Base):
    __tablename__ = "circles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("worlds.id"))
    bloodline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bloodlines.id"))
    name: Mapped[str] = mapped_column(String(64))
    created_by_kingdom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CircleMember(Base):
    __tablename__ = "circle_members"

    circle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("circles.id"), primary_key=True)
    kingdom_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kingdoms.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # member | officer | leader
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class War(Base):
    __tablename__ = "wars"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("worlds.id"))
    attacker_circle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("circles.id"))
    defender_circle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("circles.id"))
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | ended
