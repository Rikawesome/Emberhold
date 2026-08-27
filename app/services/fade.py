"""The Fade win condition — see Section 8 of the design doc.

A bloodline enters Fade when its total Emberlight income (summed across all its
kingdoms' Wellsprings) drops below its total upkeep. It's recoverable — this module
just computes current standing, it doesn't lock in a loss by itself.

Scope note, called out explicitly: a bloodline *wins* only once every rival is in
sustained Fade with no mathematically viable recovery path. That specific
comparison — "no viable path back even with full cooperation" — is a game-design
judgment call best made with real playtesting numbers in hand, not guessed at here.
This module computes accurate standing (income vs. upkeep, in_fade flag); the full
win-check comparison is left as a follow-up in jobs/compute_bloodline_status.py.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kingdom import Kingdom, KingdomResource
from app.models.tile import Building, Tile, TileGarrison

# Upkeep formula constants — placeholders to balance during playtesting, not derived
# from anything. Named and centralized here so tuning later is a one-line change.
BASE_UPKEEP_PER_KINGDOM = 10.0
UPKEEP_PER_TROOP = 0.5
UPKEEP_PER_BUILDING = 2.0


async def compute_bloodline_income_and_upkeep(
    session: AsyncSession, world_id: uuid.UUID, bloodline_id: uuid.UUID
) -> tuple[float, float]:
    """Returns (total_income, total_upkeep) for a bloodline in a world.

    Income: sum of emberlight rate_per_hour across all its kingdoms' resource ledgers.
    Upkeep: a flat per-kingdom base, plus a per-troop and per-building cost — a
    reasonable starting formula, not a balanced one. Kindled's real-game high-upkeep
    trait (see the design doc's bloodline table) isn't modeled as a separate
    multiplier yet; add one here per-bloodline if that asymmetry needs to show up
    numerically rather than just narratively.
    """
    kingdom_ids = (
        await session.execute(select(Kingdom.id).where(Kingdom.world_id == world_id, Kingdom.bloodline_id == bloodline_id))
    ).scalars().all()

    if not kingdom_ids:
        return 0.0, 0.0

    income = await session.scalar(
        select(func.coalesce(func.sum(KingdomResource.rate_per_hour), 0)).where(
            KingdomResource.kingdom_id.in_(kingdom_ids),
            KingdomResource.resource_type == "emberlight",
        )
    )

    troop_total = await session.scalar(
        select(func.coalesce(func.sum(TileGarrison.quantity), 0))
        .join(Tile, Tile.id == TileGarrison.tile_id)
        .where(Tile.owner_kingdom_id.in_(kingdom_ids))
    )

    building_total = await session.scalar(
        select(func.count(Building.id))
        .join(Tile, Tile.id == Building.tile_id)
        .where(Tile.owner_kingdom_id.in_(kingdom_ids))
    )

    upkeep = (
        BASE_UPKEEP_PER_KINGDOM * len(kingdom_ids)
        + UPKEEP_PER_TROOP * float(troop_total or 0)
        + UPKEEP_PER_BUILDING * float(building_total or 0)
    )

    return float(income or 0), upkeep
