"""Lazy-tick resource production. Nothing else (buildings, troops, marches) can
meaningfully validate a cost until this works, so it's built first per the suggested
build order in the API reference doc.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kingdom import KingdomResource


async def collect_resource(session: AsyncSession, kingdom_id: uuid.UUID, resource_type: str) -> KingdomResource:
    """Materializes elapsed production into `amount` and resets the clock. Call this
    before reading or spending a balance so it reflects real elapsed time.
    """
    row = await session.scalar(
        select(KingdomResource).where(
            KingdomResource.kingdom_id == kingdom_id,
            KingdomResource.resource_type == resource_type,
        )
    )
    if row is None:
        raise ValueError(f"No {resource_type} ledger for kingdom {kingdom_id}")

    now = datetime.now(timezone.utc)
    elapsed_hours = (now - row.last_collected_at).total_seconds() / 3600
    row.amount += max(elapsed_hours, 0) * row.rate_per_hour
    row.last_collected_at = now
    return row


async def collect_all(session: AsyncSession, kingdom_id: uuid.UUID) -> dict[str, float]:
    rows = (
        await session.execute(select(KingdomResource).where(KingdomResource.kingdom_id == kingdom_id))
    ).scalars().all()

    now = datetime.now(timezone.utc)
    result: dict[str, float] = {}
    for row in rows:
        elapsed_hours = (now - row.last_collected_at).total_seconds() / 3600
        row.amount += max(elapsed_hours, 0) * row.rate_per_hour
        row.last_collected_at = now
        result[row.resource_type] = row.amount
    return result


async def spend(session: AsyncSession, kingdom_id: uuid.UUID, costs: dict[str, float]) -> None:
    """Validates and deducts a cost dict like {"emberlight": 15, "wood": 5}. Raises
    ValueError if any resource is insufficient — callers should catch this and return
    a 400 to the client. Collects first so the balance checked is current, not stale.
    """
    for resource_type, cost in costs.items():
        row = await collect_resource(session, kingdom_id, resource_type)
        if row.amount < cost:
            raise ValueError(f"Insufficient {resource_type}: have {row.amount:.1f}, need {cost}")

    # Second pass to actually deduct, now that we know every resource is sufficient —
    # avoids partially spending if a later resource in the dict turns out short.
    for resource_type, cost in costs.items():
        row = await collect_resource(session, kingdom_id, resource_type)
        row.amount -= cost
