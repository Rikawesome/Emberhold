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