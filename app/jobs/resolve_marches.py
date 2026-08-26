"""Scheduled job — finds marches whose arrival_at has passed and resolves them via
services/combat.py, one at a time in its own transaction so a failure on one march
doesn't roll back others in the same batch.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import async_session
from app.models.march import March
from app.routers.ws import push_event
from app.services.combat import resolve_march

logger = logging.getLogger(__name__)


async def run() -> None:
    async with async_session() as session:
        due = (
            await session.execute(
                select(March).where(March.status == "marching", March.arrival_at <= datetime.now(timezone.utc))
            )
        ).scalars().all()

    for march in due:
        async with async_session() as session:
            try:
                log = await resolve_march(session, march.id)
                await session.commit()
                await push_event(
                    march.kingdom_id,
                    {"type": "march_arrived", "march_id": str(march.id), "result": log.result.get("outcome"),
                     "combat_log_id": str(log.id)},
                )
            except Exception:
                await session.rollback()
                logger.exception("Failed to resolve march %s", march.id)
