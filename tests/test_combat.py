"""Combat resolution tests.

See Section 11 of the API reference doc: this is the highest-risk code in the
project.

These tests cover:
- baseline stat-weighted combat
- Scorch
- Chill
- Bulwark
- Breach
- Aegis Core
- simultaneous-attack concurrency
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


@pytest.mark.asyncio
async def test_attacker_wins_captures_tile_with_survivors(session):
    world = await make_world(session)
    attacker_bloodline = await make_bloodline(session, "kindled")
    defender_bloodline = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bloodline.id)
    defender = await make_kingdom(session, world.id, defender_bloodline.id)
    troop_type = await make_troop_type(session)

    origin = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=attacker.id,
    )
    target = await make_tile(
        session,
        world.id,
        x=1,
        y=0,
        owner_kingdom_id=defender.id,
    )

    await make_garrison(
        session,
        target.id,
        defender.id,
        troop_type.id,
        quantity=4,
    )

    march = await make_march(
        session,
        world.id,
        attacker.id,
        origin.id,
        target.id,
        quantity=10,
        troop_type_id=troop_type.id,
    )
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    refreshed_target = await session.get(Tile, target.id)

    assert refreshed_target.owner_kingdom_id == attacker.id
    assert log.result["outcome"] == "captured"
    assert log.result["attacker_power"] == 10
    assert log.result["defender_power"] == 4

    surviving_garrison = (
        await session.execute(
            select(TileGarrison).where(
                TileGarrison.tile_id == target.id
            )
        )
    ).scalars().all()

    attacker_rows = [
        g for g in surviving_garrison
        if g.kingdom_id == attacker.id
    ]
    defender_rows = [
        g for g in surviving_garrison
        if g.kingdom_id == defender.id
    ]

    assert sum(g.quantity for g in attacker_rows) == 6
    assert all(g.quantity == 0 for g in defender_rows)


@pytest.mark.asyncio
async def test_defender_wins_garrison_reduced_not_tile_flipped(session):
    world = await make_world(session)
    attacker_bloodline = await make_bloodline(session, "kindled")
    defender_bloodline = await make_bloodline(session, "deepwell")
    attacker = await make_kingdom(session, world.id, attacker_bloodline.id)
    defender = await make_kingdom(session, world.id, defender_bloodline.id)
    troop_type = await make_troop_type(session)

    origin = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=attacker.id,
    )
    target = await make_tile(
        session,
        world.id,
        x=1,
        y=0,
        owner_kingdom_id=defender.id,
    )

    await make_garrison(
        session,
        target.id,
        defender.id,
        troop_type.id,
        quantity=20,
    )

    march = await make_march(
        session,
        world.id,
        attacker.id,
        origin.id,
        target.id,
        quantity=5,
        troop_type_id=troop_type.id,
    )
    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    refreshed_target = await session.get(Tile, target.id)

    assert refreshed_target.owner_kingdom_id == defender.id
    assert log.result["outcome"] == "repelled"

    remaining = await session.scalar(
        select(TileGarrison.quantity).where(
            TileGarrison.tile_id == target.id
        )
    )

    assert remaining == 15


@pytest.mark.asyncio
async def test_scorch_doubles_archer_offense(session):
    """Scorch doubles Cinder Archer offense for this battle.

    5 archers @ attack=2 normally contribute 10 offense.
    Scorch makes that 20.

    Defender has 15 defense, so the normal attack would lose,
    while the Scorch attack wins.
    """
    world = await make_world(session)

    attacker_bloodline = await make_bloodline(session, "kindled")
    defender_bloodline = await make_bloodline(session, "deepwell")

    attacker = await make_kingdom(
        session,
        world.id,
        attacker_bloodline.id,
    )
    defender = await make_kingdom(
        session,
        world.id,
        defender_bloodline.id,
    )

    archers = await make_troop_type(
        session,
        key="test_archers",
        stats={"attack": 2, "defense": 1},
        ability_key="scorch",
    )

    defender_troop = await make_troop_type(
        session,
        key="test_defenders",
        stats={"attack": 1, "defense": 3},
    )

    origin = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=attacker.id,
    )
    target = await make_tile(
        session,
        world.id,
        x=1,
        y=0,
        owner_kingdom_id=defender.id,
    )

    await make_garrison(
        session,
        target.id,
        defender.id,
        defender_troop.id,
        quantity=5,
    )

    march = await make_march(
        session,
        world.id,
        attacker.id,
        origin.id,
        target.id,
        quantity=5,
        troop_type_id=archers.id,
    )

    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["attacker_power"] == 20
    assert log.result["outcome"] == "captured"


@pytest.mark.asyncio
async def test_chill_reduces_attacker_offense(session):
    """Chill reduces the attacker's effective offense.

    10 attackers @ attack=2 = 20 offense.
    10 Chill defenders reduce this by 5.
    Effective offense = 15.

    Defender defense is also 15, so the attack is repelled because
    victory requires offense to strictly exceed defense.
    """
    world = await make_world(session)

    attacker_bloodline = await make_bloodline(session, "kindled")
    defender_bloodline = await make_bloodline(session, "deepwell")

    attacker = await make_kingdom(
        session,
        world.id,
        attacker_bloodline.id,
    )
    defender = await make_kingdom(
        session,
        world.id,
        defender_bloodline.id,
    )

    attacker_troop = await make_troop_type(
        session,
        key="test_attackers",
        stats={"attack": 2, "defense": 1},
    )

    slingers = await make_troop_type(
        session,
        key="test_slingers",
        stats={"attack": 1, "defense": 1.5},
        ability_key="chill",
    )

    origin = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=attacker.id,
    )
    target = await make_tile(
        session,
        world.id,
        x=1,
        y=0,
        owner_kingdom_id=defender.id,
    )

    await make_garrison(
        session,
        target.id,
        defender.id,
        slingers.id,
        quantity=10,
    )

    march = await make_march(
        session,
        world.id,
        attacker.id,
        origin.id,
        target.id,
        quantity=10,
        troop_type_id=attacker_troop.id,
    )

    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["attacker_power"] == 15
    assert log.result["outcome"] == "repelled"


@pytest.mark.asyncio
async def test_bulwark_survivors_freeze_instead_of_dying(session):
    """Bulwark troops survive at half strength when their garrison loses."""
    world = await make_world(session)

    attacker_bloodline = await make_bloodline(session, "kindled")
    defender_bloodline = await make_bloodline(session, "deepwell")

    attacker = await make_kingdom(
        session,
        world.id,
        attacker_bloodline.id,
    )
    defender = await make_kingdom(
        session,
        world.id,
        defender_bloodline.id,
    )

    def_capital = await make_tile(
        session,
        world.id,
        x=10,
        y=10,
        owner_kingdom_id=defender.id,
    )
    defender.capital_tile_id = def_capital.id

    attacker_troop = await make_troop_type(
        session,
        key="test_attackers2",
        stats={"attack": 2, "defense": 1},
    )

    wardens = await make_troop_type(
        session,
        key="test_wardens",
        stats={"attack": 1, "defense": 1},
        ability_key="bulwark",
    )

    origin = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=attacker.id,
    )
    target = await make_tile(
        session,
        world.id,
        x=1,
        y=0,
        owner_kingdom_id=defender.id,
    )

    await make_garrison(
        session,
        target.id,
        defender.id,
        wardens.id,
        quantity=10,
    )

    march = await make_march(
        session,
        world.id,
        attacker.id,
        origin.id,
        target.id,
        quantity=10,
        troop_type_id=attacker_troop.id,
    )

    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["outcome"] == "captured"

    remaining_wardens = await session.scalar(
        select(TileGarrison.quantity).where(
            TileGarrison.tile_id == def_capital.id,
            TileGarrison.troop_type_id == wardens.id,
        )
    )

    assert remaining_wardens == 5



@pytest.mark.asyncio
async def test_breach_bonus_against_built_tile(session):
    """Siege Engineers receive a 1.5x offense bonus against built tiles."""
    world = await make_world(session)

    attacker_bloodline = await make_bloodline(
        session,
        "emberwrights",
    )
    defender_bloodline = await make_bloodline(
        session,
        "deepwell",
    )

    attacker = await make_kingdom(
        session,
        world.id,
        attacker_bloodline.id,
    )
    defender = await make_kingdom(
        session,
        world.id,
        defender_bloodline.id,
    )

    engineers = await make_troop_type(
        session,
        key="test_engineers",
        stats={"attack": 1, "defense": 1},
        ability_key="breach",
    )

    defender_troop = await make_troop_type(
        session,
        key="test_def2",
        stats={"attack": 1, "defense": 4},
    )

    origin = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=attacker.id,
    )
    target = await make_tile(
        session,
        world.id,
        x=1,
        y=0,
        owner_kingdom_id=defender.id,
    )

    await make_garrison(
        session,
        target.id,
        defender.id,
        defender_troop.id,
        quantity=3,
    )

    session.add(
        Building(
            tile_id=target.id,
            building_type="fortification",
        )
    )

    march = await make_march(
        session,
        world.id,
        attacker.id,
        origin.id,
        target.id,
        quantity=10,
        troop_type_id=engineers.id,
    )

    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["attacker_power"] == 15
    assert log.result["outcome"] == "captured"


@pytest.mark.asyncio
async def test_aegis_core_boosts_adjacent_tile_defense(session):
    """Aegis Core boosts defense from adjacent same-kingdom tiles."""
    world = await make_world(session)

    attacker_bloodline = await make_bloodline(session, "kindled")
    defender_bloodline = await make_bloodline(
        session,
        "emberwrights",
    )

    attacker = await make_kingdom(
        session,
        world.id,
        attacker_bloodline.id,
    )
    defender = await make_kingdom(
        session,
        world.id,
        defender_bloodline.id,
    )

    forgeguard = await make_troop_type(
        session,
        key="test_forgeguard",
        stats={"attack": 1, "defense": 1},
        ability_key="aegis_core",
    )

    weak_attacker = await make_troop_type(
        session,
        key="test_weak",
        stats={"attack": 1, "defense": 1},
    )

    origin = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=attacker.id,
    )

    target = await make_tile(
        session,
        world.id,
        x=5,
        y=5,
        owner_kingdom_id=defender.id,
    )

    adjacent = await make_tile(
        session,
        world.id,
        x=5,
        y=6,
        owner_kingdom_id=defender.id,
    )

    await make_garrison(
        session,
        adjacent.id,
        defender.id,
        forgeguard.id,
        quantity=2,
    )

    march = await make_march(
        session,
        world.id,
        attacker.id,
        origin.id,
        target.id,
        quantity=3,
        troop_type_id=weak_attacker.id,
    )

    await session.commit()

    log = await resolve_march(session, march.id)
    await session.commit()

    assert log.result["defender_power"] == 4
    assert log.result["outcome"] == "repelled"


@pytest.mark.asyncio
async def test_simultaneous_attacks_are_serialized(engine):
    """Two attacks against the same tile must not both consume the same
    pre-battle garrison state.

    The target tile is row-locked by resolve_march(), so whichever transaction
    acquires the lock first resolves against the original garrison. The second
    transaction then sees the updated tile/garrison state.
    """
    async_session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    async with async_session_factory() as setup_session:
        world = await make_world(setup_session)

        bloodline_a = await make_bloodline(
            setup_session,
            "kindled",
        )
        bloodline_b = await make_bloodline(
            setup_session,
            "driftborn",
        )
        defender_bloodline = await make_bloodline(
            setup_session,
            "deepwell",
        )

        attacker_a = await make_kingdom(
            setup_session,
            world.id,
            bloodline_a.id,
        )
        attacker_b = await make_kingdom(
            setup_session,
            world.id,
            bloodline_b.id,
        )
        defender = await make_kingdom(
            setup_session,
            world.id,
            defender_bloodline.id,
        )

        troop_type = await make_troop_type(setup_session)

        origin_a = await make_tile(
            setup_session,
            world.id,
            x=0,
            y=0,
            owner_kingdom_id=attacker_a.id,
        )

        origin_b = await make_tile(
            setup_session,
            world.id,
            x=0,
            y=1,
            owner_kingdom_id=attacker_b.id,
        )

        target = await make_tile(
            setup_session,
            world.id,
            x=5,
            y=5,
            owner_kingdom_id=defender.id,
        )

        await make_garrison(
            setup_session,
            target.id,
            defender.id,
            troop_type.id,
            quantity=10,
        )

        # Each attacker alone would win: 12 > 10.
        march_a = await make_march(
            setup_session,
            world.id,
            attacker_a.id,
            origin_a.id,
            target.id,
            quantity=12,
            troop_type_id=troop_type.id,
        )

        march_b = await make_march(
            setup_session,
            world.id,
            attacker_b.id,
            origin_b.id,
            target.id,
            quantity=12,
            troop_type_id=troop_type.id,
        )

        await setup_session.commit()

    async def resolve_in_own_session(march_id):
        async with async_session_factory() as s:
            log = await resolve_march(s, march_id)
            await s.commit()
            return log

    results = await asyncio.gather(
        resolve_in_own_session(march_a.id),
        resolve_in_own_session(march_b.id),
    )

    outcomes = {r.result["outcome"] for r in results}

    assert "captured" in outcomes

    async with async_session_factory() as check_session:
        final_garrisons = (
            await check_session.execute(
                select(TileGarrison).where(
                    TileGarrison.tile_id == target.id
                )
            )
        ).scalars().all()

        assert all(g.quantity >= 0 for g in final_garrisons)

        refreshed_target = await check_session.get(
            Tile,
            target.id,
        )

        assert refreshed_target.owner_kingdom_id in {
            attacker_a.id,
            attacker_b.id,
        }