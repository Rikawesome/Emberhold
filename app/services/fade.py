"""The Fade win condition — see Section 8 of the design doc.

A bloodline enters Fade when its total Emberlight income (summed across all its
kingdoms' Wellsprings) drops below its total upkeep. It's recoverable — this module
just computes current standing, it doesn't lock in a loss by itself. A bloodline
*wins* only once every rival is in sustained Fade with no mathematically viable
recovery path — that comparison is a TODO, build and test it against hand-picked
numbers first per the API reference doc's testing section.
"""

import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kingdom import Kingdom, KingdomResource


async def compute_bloodline_income_and_upkeep(
    session: AsyncSession, world_id: uuid.UUID, bloodline_id: uuid.UUID
) -> tuple[float, float]:
    """Returns (total_income, total_upkeep) for a bloodline in a world.

    Income: sum of emberlight rate_per_hour across all its kingdoms' resource ledgers.
    Upkeep: TODO — needs a real formula tied to population/troops/buildings, which
    isn't modeled yet in this scaffold. Returning 0 for now so callers don't break;
    replace before relying on Fade status for anything real.
    """
    income = await session.scalar(
        select(func.coalesce(func.sum(KingdomResource.rate_per_hour), 0))
        .join(Kingdom, Kingdom.id == KingdomResource.kingdom_id)
        .where(
            Kingdom.world_id == world_id,
            Kingdom.bloodline_id == bloodline_id,
            KingdomResource.resource_type == "emberlight",
        )
    )
    upkeep = 0.0  # TODO
    return float(income or 0), upkeep
