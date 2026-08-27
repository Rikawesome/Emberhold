"""March creation and travel-time calculation."""

import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kingdom import Kingdom
from app.models.tile import Tile

BASE_SPEED_TILES_PER_HOUR = 4.0  # tune during playtesting
FLASH_MARCH_TRAVEL_TIME = timedelta(seconds=1)  # effectively instant


def calculate_travel_time(origin: Tile, target: Tile, speed_modifier: float = 1.0, has_flash_march: bool = False) -> timedelta:
    """has_flash_march: pass True when the march's troop_stack includes a Stormrunner
    (ability_key == 'flash_march') — the router looks this up before calling in,
    since this function stays DB-free otherwise.

    Scope note: the design doc describes Flash March as usable "once per cooldown."
    This implementation applies it every time it's present in the stack — cooldown
    tracking needs a new column (e.g. Kingdom.flash_march_available_at) and is left
    as a follow-up rather than bolted on here.
    """
    if has_flash_march:
        return FLASH_MARCH_TRAVEL_TIME
    distance = math.dist((origin.x, origin.y), (target.x, target.y))
    hours = distance / (BASE_SPEED_TILES_PER_HOUR * speed_modifier)
    return timedelta(hours=hours)


async def check_kindling_shield(target_tile: Tile, session: AsyncSession) -> bool:
    """Returns True if the target is currently protected and cannot be attacked."""
    if target_tile.owner_kingdom_id is None:
        return False
    kingdom = await session.get(Kingdom, target_tile.owner_kingdom_id)
    if kingdom is None:
        return False
    return kingdom.kindling_shield_expires_at > datetime.now(timezone.utc)


def new_march_id() -> uuid.UUID:
    return uuid.uuid4()
