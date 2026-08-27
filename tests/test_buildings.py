"""Building lifecycle tests.

Covers:
- construction queue creation
- resource deduction
- insufficient-resource protection
- queue completion
- completed building creation
- no premature completion
- duplicate-building database protection
- invalid building type protection
- tile ownership protection
- duplicate active construction protection
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.jobs.complete_queues import process_queues
from app.models.kingdom import KingdomResource
from app.models.tile import Building, BuildingQueue
from app.routers.buildings import BUILDING_COSTS, build_on_tile
from app.schemas.tile import BuildRequest
from tests.conftest import (
    make_bloodline,
    make_kingdom,
    make_tile,
    make_world,
)


@pytest.mark.asyncio
async def test_building_queue_can_be_completed(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=kingdom.id,
    )

    now = datetime.now(timezone.utc)

    queue = BuildingQueue(
        tile_id=tile.id,
        building_type="barracks",
        started_at=now - timedelta(minutes=50),
        completes_at=now - timedelta(minutes=1),
        status="in_progress",
    )
    session.add(queue)

    await session.commit()

    await process_queues(session)
    await session.flush()

    building = await session.scalar(
        select(Building).where(Building.tile_id == tile.id)
    )

    refreshed_queue = await session.get(BuildingQueue, queue.id)

    assert building is not None
    assert building.building_type == "barracks"
    assert refreshed_queue.status == "complete"


@pytest.mark.asyncio
async def test_building_queue_not_due_is_not_completed(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=kingdom.id,
    )

    now = datetime.now(timezone.utc)

    queue = BuildingQueue(
        tile_id=tile.id,
        building_type="barracks",
        started_at=now,
        completes_at=now + timedelta(minutes=30),
        status="in_progress",
    )
    session.add(queue)

    await session.commit()

    await process_queues(session)
    await session.flush()

    building = await session.scalar(
        select(Building).where(Building.tile_id == tile.id)
    )

    refreshed_queue = await session.get(BuildingQueue, queue.id)

    assert building is None
    assert refreshed_queue.status == "in_progress"


@pytest.mark.asyncio
async def test_completed_building_cannot_be_duplicated(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=kingdom.id,
    )

    session.add(
        Building(
            tile_id=tile.id,
            building_type="barracks",
        )
    )
    await session.flush()

    async with session.begin_nested():
        session.add(
            Building(
                tile_id=tile.id,
                building_type="fortification",
            )
        )

        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.asyncio
async def test_build_request_creates_queue_and_deducts_resources(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=kingdom.id,
    )

    now = datetime.now(timezone.utc)

    session.add_all(
        [
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="scrap",
                amount=100,
                rate_per_hour=0,
                last_collected_at=now,
            ),
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="emberlight",
                amount=100,
                rate_per_hour=0,
                last_collected_at=now,
            ),
        ]
    )

    await session.flush()

    result = await build_on_tile(
        kingdom_id=kingdom.id,
        tile_id=tile.id,
        payload=BuildRequest(building_type="barracks"),
        player_id=kingdom.player_id,
        session=session,
    )

    assert result.tile_id == tile.id
    assert result.building_type == "barracks"

    queue = await session.scalar(
        select(BuildingQueue).where(BuildingQueue.tile_id == tile.id)
    )

    assert queue is not None
    assert queue.status == "in_progress"
    assert queue.building_type == "barracks"

    scrap = await session.scalar(
        select(KingdomResource).where(
            KingdomResource.kingdom_id == kingdom.id,
            KingdomResource.resource_type == "scrap",
        )
    )
    emberlight = await session.scalar(
        select(KingdomResource).where(
            KingdomResource.kingdom_id == kingdom.id,
            KingdomResource.resource_type == "emberlight",
        )
    )

    assert scrap.amount == 60
    assert emberlight.amount == 85


@pytest.mark.asyncio
async def test_build_request_rejects_insufficient_resources_without_deduction(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=kingdom.id,
    )

    now = datetime.now(timezone.utc)

    session.add_all(
        [
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="scrap",
                amount=10,
                rate_per_hour=0,
                last_collected_at=now,
            ),
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="emberlight",
                amount=100,
                rate_per_hour=0,
                last_collected_at=now,
            ),
        ]
    )

    await session.flush()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await build_on_tile(
            kingdom_id=kingdom.id,
            tile_id=tile.id,
            payload=BuildRequest(building_type="barracks"),
            player_id=kingdom.player_id,
            session=session,
        )

    assert exc.value.status_code == 400

    queue = await session.scalar(
        select(BuildingQueue).where(BuildingQueue.tile_id == tile.id)
    )
    assert queue is None

    scrap = await session.scalar(
        select(KingdomResource).where(
            KingdomResource.kingdom_id == kingdom.id,
            KingdomResource.resource_type == "scrap",
        )
    )
    emberlight = await session.scalar(
        select(KingdomResource).where(
            KingdomResource.kingdom_id == kingdom.id,
            KingdomResource.resource_type == "emberlight",
        )
    )

    assert scrap.amount == 10
    assert emberlight.amount == 100


@pytest.mark.asyncio
async def test_build_request_rejects_unknown_building_type(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=kingdom.id,
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await build_on_tile(
            kingdom_id=kingdom.id,
            tile_id=tile.id,
            payload=BuildRequest(building_type="death_star"),
            player_id=kingdom.player_id,
            session=session,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_build_request_rejects_tile_owned_by_another_kingdom(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")

    attacker = await make_kingdom(session, world.id, bloodline.id)
    defender = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=defender.id,
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await build_on_tile(
            kingdom_id=attacker.id,
            tile_id=tile.id,
            payload=BuildRequest(building_type="barracks"),
            player_id=attacker.player_id,
            session=session,
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_build_request_rejects_duplicate_active_construction(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        x=0,
        y=0,
        owner_kingdom_id=kingdom.id,
    )

    now = datetime.now(timezone.utc)

    session.add(
        BuildingQueue(
            tile_id=tile.id,
            building_type="barracks",
            started_at=now,
            completes_at=now + timedelta(minutes=45),
            status="in_progress",
        )
    )

    session.add_all(
        [
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="scrap",
                amount=100,
                rate_per_hour=0,
                last_collected_at=now,
            ),
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="emberlight",
                amount=100,
                rate_per_hour=0,
                last_collected_at=now,
            ),
        ]
    )

    await session.flush()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await build_on_tile(
            kingdom_id=kingdom.id,
            tile_id=tile.id,
            payload=BuildRequest(building_type="fortification"),
            player_id=kingdom.player_id,
            session=session,
        )

    assert exc.value.status_code == 409

    queues = (
        await session.execute(
            select(BuildingQueue).where(
                BuildingQueue.tile_id == tile.id,
                BuildingQueue.status == "in_progress",
            )
        )
    ).scalars().all()

    assert len(queues) == 1
    assert queues[0].building_type == "barracks"