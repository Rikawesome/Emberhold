"""Tests for Item #8 (public kingdom privacy) and Item #9 (circle war declaration permissions & duplicate join handling)."""

import pytest
from fastapi import HTTPException
from app.routers.kingdoms import get_kingdom_public
from app.routers.circles import declare_war, join_circle
from app.schemas.circle import DeclareWarRequest
from app.models.circle import Circle, CircleMember
from app.models.kingdom import KingdomResource
from tests.conftest import (
    make_bloodline, make_kingdom, make_player, make_world,
)


@pytest.mark.asyncio
async def test_public_kingdom_view_strips_rival_resources(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    player1 = await make_player(session)
    player2 = await make_player(session)

    k1 = await make_kingdom(session, world.id, bloodline.id, player_id=player1.id)
    session.add(KingdomResource(kingdom_id=k1.id, resource_type="emberlight", amount=500, rate_per_hour=10))
    await session.commit()

    # Owner views kingdom -> gets resource values
    owner_view = await get_kingdom_public(kingdom_id=k1.id, player_id=player1.id, session=session)
    assert owner_view.resources.get("emberlight") == pytest.approx(500.0, abs=0.1)


    # Rival views kingdom -> gets stripped resource dict ({})
    rival_view = await get_kingdom_public(kingdom_id=k1.id, player_id=player2.id, session=session)
    assert rival_view.resources == {}


@pytest.mark.asyncio
async def test_declare_war_requires_circle_membership(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    player1 = await make_player(session)
    player2 = await make_player(session)

    k1 = await make_kingdom(session, world.id, bloodline.id, player_id=player1.id)
    k2 = await make_kingdom(session, world.id, bloodline.id, player_id=player2.id)

    circle1 = Circle(world_id=world.id, bloodline_id=bloodline.id, name="Circle One", created_by_kingdom_id=k1.id)
    circle2 = Circle(world_id=world.id, bloodline_id=bloodline.id, name="Circle Two", created_by_kingdom_id=k2.id)
    session.add(circle1)
    session.add(circle2)
    await session.flush()

    # k1 is leader of circle1
    session.add(CircleMember(circle_id=circle1.id, kingdom_id=k1.id, role="leader"))
    await session.commit()

    payload = DeclareWarRequest(defender_circle_id=circle2.id)

    # Player 2 (member of k2, NOT circle1) tries to declare war for circle1 -> 403
    with pytest.raises(HTTPException) as exc_info:
        await declare_war(circle_id=circle1.id, payload=payload, player_id=player2.id, session=session)

    assert exc_info.value.status_code == 403
    assert "not a member" in exc_info.value.detail

    # Player 1 (member of circle1) declares war -> 201 success
    war_res = await declare_war(circle_id=circle1.id, payload=payload, player_id=player1.id, session=session)
    assert "war_id" in war_res


@pytest.mark.asyncio
async def test_join_circle_duplicate_returns_409(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    player = await make_player(session)
    k = await make_kingdom(session, world.id, bloodline.id, player_id=player.id)

    circle = Circle(world_id=world.id, bloodline_id=bloodline.id, name="Test Circle", created_by_kingdom_id=k.id)
    session.add(circle)
    await session.flush()
    session.add(CircleMember(circle_id=circle.id, kingdom_id=k.id, role="leader"))
    await session.commit()

    # Try to re-join circle already in -> 409 Conflict
    with pytest.raises(HTTPException) as exc_info:
        await join_circle(circle_id=circle.id, player_id=player.id, session=session)

    assert exc_info.value.status_code == 409
