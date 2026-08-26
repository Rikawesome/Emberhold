"""Scheduled job — recomputes total_income/total_upkeep per bloodline per world and
updates in_fade. Runs every few minutes; this is a world-scale aggregate, not
something that needs per-action consistency. See services/fade.py for the math
(upkeep is currently a TODO there — this job will under-report Fade until it's real).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import async_session
from app.models.kingdom import BloodlineStatus, World
from app.models.player import Bloodline
from app.services.fade import compute_bloodline_income_and_upkeep

logger = logging.getLogger(__name__)


async def run() -> None:
    async with async_session() as session:
        try:
            worlds = (await session.execute(select(World).where(World.status == "active"))).scalars().all()
            bloodlines = (await session.execute(select(Bloodline))).scalars().all()

            for world in worlds:
                for bloodline in bloodlines:
                    income, upkeep = await compute_bloodline_income_and_upkeep(session, world.id, bloodline.id)
                    in_fade = income < upkeep

                    row = await session.get(BloodlineStatus, (world.id, bloodline.id))
                    if row is None:
                        row = BloodlineStatus(world_id=world.id, bloodline_id=bloodline.id)
                        session.add(row)

                    was_in_fade = row.in_fade
                    row.total_income = income
                    row.total_upkeep = upkeep
                    row.in_fade = in_fade
                    row.updated_at = datetime.now(timezone.utc)
                    if in_fade and not was_in_fade:
                        row.fade_entered_at = row.updated_at

                    # TODO: check the actual win condition here — every rival bloodline
                    # in sustained Fade with no viable recovery path — and mark the
                    # world ended if so. Left out until upkeep math is real.

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("compute_bloodline_status job failed")
