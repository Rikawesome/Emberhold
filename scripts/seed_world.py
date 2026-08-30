"""Seed default world and generate tile grid:

    python -m scripts.seed_world

Generates active world map grid with weighted terrain types, base yields, and resonance affinities.
"""

import asyncio
from sqlalchemy import select

from app.core.db import async_session
from app.models.kingdom import World
from app.models.tile import Tile
from app.services.world_generator import generate_world_map


async def seed_world(width: int = 50, height: int = 50) -> None:
    async with async_session() as session:
        world = await session.scalar(select(World).where(World.status == "active"))
        if not world:
            world = World(name="Emberfall — World 1", status="active")
            session.add(world)
            await session.flush()

        existing_tiles = await session.scalar(select(Tile).where(Tile.world_id == world.id))
        if existing_tiles:
            print(f"World '{world.name}' already has tiles — skipping map generation.")
            return

        count = await generate_world_map(session, world.id, width=width, height=height)
        await session.commit()
        print(f"Successfully generated map with {count} tiles ({width}x{height}) for world '{world.name}'.")


if __name__ == "__main__":
    asyncio.run(seed_world())
