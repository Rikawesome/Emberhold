"""Training lifecycle tests.

Covers:
- training queue creation
- resource deduction
- insufficient-resource protection
- invalid quantity protection
- signature troop bloodline restriction
- queue completion
- troop delivery to garrison
- existing garrison merging
- no premature completion
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.jobs.complete_queues import process_queues
from app.models.kingdom import KingdomResource
from app.models.tile import TileGarrison
from app.models.troop import TrainingQueue
from app.routers.troops import train_troops
from app.schemas.troop import TrainRequest
from tests.conftest import (
    make_bloodline,
    make_kingdom,
    make_tile,
    make_troop_type,
    make_world,
)


@pytest.mark.asyncio
async def test_training_queue_is_created_and_resources_are_deducted(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        owner_kingdom_id=kingdom.id,
    )

    troop = await make_troop_type(
        session,
        bloodline_id=bloodline.id,
        resource_costs={"sustenance": 4, "emberlight": 2},
    )

    session.add_all(
        [
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="sustenance",
                amount=100,
                rate_per_hour=0,
                last_collected_at=datetime.now(timezone.utc),
            ),
            KingdomResource(
                kingdom_id=kingdom.id,
                resource_type="emberlight",
                amount=100,
                rate_per_hour=0,
                last_collected_at=datetime.now(timezone.utc),
            ),
        ]
    )
    await session.flush()

    result = await train_troops(
        kingdom_id=kingdom.id,
        tile_id=tile.id,
        payload=TrainRequest(
            troop_type_id=troop.id,
            quantity=5,
        ),
        player_id=kingdom.player_id,
        session=session,
    )

    queue = await session.get(TrainingQueue, result.queue_id)

    assert queue is not None
    assert queue.quantity == 5
    assert queue.tile_id == tile.id
    assert queue.troop_type_id == troop.id
    assert queue.status == "in_progress"

    sustenance = await session.scalar(
        select(KingdomResource).where(
            KingdomResource.kingdom_id == kingdom.id,
            KingdomResource.resource_type == "sustenance",
        )
    )
    emberlight = await session.scalar(
        select(KingdomResource).where(
            KingdomResource.kingdom_id == kingdom.id,
            KingdomResource.resource_type == "emberlight",
        )
    )

    assert sustenance.amount == pytest.approx(80)
    assert emberlight.amount == pytest.approx(90)


@pytest.mark.asyncio
async def test_training_with_insufficient_resources_does_not_create_queue(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        owner_kingdom_id=kingdom.id,
    )

    troop = await make_troop_type(
        session,
        bloodline_id=bloodline.id,
        resource_costs={"sustenance": 4},
    )

    session.add(
        KingdomResource(
            kingdom_id=kingdom.id,
            resource_type="sustenance",
            amount=10,
            rate_per_hour=0,
            last_collected_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await train_troops(
            kingdom_id=kingdom.id,
            tile_id=tile.id,
            payload=TrainRequest(
                troop_type_id=troop.id,
                quantity=3,
            ),
            player_id=kingdom.player_id,
            session=session,
        )

    assert exc.value.status_code == 400

    queues = (
        await session.execute(
            select(TrainingQueue).where(
                TrainingQueue.kingdom_id == kingdom.id
            )
        )
    ).scalars().all()
    assert len(queues) == 0


def test_training_quantity_must_be_positive():
    with pytest.raises(ValueError):
        TrainRequest(
            troop_type_id="00000000-0000-0000-0000-000000000001",
            quantity=0,
        )

    with pytest.raises(ValueError):
        TrainRequest(
            troop_type_id="00000000-0000-0000-0000-000000000001",
            quantity=-5,
        )


@pytest.mark.asyncio
async def test_signature_troop_requires_matching_bloodline(session):
    world = await make_world(session)

    kindled = await make_bloodline(session, "kindled")
    deepwell = await make_bloodline(session, "deepwell")

    kingdom = await make_kingdom(
        session,
        world.id,
        kindled.id,
    )

    tile = await make_tile(
        session,
        world.id,
        owner_kingdom_id=kingdom.id,
    )

    signature_troop = await make_troop_type(
        session,
        bloodline_id=deepwell.id,
        key="deepwell_signature",
    )

    # Change the helper-created troop to signature tier.
    signature_troop.tier = "signature"

    await session.flush()

    with pytest.raises(HTTPException) as exc:
        await train_troops(
            kingdom_id=kingdom.id,
            tile_id=tile.id,
            payload=TrainRequest(
                troop_type_id=signature_troop.id,
                quantity=1,
            ),
            player_id=kingdom.player_id,
            session=session,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_due_training_completes_into_new_garrison(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        owner_kingdom_id=kingdom.id,
    )

    troop = await make_troop_type(
        session,
        bloodline_id=bloodline.id,
    )

    now = datetime.now(timezone.utc)

    queue = TrainingQueue(
        kingdom_id=kingdom.id,
        tile_id=tile.id,
        troop_type_id=troop.id,
        quantity=10,
        started_at=now - timedelta(minutes=60),
        completes_at=now - timedelta(minutes=1),
        status="in_progress",
    )

    session.add(queue)
    await session.flush()

    await process_queues(session)
    await session.flush()

    garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == tile.id,
            TileGarrison.kingdom_id == kingdom.id,
            TileGarrison.troop_type_id == troop.id,
        )
    )

    refreshed_queue = await session.get(
        TrainingQueue,
        queue.id,
    )

    assert garrison is not None
    assert garrison.quantity == 10
    assert refreshed_queue.status == "complete"


@pytest.mark.asyncio
async def test_due_training_merges_into_existing_garrison(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        owner_kingdom_id=kingdom.id,
    )

    troop = await make_troop_type(
        session,
        bloodline_id=bloodline.id,
    )

    existing = TileGarrison(
        tile_id=tile.id,
        kingdom_id=kingdom.id,
        troop_type_id=troop.id,
        quantity=25,
    )
    session.add(existing)

    now = datetime.now(timezone.utc)

    queue = TrainingQueue(
        kingdom_id=kingdom.id,
        tile_id=tile.id,
        troop_type_id=troop.id,
        quantity=10,
        started_at=now - timedelta(minutes=60),
        completes_at=now - timedelta(minutes=1),
        status="in_progress",
    )

    session.add(queue)
    await session.flush()

    await process_queues(session)
    await session.flush()

    garrisons = (
        await session.execute(
            select(TileGarrison).where(
                TileGarrison.tile_id == tile.id,
                TileGarrison.kingdom_id == kingdom.id,
                TileGarrison.troop_type_id == troop.id,
            )
        )
    ).scalars().all()

    assert len(garrisons) == 1
    assert garrisons[0].quantity == 35


@pytest.mark.asyncio
async def test_training_not_due_is_not_completed(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session, "kindled")
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    tile = await make_tile(
        session,
        world.id,
        owner_kingdom_id=kingdom.id,
    )

    troop = await make_troop_type(
        session,
        bloodline_id=bloodline.id,
    )

    now = datetime.now(timezone.utc)

    queue = TrainingQueue(
        kingdom_id=kingdom.id,
        tile_id=tile.id,
        troop_type_id=troop.id,
        quantity=10,
        started_at=now,
        completes_at=now + timedelta(minutes=30),
        status="in_progress",
    )

    session.add(queue)
    await session.flush()

    await process_queues(session)
    await session.flush()

    garrison = await session.scalar(
        select(TileGarrison).where(
            TileGarrison.tile_id == tile.id,
            TileGarrison.kingdom_id == kingdom.id,
            TileGarrison.troop_type_id == troop.id,
        )
    )

    refreshed_queue = await session.get(
        TrainingQueue,
        queue.id,
    )

    assert garrison is None
    assert refreshed_queue.status == "in_progress"
    