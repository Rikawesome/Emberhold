"""Lazy-tick resource production.

Resource balances are materialized from elapsed time whenever they are read
or spent.

All mutating resource operations lock their ledger rows with SELECT ... FOR
UPDATE so concurrent requests cannot overspend the same resource balance.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kingdom import KingdomResource


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _materialize(row: KingdomResource, now: datetime) -> None:
    elapsed_hours = (
        now - row.last_collected_at
    ).total_seconds() / 3600

    row.amount += max(elapsed_hours, 0) * row.rate_per_hour
    row.last_collected_at = now


async def collect_resource(
    session: AsyncSession,
    kingdom_id: uuid.UUID,
    resource_type: str,
) -> KingdomResource:
    """Materialize one resource balance.

    The ledger row is locked so concurrent reads/spends cannot both mutate
    the same stale balance.
    """

    row = await session.scalar(
        select(KingdomResource)
        .where(
            KingdomResource.kingdom_id == kingdom_id,
            KingdomResource.resource_type == resource_type,
        )
        .with_for_update()
    )

    if row is None:
        raise ValueError(
            f"No {resource_type} ledger for kingdom {kingdom_id}"
        )

    _materialize(row, _now())
    return row


async def collect_all(
    session: AsyncSession,
    kingdom_id: uuid.UUID,
) -> dict[str, float]:
    """Materialize every resource balance for a kingdom."""

    rows = (
        await session.execute(
            select(KingdomResource)
            .where(
                KingdomResource.kingdom_id == kingdom_id
            )
            .with_for_update()
        )
    ).scalars().all()

    now = _now()
    result: dict[str, float] = {}

    for row in rows:
        _materialize(row, now)
        result[row.resource_type] = row.amount

    return result


async def spend(
    session: AsyncSession,
    kingdom_id: uuid.UUID,
    costs: dict[str, float],
) -> None:
    """Atomically validate and deduct a set of resource costs.

    Every required ledger row is locked before any balance is checked.
    This prevents concurrent requests from overspending the same resources.

    Raises ValueError if:
      - a cost is negative
      - a required resource ledger does not exist
      - any resource has insufficient funds
    """

    if not costs:
        return

    # Negative costs would effectively create resources.
    for resource_type, cost in costs.items():
        if cost < 0:
            raise ValueError(
                f"Resource cost cannot be negative: "
                f"{resource_type}={cost}"
            )

    # Lock rows in deterministic order.
    # Deterministic ordering reduces deadlock risk when two transactions
    # spend multiple resources at the same time.
    resource_types = sorted(costs)

    rows = (
        await session.execute(
            select(KingdomResource)
            .where(
                KingdomResource.kingdom_id == kingdom_id,
                KingdomResource.resource_type.in_(resource_types),
            )
            .order_by(KingdomResource.resource_type)
            .with_for_update()
        )
    ).scalars().all()

    rows_by_type = {
        row.resource_type: row
        for row in rows
    }

    # Verify every requested resource has a ledger.
    for resource_type in resource_types:
        if resource_type not in rows_by_type:
            raise ValueError(
                f"No {resource_type} ledger for kingdom {kingdom_id}"
            )

    # Materialize every balance exactly once.
    now = _now()

    for resource_type in resource_types:
        row = rows_by_type[resource_type]
        _materialize(row, now)

    # Validate the complete transaction before changing anything.
    for resource_type, cost in costs.items():
        row = rows_by_type[resource_type]

        if row.amount < cost:
            raise ValueError(
                f"Insufficient {resource_type}: "
                f"have {row.amount:.1f}, need {cost}"
            )

    # All resources are affordable, so deduction can safely happen.
    for resource_type, cost in costs.items():
        rows_by_type[resource_type].amount -= cost


BUILDING_YIELD_BONUSES = {
    "wellspring_tap": {"emberlight": 15},
    "grove_farm": {"sustenance": 15},
    "ashfield_works": {"scrap": 15},
}

BASE_KINGDOM_PRODUCTION = {
    "emberlight": 10.0,
    "sustenance": 10.0,
    "scrap": 10.0,
}


async def recalculate_production(
    session: AsyncSession,
    kingdom_id: uuid.UUID,
) -> dict[str, float]:
    """Recalculates and updates rate_per_hour for all resource ledgers owned by a kingdom
    based on territory base yields and built structures.
    """
    from app.models.tile import Building, Tile

    tiles = (
        await session.execute(
            select(Tile).where(Tile.owner_kingdom_id == kingdom_id)
        )
    ).scalars().all()

    rates: dict[str, float] = dict(BASE_KINGDOM_PRODUCTION)

    if tiles:
        tile_ids = [t.id for t in tiles]
        for t in tiles:
            if t.base_yield:
                for res, yield_amt in t.base_yield.items():
                    rates[res] = rates.get(res, 0.0) + float(yield_amt)

        buildings = (
            await session.execute(
                select(Building).where(Building.tile_id.in_(tile_ids))
            )
        ).scalars().all()

        for b in buildings:
            bonuses = BUILDING_YIELD_BONUSES.get(b.building_type, {})
            for res, bonus_amt in bonuses.items():
                rates[res] = rates.get(res, 0.0) + float(bonus_amt) * float(b.level)

    resources = (
        await session.execute(
            select(KingdomResource)
            .where(KingdomResource.kingdom_id == kingdom_id)
            .with_for_update()
        )
    ).scalars().all()

    resource_map = {r.resource_type: r for r in resources}
    now = _now()

    for res_type, new_rate in rates.items():
        if res_type in resource_map:
            res_row = resource_map[res_type]
            _materialize(res_row, now)
            res_row.rate_per_hour = new_rate
        else:
            session.add(
                KingdomResource(
                    kingdom_id=kingdom_id,
                    resource_type=res_type,
                    amount=0.0,
                    rate_per_hour=new_rate,
                    last_collected_at=now,
                )
            )

    return rates