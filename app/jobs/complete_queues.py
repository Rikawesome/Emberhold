"""Scheduled job for completing due building and training queues."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session
from app.models.tile import Building, BuildingQueue, TileGarrison
from app.models.troop import TrainingQueue

logger = logging.getLogger(__name__)


async def process_queues(session: AsyncSession) -> None:
    """Complete all currently due building and training queues.

    The caller owns the transaction. This makes the lifecycle directly
    testable while the scheduled `run()` entrypoint below still owns its
    production session.
    """
    now = datetime.now(timezone.utc)

    due_buildings = (
        await session.execute(
            select(BuildingQueue)
            .where(
                BuildingQueue.status == "in_progress",
                BuildingQueue.completes_at <= now,
            )
            .with_for_update()
        )
    ).scalars().all()

    for entry in due_buildings:
        session.add(
            Building(
                tile_id=entry.tile_id,
                building_type=entry.building_type,
            )
        )
        entry.status = "complete"

    due_training = (
        await session.execute(
            select(TrainingQueue)
            .where(
                TrainingQueue.status == "in_progress",
                TrainingQueue.completes_at <= now,
            )
            .with_for_update()
        )
    ).scalars().all()

    for entry in due_training:
        garrison = await session.scalar(
            select(TileGarrison)
            .where(
                TileGarrison.tile_id == entry.tile_id,
                TileGarrison.kingdom_id == entry.kingdom_id,
                TileGarrison.troop_type_id == entry.troop_type_id,
            )
            .with_for_update()
        )

        if garrison:
            garrison.quantity += entry.quantity
        else:
            session.add(
                TileGarrison(
                    tile_id=entry.tile_id,
                    kingdom_id=entry.kingdom_id,
                    troop_type_id=entry.troop_type_id,
                    quantity=entry.quantity,
                )
            )

        entry.status = "complete"


async def run() -> None:
    """Scheduled entrypoint used by the production job runner."""
    async with async_session() as session:
        try:
            await process_queues(session)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("complete_queues job failed")
