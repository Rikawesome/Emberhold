"""World map generation service for grid generation and tile seeding."""

import random
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kingdom import World
from app.models.tile import Tile

TERRAIN_WEIGHTS = {
    "plain": 0.60,
    "wellspring": 0.15,
    "grove": 0.15,
    "ashfield": 0.10,
}

TERRAIN_BASE_YIELDS = {
    "wellspring": {"emberlight": 25},
    "grove": {"sustenance": 25},
    "ashfield": {"scrap": 20},
    "plain": {"emberlight": 5, "sustenance": 5, "scrap": 5},
}

RESONANCE_TYPES = ["emberdust", "everfrost", "farsight", "galewisp", "sparkstone"]


def generate_tile_yield(terrain_type: str, resonance_affinity: str | None = None) -> dict[str, int]:
    base = dict(TERRAIN_BASE_YIELDS.get(terrain_type, {}))
    if resonance_affinity:
        base[resonance_affinity] = base.get(resonance_affinity, 0) + 10
    return base


async def generate_world_map(
    session: AsyncSession,
    world_id: uuid.UUID,
    width: int = 50,
    height: int = 50,
) -> int:
    """Generate a grid of tiles for the given world.

    Returns the total number of created tiles.
    """
    terrains = list(TERRAIN_WEIGHTS.keys())
    weights = list(TERRAIN_WEIGHTS.values())

    tiles_to_add = []
    for x in range(width):
        for y in range(height):
            terrain = random.choices(terrains, weights=weights, k=1)[0]
            
            # ~15% chance of resonance affinity
            affinity = random.choice(RESONANCE_TYPES) if random.random() < 0.15 else None
            base_yield = generate_tile_yield(terrain, affinity)

            tile = Tile(
                world_id=world_id,
                x=x,
                y=y,
                terrain_type=terrain,
                resonance_affinity=affinity,
                base_yield=base_yield,
                owner_kingdom_id=None,
            )
            tiles_to_add.append(tile)

    session.add_all(tiles_to_add)
    await session.flush()
    return len(tiles_to_add)
