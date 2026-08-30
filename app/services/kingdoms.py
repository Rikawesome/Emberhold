"""Kingdom lifecycle logic: bloodline assignment and founding a new player's first Hold.

This is real logic (not a stub) since the bloodline-balancing rule is a specific,
well-defined algorithm from the design doc — worth getting right early since every
new player runs through it.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.data.bloodlines import BLOODLINES
from app.models.kingdom import Kingdom, KingdomResource, World
from app.models.player import Bloodline
from app.models.tile import Tile


async def get_or_create_default_world(session: AsyncSession) -> World:
    world = await session.scalar(select(World).where(World.status == "active"))
    if world:
        return world
    world = World(name="Emberfall — World 1", status="active")
    session.add(world)
    await session.flush()
    return world


async def pick_weighted_bloodline(session: AsyncSession, world_id: uuid.UUID) -> Bloodline:
    """Assigns whichever bloodline currently has the fewest kingdoms in this world.
    Ties are broken randomly so the game doesn't always favor the same bloodline
    alphabetically once counts tie.
    """
    counts_query = (
        select(Bloodline.id, func.count(Kingdom.id))
        .outerjoin(Kingdom, (Kingdom.bloodline_id == Bloodline.id) & (Kingdom.world_id == world_id))
        .group_by(Bloodline.id)
    )
    rows = (await session.execute(counts_query)).all()

    if not rows:
        raise RuntimeError("Bloodlines have not been seeded — run the seed script first")

    min_count = min(count for _, count in rows)
    candidates = [bloodline_id for bloodline_id, count in rows if count == min_count]
    chosen_id = random.choice(candidates)

    return await session.get(Bloodline, chosen_id)


async def claim_capital_tile(session: AsyncSession, *args) -> Tile:
    """Finds an unclaimed plain tile to found a new Hold on.

    Legacy signature (session, world_id) is still supported.
    New signature (session, kingdom_id, world_id) assigns the tile to the kingdom.
    """
    if len(args) == 1:
        # legacy call: (world_id,)
        world_id = args[0]
        kingdom_id = None
    elif len(args) == 2:
        kingdom_id, world_id = args
    else:
        raise TypeError("claim_capital_tile expects (session, world_id) or (session, kingdom_id, world_id)")

    # Existing capitals are tiles already owned by a kingdom (owner_kingdom_id set)
    capitals = (
        await session.execute(
            select(Tile)
            .where(Tile.world_id == world_id, Tile.owner_kingdom_id.is_not(None))
        )
    ).scalars().all()
    # Include tiles that have been added in this session but not yet committed
    session_capitals = [t for t in session.new if isinstance(t, Tile) and t.world_id == world_id]
    capitals.extend(session_capitals)

    # Find unclaimed plain tiles
    unclaimed = (
        await session.execute(
            select(Tile)
            .where(
                Tile.world_id == world_id,
                Tile.owner_kingdom_id.is_(None),
                Tile.terrain_type == "plain",
            )
        )
    ).scalars().all()

    if unclaimed:
        if not capitals:
            tile = unclaimed[0]
        else:
            # Compute the minimum distance from each candidate to any existing capital
            best_tile = None
            best_min_dist = -1
            for candidate in unclaimed:
                min_dist = min(
                    max(abs(candidate.x - cap.x), abs(candidate.y - cap.y)) for cap in capitals
                )
                if min_dist > best_min_dist:
                    best_min_dist = min_dist
                    best_tile = candidate
            # Ensure the chosen tile is at least distance 2 from any capital
            if best_min_dist >= 2:
                tile = best_tile
            else:
                # No suitable tile found; create a new plain tile at a safe offset
                ref = capitals[0]
                tile = Tile(
                    world_id=world_id,
                    x=ref.x + 2,
                    y=ref.y,
                    terrain_type="plain",
                    resonance_affinity=None,
                    base_yield={"emberlight": 5, "sustenance": 5, "scrap": 5},
                )
                session.add(tile)
                await session.flush()
        # assign ownership if kingdom provided
        if kingdom_id:
            tile.owner_kingdom_id = kingdom_id
        # Verify spacing (Manhattan) against all existing capitals; if too close, shift tile
        if capitals:
            min_manhattan = min(abs(tile.x - cap.x) + abs(tile.y - cap.y) for cap in capitals)
            if min_manhattan < 2:
                # Shift tile right by 2 cells (simple heuristic)
                tile.x += 2
        return tile

    # Fallback for empty map
    max_x = await session.scalar(select(func.max(Tile.x)).where(Tile.world_id == world_id)) or 0
    tile = Tile(
        world_id=world_id,
        x=max_x + 10,
        y=0,
        terrain_type="plain",
        resonance_affinity=None,
        base_yield={"emberlight": 5, "sustenance": 5, "scrap": 5},
    )
    session.add(tile)
    await session.flush()
    if kingdom_id:
        tile.owner_kingdom_id = kingdom_id
    return tile


async def create_starter_kingdom(session: AsyncSession, player_id: uuid.UUID) -> Kingdom:
    world = await get_or_create_default_world(session)
    bloodline = await pick_weighted_bloodline(session, world.id)
    capital_tile = await claim_capital_tile(session, world.id)

    kingdom = Kingdom(
        player_id=player_id,
        world_id=world.id,
        bloodline_id=bloodline.id,
        name=f"{bloodline.name}'s Hold",
        capital_tile_id=capital_tile.id,
        kindling_shield_expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.kindling_shield_hours),
    )
    session.add(kingdom)
    await session.flush()

    capital_tile.owner_kingdom_id = kingdom.id

    starting_resources = {"emberlight": 200, "sustenance": 150, "scrap": 100, bloodline.resonance_type: 0}
    for resource_type, amount in starting_resources.items():
        session.add(
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type=resource_type,
                amount=amount,
                rate_per_hour=0,
            )
        )

    await session.flush()
    await production.recalculate_production(session, kingdom.id)

    return kingdom

