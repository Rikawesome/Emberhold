"""Baseline combat lifecycle tests.

Abilities are intentionally out of scope here.  These tests pin down deterministic
casualties, survivor persistence, capture semantics, fortification, idempotency,
rollback, and target locking before abilities are added.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.march import CombatLog
from app.models.tile import Building, Tile, TileGarrison
from app.services.combat import resolve_march
from tests.conftest import (
    make_bloodline,
    make_garrison,
    make_kingdom,
    make_march,
    make_tile,
    make_troop_type,
    make_world,
)


async def _deduct_origin(session, origin_id, kingdom_id, troop_type_id, quantity):
    garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == origin_id,
            TileGarrison.kingdom_id == kingdom_id,
            TileGarrison.troop_type_id == troop_type_id,
        )
    )
    assert garrison is not None
    assert garrison.quantity >= quantity
    garrison.quantity -= quantity


@pytest.mark.asyncio
async def test_attacker_victory_has_deterministic_casualties_and_survivors(session):
    world = await make_world(session)
    attacker_bl = await make_bloodline(session, "kindled")
    defender_bl = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bl.id)
    defender = await make_kingdom(session, world.id, defender_bl.id)
    troop = await make_troop_type(session)
    origin = await make_tile(session, world.id, 0, 0, attacker.id)
    target = await make_tile(session, world.id, 1, 0, defender.id)
    await make_garrison(session, origin.id, attacker.id, troop.id, 10)
    await make_garrison(session, target.id, defender.id, troop.id, 4)
    await _deduct_origin(session, origin.id, attacker.id, troop.id, 10)

    march = await make_march(
        session, world.id, attacker.id, origin.id, target.id, 10, troop.id
    )
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["attacker_power"] == 10
    assert log.result["defender_power"] == 4
    assert log.result["attacker_casualties"] == 4
    assert log.result["defender_casualties"] == 4
    assert log.result["attacker_survivors"] == 6
    assert log.result["defender_survivors"] == 0

    origin_garrison = await session.scalar(
        select(TileGarrison).where(TileGarrison.tile_id == origin.id)
    )
    target_garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == target.id,
            TileGarrison.kingdom_id == attacker.id,
            TileGarrison.troop_type_id == troop.id,
        )
    )
    assert origin_garrison.quantity == 0
    assert target_garrison.quantity == 6


@pytest.mark.asyncio
async def test_defender_victory_preserves_ownership_and_defender_survivors(session):
    world = await make_world(session)
    attacker_bl = await make_bloodline(session, "kindled")
    defender_bl = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bl.id)
    defender = await make_kingdom(session, world.id, defender_bl.id)
    troop = await make_troop_type(session)
    origin = await make_tile(session, world.id, 0, 0, attacker.id)
    target = await make_tile(session, world.id, 1, 0, defender.id)
    await make_garrison(session, origin.id, attacker.id, troop.id, 5)
    await make_garrison(session, target.id, defender.id, troop.id, 20)
    await _deduct_origin(session, origin.id, attacker.id, troop.id, 5)

    march = await make_march(
        session, world.id, attacker.id, origin.id, target.id, 5, troop.id
    )
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["outcome"] == "repelled"
    assert log.result["attacker_casualties"] == 5
    assert log.result["defender_casualties"] == 5
    assert log.result["defender_survivors"] == 15

    refreshed_target = await session.get(Tile, target.id)
    assert refreshed_target.owner_kingdom_id == defender.id

    defender_garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == target.id,
            TileGarrison.kingdom_id == defender.id,
            TileGarrison.troop_type_id == troop.id,
        )
    )
    assert defender_garrison.quantity == 15


@pytest.mark.asyncio
async def test_zero_survivors_remove_garrison_rows(session):
    world = await make_world(session)
    attacker_bl = await make_bloodline(session, "kindled")
    defender_bl = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bl.id)
    defender = await make_kingdom(session, world.id, defender_bl.id)
    troop = await make_troop_type(session)
    origin = await make_tile(session, world.id, 0, 0, attacker.id)
    target = await make_tile(session, world.id, 1, 0, defender.id)
    await make_garrison(session, origin.id, attacker.id, troop.id, 10)
    await make_garrison(session, target.id, defender.id, troop.id, 10)
    await _deduct_origin(session, origin.id, attacker.id, troop.id, 10)

    march = await make_march(
        session, world.id, attacker.id, origin.id, target.id, 10, troop.id
    )
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["attacker_survivors"] == 0
    assert log.result["defender_survivors"] == 0
    rows = (
        await session.execute(
            select(TileGarrison).where(TileGarrison.tile_id == target.id)
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_attacker_survivors_after_capture_are_not_duplicated(session):
    world = await make_world(session)
    attacker_bl = await make_bloodline(session, "kindled")
    defender_bl = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bl.id)
    defender = await make_kingdom(session, world.id, defender_bl.id)
    troop = await make_troop_type(session)
    origin = await make_tile(session, world.id, 0, 0, attacker.id)
    target = await make_tile(session, world.id, 1, 0, defender.id)
    await make_garrison(session, origin.id, attacker.id, troop.id, 10)
    await make_garrison(session, target.id, defender.id, troop.id, 4)
    await _deduct_origin(session, origin.id, attacker.id, troop.id, 10)

    march = await make_march(
        session, world.id, attacker.id, origin.id, target.id, 10, troop.id
    )
    await session.commit()

    await resolve_march(session, march.id)
    await session.commit()

    attacker_rows = (
        await session.execute(
            select(TileGarrison).where(
                TileGarrison.tile_id == target.id,
                TileGarrison.kingdom_id == attacker.id,
                TileGarrison.troop_type_id == troop.id,
            )
        )
    ).scalars().all()

    assert len(attacker_rows) == 1
    assert attacker_rows[0].quantity == 6


@pytest.mark.asyncio
async def test_ownership_transfer_and_failed_attack_preserves_owner(session):
    world = await make_world(session)
    attacker_bl = await make_bloodline(session, "kindled")
    defender_bl = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bl.id)
    defender = await make_kingdom(session, world.id, defender_bl.id)
    troop = await make_troop_type(session)

    # Capture case.
    origin_a = await make_tile(session, world.id, 0, 0, attacker.id)
    target_a = await make_tile(session, world.id, 1, 0, defender.id)
    await make_garrison(session, origin_a.id, attacker.id, troop.id, 11)
    await make_garrison(session, target_a.id, defender.id, troop.id, 10)
    await _deduct_origin(session, origin_a.id, attacker.id, troop.id, 11)
    march_a = await make_march(
        session, world.id, attacker.id, origin_a.id, target_a.id, 11, troop.id
    )

    # Repel case.
    origin_b = await make_tile(session, world.id, 0, 1, attacker.id)
    target_b = await make_tile(session, world.id, 1, 1, defender.id)
    await make_garrison(session, origin_b.id, attacker.id, troop.id, 5)
    await make_garrison(session, target_b.id, defender.id, troop.id, 20)
    await _deduct_origin(session, origin_b.id, attacker.id, troop.id, 5)
    march_b = await make_march(
        session, world.id, attacker.id, origin_b.id, target_b.id, 5, troop.id
    )
    await session.commit()

    log_a = await resolve_march(session, march_a.id)
    log_b = await resolve_march(session, march_b.id)
    await session.commit()

    assert log_a.result["outcome"] == "captured"
    assert log_b.result["outcome"] == "repelled"
    assert (await session.get(Tile, target_a.id)).owner_kingdom_id == attacker.id
    assert (await session.get(Tile, target_b.id)).owner_kingdom_id == defender.id


@pytest.mark.asyncio
async def test_fortification_affects_combat_before_abilities(session):
    world = await make_world(session)
    attacker_bl = await make_bloodline(session, "kindled")
    defender_bl = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bl.id)
    defender = await make_kingdom(session, world.id, defender_bl.id)
    troop = await make_troop_type(session)
    origin = await make_tile(session, world.id, 0, 0, attacker.id)

    unfortified = await make_tile(session, world.id, 1, 0, defender.id)
    await make_garrison(session, unfortified.id, defender.id, troop.id, 10)
    await make_garrison(session, origin.id, attacker.id, troop.id, 11)
    await _deduct_origin(session, origin.id, attacker.id, troop.id, 11)
    march_one = await make_march(
        session, world.id, attacker.id, origin.id, unfortified.id, 11, troop.id
    )

    fortified = await make_tile(session, world.id, 1, 1, defender.id)
    await make_garrison(session, fortified.id, defender.id, troop.id, 10)
    session.add(Building(tile_id=fortified.id, building_type="fortification", level=1))
    await session.flush()
    # Use a fresh attacker stack for the second attack.
    origin_two = await make_tile(session, world.id, 0, 1, attacker.id)
    await make_garrison(session, origin_two.id, attacker.id, troop.id, 11)
    await _deduct_origin(session, origin_two.id, attacker.id, troop.id, 11)
    march_two = await make_march(
        session, world.id, attacker.id, origin_two.id, fortified.id, 11, troop.id
    )
    await session.commit()

    unfortified_log = await resolve_march(session, march_one.id)
    fortified_log = await resolve_march(session, march_two.id)
    await session.commit()

    assert unfortified_log.result["outcome"] == "captured"
    assert fortified_log.result["outcome"] == "repelled"
    assert fortified_log.result["fortification_bonus"] == 1
    assert fortified_log.result["defender_power_with_fortification"] == 11


@pytest.mark.asyncio
async def test_march_cannot_resolve_twice_or_duplicate_side_effects(session):
    world = await make_world(session)
    attacker_bl = await make_bloodline(session, "kindled")
    defender_bl = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bl.id)
    defender = await make_kingdom(session, world.id, defender_bl.id)
    troop = await make_troop_type(session)
    origin = await make_tile(session, world.id, 0, 0, attacker.id)
    target = await make_tile(session, world.id, 1, 0, defender.id)
    await make_garrison(session, origin.id, attacker.id, troop.id, 10)
    await make_garrison(session, target.id, defender.id, troop.id, 4)
    await _deduct_origin(session, origin.id, attacker.id, troop.id, 10)
    march = await make_march(
        session, world.id, attacker.id, origin.id, target.id, 10, troop.id
    )
    await session.commit()

    first = await resolve_march(session, march.id)
    await session.commit()
    second = await resolve_march(session, march.id)
    await session.commit()

    assert first.id == second.id
    assert second.result["attacker_survivors"] == 6

    logs = (
        await session.execute(
            select(CombatLog).where(CombatLog.march_id == march.id)
        )
    ).scalars().all()
    assert len(logs) == 1

    rows = (
        await session.execute(
            select(TileGarrison).where(
                TileGarrison.tile_id == target.id,
                TileGarrison.kingdom_id == attacker.id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].quantity == 6


@pytest.mark.asyncio
async def test_transaction_rollback_reverts_entire_resolution(engine):
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with factory() as setup:
        world = await make_world(setup)
        attacker_bl = await make_bloodline(setup, "kindled")
        defender_bl = await make_bloodline(setup, "deepwell")
        attacker = await make_kingdom(setup, world.id, attacker_bl.id)
        defender = await make_kingdom(setup, world.id, defender_bl.id)
        troop = await make_troop_type(setup)
        origin = await make_tile(setup, world.id, 0, 0, attacker.id)
        target = await make_tile(setup, world.id, 1, 0, defender.id)
        await make_garrison(setup, origin.id, attacker.id, troop.id, 10)
        await make_garrison(setup, target.id, defender.id, troop.id, 4)
        await _deduct_origin(setup, origin.id, attacker.id, troop.id, 10)
        march = await make_march(
            setup, world.id, attacker.id, origin.id, target.id, 10, troop.id
        )
        await setup.commit()

    async with factory() as tx:
        await resolve_march(tx, march.id)
        await tx.rollback()

    async with factory() as check:
        refreshed_march = await check.get(type(march), march.id)
        refreshed_target = await check.get(Tile, target.id)
        origin_garrison = await check.scalar(
            select(TileGarrison).where(TileGarrison.tile_id == origin.id)
        )
        target_garrison = await check.scalar(
            select(TileGarrison).where(
                TileGarrison.tile_id == target.id,
                TileGarrison.kingdom_id == defender.id,
            )
        )
        logs = (
            await check.execute(
                select(CombatLog).where(CombatLog.march_id == march.id)
            )
        ).scalars().all()

        assert refreshed_march.status == "marching"
        assert refreshed_target.owner_kingdom_id == defender.id
        assert origin_garrison.quantity == 0
        assert target_garrison.quantity == 4
        assert logs == []


@pytest.mark.asyncio
async def test_concurrent_attacks_against_same_tile_are_serialized(engine):
    """The target row lock prevents both transactions from consuming the same
    pre-attack garrison snapshot."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with factory() as setup:
        world = await make_world(setup)
        attacker_a_bl = await make_bloodline(setup, "kindled_concurrent")
        attacker_b_bl = await make_bloodline(setup, "driftborn")
        defender_bl = await make_bloodline(setup, "deepwell_concurrent")
        attacker_a = await make_kingdom(setup, world.id, attacker_a_bl.id)
        attacker_b = await make_kingdom(setup, world.id, attacker_b_bl.id)
        defender = await make_kingdom(setup, world.id, defender_bl.id)
        troop = await make_troop_type(setup)

        origin_a = await make_tile(setup, world.id, 0, 0, attacker_a.id)
        origin_b = await make_tile(setup, world.id, 0, 1, attacker_b.id)
        target = await make_tile(setup, world.id, 5, 5, defender.id)
        await make_garrison(setup, origin_a.id, attacker_a.id, troop.id, 12)
        await make_garrison(setup, origin_b.id, attacker_b.id, troop.id, 12)
        await make_garrison(setup, target.id, defender.id, troop.id, 10)
        await _deduct_origin(setup, origin_a.id, attacker_a.id, troop.id, 12)
        await _deduct_origin(setup, origin_b.id, attacker_b.id, troop.id, 12)
        march_a = await make_march(
            setup, world.id, attacker_a.id, origin_a.id, target.id, 12, troop.id
        )
        march_b = await make_march(
            setup, world.id, attacker_b.id, origin_b.id, target.id, 12, troop.id
        )
        await setup.commit()

    async def resolve_in_own_session(march_id):
        async with factory() as tx:
            log = await resolve_march(tx, march_id)
            await tx.commit()
            return log

    logs = await asyncio.gather(
        resolve_in_own_session(march_a.id),
        resolve_in_own_session(march_b.id),
    )

    assert len(logs) == 2
    assert sum(log.result["defender_casualties"] for log in logs) == 12
    assert any(log.result["defender_power"] == 10 for log in logs)

    async with factory() as check:
        target_after = await check.get(Tile, target.id)
        assert target_after.owner_kingdom_id in {attacker_a.id, attacker_b.id}

        garrisons = (
            await check.execute(
                select(TileGarrison).where(TileGarrison.tile_id == target.id)
            )
        ).scalars().all()
        assert all(g.quantity >= 0 for g in garrisons)
        assert sum(g.quantity for g in garrisons) == 10
