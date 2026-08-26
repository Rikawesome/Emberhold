import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Bloodline(Base):
    """Static reference data — five rows, seeded once. See app/data/bloodlines.py."""

    __tablename__ = "bloodlines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(32), unique=True)  # kindled | deepwell | wardens | driftborn | emberwrights
    name: Mapped[str] = mapped_column(String(64))
    resonance_type: Mapped[str] = mapped_column(String(32))  # emberdust | everfrost | farsight | galewisp | sparkstone
    strength_desc: Mapped[str] = mapped_column(String(512))
    weakness_desc: Mapped[str] = mapped_column(String(512))
