"""Scheduled job — completes any building or training queue entries whose
completes_at has passed: marks the building built, or adds trained troops to the
tile's garrison.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import async_session
from app.models.tile import Building, BuildingQueue, TileGarrison
from app.models.troop import TrainingQueue

logger = logging.getLogger(__name__)


async def run() -> None:
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        try:
            due_buildings = (
                await session.execute(
                    select(BuildingQueue).where(BuildingQueue.status == "in_progress", BuildingQueue.completes_at <= now)
                )
            ).scalars().all()

            for entry in due_buildings:
                session.add(Building(tile_id=entry.tile_id, building_type=entry.building_type))
                entry.status = "complete"

            due_training = (
                await session.execute(
                    select(TrainingQueue).where(TrainingQueue.status == "in_progress", TrainingQueue.completes_at <= now)
                )
            ).scalars().all()

            for entry in due_training:
                garrison = await session.scalar(
                    select(TileGarrison).where(
                        TileGarrison.tile_id == entry.tile_id,
                        TileGarrison.kingdom_id == entry.kingdom_id,
                        TileGarrison.troop_type_id == entry.troop_type_id,
                    )
                )
                if garrison:
                    garrison.quantity += entry.quantity
                else:
                    session.add(
                        TileGarrison(
                            tile_id=entry.tile_id, kingdom_id=entry.kingdom_id,
                            troop_type_id=entry.troop_type_id, quantity=entry.quantity,
                        )
                    )
                entry.status = "complete"

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("complete_queues job failed")
