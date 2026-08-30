"""Tests for march types (reinforce, return, attack validation) and Bulwark survivor retreat logic."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.models.tile import Tile, TileGarrison
from app.models.march import March
from app.services.combat import resolve_march
from app.routers.marches import create_march
from app.schemas.march import MarchRequest, TroopStackEntry
from tests.conftest import (
    make_bloodline, make_garrison, make_kingdom, make_march, make_tile,
    make_troop_type, make_world, make_player,
)


@pytest.mark.asyncio
async def test_cannot_attack_own_territory(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    player = await make_player(session)
    kingdom = await make_kingdom(session, world.id, bloodline.id, player_id=player.id)
    troop_type = await make_troop_type(session)

    t1 = await make_tile(session, world.id, x=0, y=0, owner_kingdom_id=kingdom.id)
    t2 = await make_tile(session, world.id, x=1, y=0, owner_kingdom_id=kingdom.id)
    await make_garrison(session, t1.id, kingdom.id, troop_type.id, quantity=10)
    await session.commit()

    from fastapi import HTTPException
    payload = MarchRequest(
        origin_tile_id=t1.id,
        target_tile_id=t2.id,
        troop_stack=[TroopStackEntry(troop_type_id=troop_type.id, quantity=5)],
        march_type="attack",
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_march(kingdom_id=kingdom.id, payload=payload, player_id=player.id, session=session)

    assert exc_info.value.status_code == 400
    assert "Cannot attack your own territory" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reinforce_march_merges_troops_without_combat(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    player = await make_player(session)
    kingdom = await make_kingdom(session, world.id, bloodline.id, player_id=player.id)
    troop_type = await make_troop_type(session)

    t1 = await make_tile(session, world.id, x=0, y=0, owner_kingdom_id=kingdom.id)
    t2 = await make_tile(session, world.id, x=1, y=0, owner_kingdom_id=kingdom.id)

    # Place existing garrison of 20 troops at target tile
    await make_garrison(session, t2.id, kingdom.id, troop_type.id, quantity=20)

    now = datetime.now(timezone.utc)
    march = March(
        world_id=world.id,
        kingdom_id=kingdom.id,
        origin_tile_id=t1.id,
        target_tile_id=t2.id,
        troop_stack=[{"troop_type_id": str(troop_type.id), "quantity": 10}],
        march_type="reinforce",
        departure_at=now,
        arrival_at=now,
        status="marching",
    )
    session.add(march)
    await session.commit()

    # Resolve reinforce march
    await resolve_march(session, march.id)
    await session.commit()

    # Target garrison should be 20 + 10 = 30 without combat casualties
    garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == t2.id,
            TileGarrison.kingdom_id == kingdom.id,
            TileGarrison.troop_type_id == troop_type.id,
        )
    )
    assert garrison is not None
    assert garrison.quantity == 30


@pytest.mark.asyncio
async def test_bulwark_survivors_retreat_to_defender_capital(session):
    world = await make_world(session)
    kindled = await make_bloodline(session, "kindled")
    glacial = await make_bloodline(session, "glacial")
    attacker = await make_kingdom(session, world.id, kindled.id)
    defender = await make_kingdom(session, world.id, glacial.id)

    def_capital = await make_tile(session, world.id, x=0, y=0, owner_kingdom_id=defender.id)
    defender.capital_tile_id = def_capital.id

    attacker_origin = await make_tile(session, world.id, x=5, y=5, owner_kingdom_id=attacker.id)
    target = await make_tile(session, world.id, x=1, y=0, owner_kingdom_id=defender.id)

    attacker_troop = await make_troop_type(session, key="kindled_warrior")
    attacker_troop.stats = {"attack": 10, "defense": 5}

    bulwark_troop = await make_troop_type(session, key="glacial_warden")
    bulwark_troop.ability_key = "bulwark"
    bulwark_troop.stats = {"attack": 1, "defense": 1}
    session.add(attacker_troop)
    session.add(bulwark_troop)

    # 10 Bulwark defenders on target tile
    await make_garrison(session, target.id, defender.id, bulwark_troop.id, quantity=10)

    # Attacker sends overwhelming force (20 * 10 = 200 offense vs 10 defense)
    march = await make_march(session, world.id, attacker.id, attacker_origin.id, target.id, quantity=20, troop_type_id=attacker_troop.id)
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["outcome"] == "captured"

    # Target tile is now owned by attacker
    refreshed_target = await session.get(Tile, target.id)
    assert refreshed_target.owner_kingdom_id == attacker.id

    # Defender Bulwark survivors (50% of 10 = 5 troops) retreated to defender's capital tile!
    capital_garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == def_capital.id,
            TileGarrison.kingdom_id == defender.id,
            TileGarrison.troop_type_id == bulwark_troop.id,
        )
    )
    assert capital_garrison is not None
    assert capital_garrison.quantity == 5
