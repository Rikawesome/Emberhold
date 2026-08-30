"""Comprehensive End-to-End Game Lifecycle Test Suite (Item #17).

Tests the complete multi-player game loop:
1. Registration & Starter Kingdom / Capital Spacing
2. Resource Production & Ledger Collection
3. Building Queue Construction & Production Recalculation
4. Troop Queue Training & Garrison Insertion
5. March Deployment & Combat Tile Capture
6. Reinforcement March Troop Merging
7. Fade Dynamics & Bloodline Status Recomputation
8. Auth Refresh & Rival Privacy Enforcements
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.models.kingdom import Kingdom, KingdomResource
from app.models.tile import Tile, TileGarrison, Building, BuildingQueue
from app.models.troop import TroopType, TrainingQueue
from app.models.march import March, CombatLog
from app.models.player import Player, Bloodline
from app.services.world_generator import generate_world_map
from app.services.kingdoms import claim_capital_tile
from app.services.production import recalculate_production, collect_all
from app.services.combat import resolve_march
from app.services.fade import compute_bloodline_income_and_upkeep
from app.jobs.complete_queues import complete_building_queues, complete_troop_queues
from app.routers.kingdoms import get_kingdom_public
from app.routers.auth import refresh_token
from tests.conftest import make_bloodline, make_player, make_world, make_troop_type


@pytest.mark.asyncio
async def test_full_game_lifecycle_e2e(session):
    # -------------------------------------------------------------------------
    # 1. World Generation & Multi-Player Starter Setup
    # -------------------------------------------------------------------------
    world = await make_world(session)
    await generate_world_map(session, world.id, width=10, height=10)

    kindled = await make_bloodline(session, "kindled")
    deepwell = await make_bloodline(session, "deepwell")

    p1 = await make_player(session, username="kindled_lord")
    p2 = await make_player(session, username="deepwell_king")

    # Create Kingdom 1
    k1 = Kingdom(
        player_id=p1.id,
        world_id=world.id,
        bloodline_id=kindled.id,
        name="Kindled Hold",
        kindling_shield_expires_at=datetime.now(timezone.utc),
    )
    session.add(k1)
    await session.flush()
    cap1 = await claim_capital_tile(session, world.id)
    cap1.owner_kingdom_id = k1.id
    await session.flush()
    await recalculate_production(session, k1.id)

    # Create Kingdom 2
    k2 = Kingdom(
        player_id=p2.id,
        world_id=world.id,
        bloodline_id=deepwell.id,
        name="Deepwell Fortress",
        kindling_shield_expires_at=datetime.now(timezone.utc),
    )
    session.add(k2)
    await session.flush()
    cap2 = await claim_capital_tile(session, world.id)
    cap2.owner_kingdom_id = k2.id
    await session.flush()
    await recalculate_production(session, k2.id)

    await session.commit()

    # Capital spacing check (Manhattan distance >= min spacing)
    dist = abs(cap1.x - cap2.x) + abs(cap1.y - cap2.y)
    assert dist >= 2
    assert cap1.owner_kingdom_id == k1.id
    assert cap2.owner_kingdom_id == k2.id

    # -------------------------------------------------------------------------
    # 2. Resource Accumulation & Collection
    # -------------------------------------------------------------------------
    resources1 = await collect_all(session, k1.id)
    assert "emberlight" in resources1
    assert resources1["emberlight"] >= 0

    # -------------------------------------------------------------------------
    # 3. Building Construction & Queue Completion
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)
    bq = BuildingQueue(
        tile_id=cap1.id,
        building_type="wellspring_tap",
        started_at=now - timedelta(minutes=10),
        completes_at=now - timedelta(seconds=1),
    )
    session.add(bq)
    await session.commit()

    # Run the queue processor (no return value)
    await complete_building_queues(session)
    await session.flush()

    b = await session.scalar(select(Building).where(Building.tile_id == cap1.id, Building.building_type == "wellspring_tap"))
    assert b is not None
    assert b.level == 1

    # -------------------------------------------------------------------------
    # 4. Troop Training & Queue Completion
    # -------------------------------------------------------------------------
    warrior_type = await make_troop_type(session, key="kindled_warrior_e2e")
    warrior_type.stats = {"attack": 5, "defense": 2}
    session.add(warrior_type)
    await session.commit()

    tq = TrainingQueue(
        kingdom_id=k1.id,
        tile_id=cap1.id,
        troop_type_id=warrior_type.id,
        quantity=15,
        started_at=now - timedelta(minutes=10),
        completes_at=now - timedelta(seconds=1),
    )
    session.add(tq)
    await session.commit()

    await complete_troop_queues(session)
    await session.flush()

    cap1_garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == cap1.id,
            TileGarrison.troop_type_id == warrior_type.id,
        )
    )
    assert cap1_garrison is not None
    assert cap1_garrison.quantity == 15

    # -------------------------------------------------------------------------
    # 5. March Deployment & Combat Resolution
    # -------------------------------------------------------------------------
    # Place small defending garrison at target tile
    target_tile = await session.scalar(
        select(Tile).where(
            Tile.world_id == world.id,
            Tile.id != cap1.id,
            Tile.id != cap2.id,
        )
    )
    target_tile.owner_kingdom_id = k2.id
    await session.flush()

    def_troop = await make_troop_type(session, key="deepwell_guard_e2e")
    def_troop.stats = {"attack": 1, "defense": 1}
    session.add(def_troop)
    session.add(TileGarrison(tile_id=target_tile.id, kingdom_id=k2.id, troop_type_id=def_troop.id, quantity=4))
    await session.commit()

    # Deduct troops from cap1 garrison to dispatch march
    cap1_garrison.quantity -= 10
    march = March(
        world_id=world.id,
        kingdom_id=k1.id,
        origin_tile_id=cap1.id,
        target_tile_id=target_tile.id,
        troop_stack=[{"troop_type_id": str(warrior_type.id), "quantity": 10}],
        march_type="attack",
        departure_at=now,
        arrival_at=now,
        status="marching",
    )
    session.add(march)
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log is not None
    assert log.result["outcome"] == "captured"

    # Verify tile flipped to k1
    refreshed_target = await session.get(Tile, target_tile.id)
    assert refreshed_target.owner_kingdom_id == k1.id

    # -------------------------------------------------------------------------
    # 6. Reinforcement March (Non-Combat Garrison Merge)
    # -------------------------------------------------------------------------
    reinforce_march = March(
        world_id=world.id,
        kingdom_id=k1.id,
        origin_tile_id=cap1.id,
        target_tile_id=target_tile.id,
        troop_stack=[{"troop_type_id": str(warrior_type.id), "quantity": 5}],
        march_type="reinforce",
        departure_at=now,
        arrival_at=now,
        status="marching",
    )
    session.add(reinforce_march)
    await session.commit()

    await resolve_march(session, reinforce_march.id)
    await session.commit()

    target_garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == target_tile.id,
            TileGarrison.kingdom_id == k1.id,
            TileGarrison.troop_type_id == warrior_type.id,
        )
    )
    assert target_garrison is not None
    assert target_garrison.quantity > 5

    # -------------------------------------------------------------------------
    # 7. Fade Status Recomputation
    # -------------------------------------------------------------------------
    income, upkeep = await compute_bloodline_income_and_upkeep(session, world.id, kindled.id)
    assert income >= 0
    assert upkeep >= 0

    # -------------------------------------------------------------------------
    # 8. Auth Refresh & Privacy Enforcements
    # -------------------------------------------------------------------------
    auth_res = await refresh_token(player_id=p1.id)
    assert auth_res.access_token is not None

    # Owner gets full resource view
    owner_view = await get_kingdom_public(kingdom_id=k1.id, player_id=p1.id, session=session)
    assert owner_view.resources != {}

    # Rival gets stripped resource view ({})
    rival_view = await get_kingdom_public(kingdom_id=k1.id, player_id=p2.id, session=session)
    assert rival_view.resources == {}
