"""Tests for auth refresh token, flash march cooldown, and bloodline self-mitigation tech endpoints."""

import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from app.routers.auth import refresh_token
from app.routers.kingdoms import get_kingdom_tech
from app.routers.marches import create_march
from app.schemas.march import MarchRequest, TroopStackEntry
from tests.conftest import make_bloodline, make_kingdom, make_player, make_tile, make_troop_type, make_world


@pytest.mark.asyncio
async def test_auth_refresh_token():
    import uuid
    player_id = uuid.uuid4()
    res = await refresh_token(player_id=player_id)
    assert res.access_token is not None
    assert len(res.access_token) > 20


@pytest.mark.asyncio
async def test_flash_march_cooldown_enforced(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    player = await make_player(session)
    k1 = await make_kingdom(session, world.id, bloodline.id, player_id=player.id)
    k2 = await make_kingdom(session, world.id, bloodline.id)

    stormrunner = await make_troop_type(session, key="stormrunner")
    stormrunner.ability_key = "flash_march"
    session.add(stormrunner)

    t1 = await make_tile(session, world.id, x=0, y=0, owner_kingdom_id=k1.id)
    t2 = await make_tile(session, world.id, x=2, y=0, owner_kingdom_id=k2.id)
    t3 = await make_tile(session, world.id, x=3, y=0, owner_kingdom_id=k2.id)

    from tests.conftest import make_garrison
    await make_garrison(session, t1.id, k1.id, stormrunner.id, quantity=20)
    await session.commit()

    payload1 = MarchRequest(
        origin_tile_id=t1.id, target_tile_id=t2.id,
        troop_stack=[TroopStackEntry(troop_type_id=stormrunner.id, quantity=5)],
        march_type="attack",
    )
    # First flash march succeeds
    m1 = await create_march(kingdom_id=k1.id, payload=payload1, player_id=player.id, session=session)
    assert m1.march_id is not None

    # Immediate second flash march within cooldown window fails with HTTP 400
    payload2 = MarchRequest(
        origin_tile_id=t1.id, target_tile_id=t3.id,
        troop_stack=[TroopStackEntry(troop_type_id=stormrunner.id, quantity=5)],
        march_type="attack",
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_march(kingdom_id=k1.id, payload=payload2, player_id=player.id, session=session)

    assert exc_info.value.status_code == 400
    assert "on cooldown" in exc_info.value.detail


@pytest.mark.asyncio
async def test_bloodline_tech_endpoint(session):
    world = await make_world(session)
    kindled = await make_bloodline(session, "kindled")
    player = await make_player(session)
    kingdom = await make_kingdom(session, world.id, kindled.id, player_id=player.id)
    await session.commit()

    tech_res = await get_kingdom_tech(kingdom_id=kingdom.id, player_id=player.id, session=session)
    assert tech_res["bloodline"] == "kindled"
    assert tech_res["self_mitigation"]["key"] == "ashwall_forges"
