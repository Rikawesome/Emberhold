"""Tests for world map generation, capital placement spacing, and dynamic resource production recalculation."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.models.kingdom import KingdomResource, World
from app.models.tile import Building, Tile, BuildingQueue
from app.models.march import March
from app.services.world_generator import generate_world_map
from app.services.kingdoms import claim_capital_tile, create_starter_kingdom
from app.services.production import recalculate_production, collect_resource
from app.services.fade import compute_bloodline_income_and_upkeep
from app.services.combat import resolve_march
from app.jobs.complete_queues import process_queues
from tests.conftest import make_bloodline, make_kingdom, make_tile, make_world, make_player, make_troop_type, make_garrison, make_march


@pytest.mark.asyncio
async def test_generate_world_map(session):
    world = await make_world(session)
    count = await generate_world_map(session, world.id, width=10, height=10)
    assert count == 100

    tiles = (await session.execute(select(Tile).where(Tile.world_id == world.id))).scalars().all()
    assert len(tiles) == 100

    terrains = {t.terrain_type for t in tiles}
    assert "plain" in terrains

    wellspring_tiles = [t for t in tiles if t.terrain_type == "wellspring"]
    if wellspring_tiles:
        assert wellspring_tiles[0].base_yield.get("emberlight") == 25


@pytest.mark.asyncio
async def test_claim_capital_tile_spacing(session):
    world = await make_world(session)
    # Generate 10x10 map
    await generate_world_map(session, world.id, width=10, height=10)

    t1 = await claim_capital_tile(session, world.id)
    player1 = await make_player(session)
    bloodline = await make_bloodline(session)
    k1 = await make_kingdom(session, world.id, bloodline.id, player_id=player1.id)
    k1.capital_tile_id = t1.id
    t1.owner_kingdom_id = k1.id
    await session.commit()

    t2 = await claim_capital_tile(session, world.id)
    # Distance between capital 1 and capital 2 should be >= 1
    dist = abs(t1.x - t2.x) + abs(t1.y - t2.y)
    assert dist >= 1


@pytest.mark.asyncio
async def test_production_recalculation_on_capture_and_building(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    player = await make_player(session)
    kingdom = await make_kingdom(session, world.id, bloodline.id, player_id=player.id)

    # Initial production (base 10)
    initial_rates = await recalculate_production(session, kingdom.id)
    assert initial_rates["emberlight"] == 10.0

    # Add a wellspring tile owned by kingdom
    ws_tile = Tile(
        world_id=world.id, x=2, y=2, terrain_type="wellspring",
        base_yield={"emberlight": 25}, owner_kingdom_id=kingdom.id,
    )
    session.add(ws_tile)
    await session.commit()

    # Recalculate production -> should be 10 + 25 = 35 emberlight
    updated_rates = await recalculate_production(session, kingdom.id)
    assert updated_rates["emberlight"] == 35.0

    # Add a building (wellspring_tap) on that tile
    session.add(Building(tile_id=ws_tile.id, building_type="wellspring_tap", level=1))
    await session.commit()

    built_rates = await recalculate_production(session, kingdom.id)
    assert built_rates["emberlight"] == 50.0  # 10 base + 25 tile + 15 tap


@pytest.mark.asyncio
async def test_fade_income_reflects_dynamic_production(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    player = await make_player(session)
    kingdom = await make_kingdom(session, world.id, bloodline.id, player_id=player.id)

    # Add wellspring tile to kingdom
    ws_tile = Tile(
        world_id=world.id, x=3, y=3, terrain_type="wellspring",
        base_yield={"emberlight": 50}, owner_kingdom_id=kingdom.id,
    )
    session.add(ws_tile)
    await session.commit()

    await recalculate_production(session, kingdom.id)
    await session.commit()

    income, upkeep = await compute_bloodline_income_and_upkeep(session, world.id, bloodline.id)
    # Income should be higher than default due to territory ownership (10 base + 50 tile = 60)
    assert income >= 60.0

