"""March creation and travel-time calculation.

Travel time is bloodline-sensitive (Driftborn faster, Flash March ignores it once per
cooldown) — that modifier lookup is a TODO here; the base distance calculation is real.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tile import Tile

BASE_SPEED_TILES_PER_HOUR = 4.0  # tune during playtesting


def calculate_travel_time(origin: Tile, target: Tile, speed_modifier: float = 1.0) -> timedelta:
    distance = math.dist((origin.x, origin.y), (target.x, target.y))
    hours = distance / (BASE_SPEED_TILES_PER_HOUR * speed_modifier)
    return timedelta(hours=hours)


async def check_kindling_shield(target_tile: Tile, session: AsyncSession) -> bool:
    """Returns True if the target is currently protected and cannot be attacked.
    TODO: join to the owning Kingdom's kindling_shield_expires_at and compare to now.
    """
    if target_tile.owner_kingdom_id is None:
        return False
    # placeholder — wire up the real kingdom lookup once this is called from the router
    return False


def new_march_id() -> uuid.UUID:
    return uuid.uuid4()
