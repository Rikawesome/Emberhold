"""Combat casualty math consistency tests for Breach, Scorch, Fortification, and Aegis Core abilities."""

import pytest
from sqlalchemy import select

from app.models.tile import Building, Tile, TileGarrison
from app.services.combat import resolve_march
from tests.conftest import (
    make_bloodline, make_garrison, make_kingdom, make_march, make_tile,
    make_troop_type, make_world,
)


@pytest.mark.asyncio
async def test_breach_attacker_retains_survivors_on_win(session):
    """Repro test for Item #5:
    10 Breach Siege Engineers (base attack=1, Breach 1.5x against buildings = 15 offense)
    attacking a tile with a building and 12 defense. Attacker wins (15 > 12).
    Casualty calculation must use attacker_offense (15) so the stack is NOT wiped out.
    """
    world = await make_world(session)
    kindled = await make_bloodline(session, "kindled")
    deepwell = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, kindled.id)
    defender = await make_kingdom(session, world.id, deepwell.id)

    breach_troop = await make_troop_type(session, key="siege_engineer")
    breach_troop.ability_key = "breach"
    breach_troop.stats = {"attack": 1, "defense": 1}

    def_troop = await make_troop_type(session, key="defender_guard")
    def_troop.stats = {"attack": 1, "defense": 1}
    session.add(breach_troop)
    session.add(def_troop)

    origin = await make_tile(session, world.id, x=0, y=0, owner_kingdom_id=attacker.id)
    target = await make_tile(session, world.id, x=1, y=0, owner_kingdom_id=defender.id)
    
    # Add a building to target tile so Breach triggers
    session.add(Building(tile_id=target.id, building_type="barracks", level=1))
    await make_garrison(session, target.id, defender.id, def_troop.id, quantity=12)

    march = await make_march(session, world.id, attacker.id, origin.id, target.id, quantity=10, troop_type_id=breach_troop.id)
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["outcome"] == "captured"
    assert log.result["attacker_power"] == 15.0  # 10 * 1.5 Breach multiplier
    assert log.result["defender_power"] == 12.0

    # Attacker survived!
    garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == target.id,
            TileGarrison.kingdom_id == attacker.id,
            TileGarrison.troop_type_id == breach_troop.id,
        )
    )
    assert garrison is not None
    assert garrison.quantity > 0
