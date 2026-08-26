"""Production math tests — the foundation everything else costs against. See the
build order note in the API reference doc for why this comes before buildings/troops.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.kingdom import KingdomResource
from app.services.production import collect_resource, spend
from tests.conftest import make_bloodline, make_kingdom, make_world


@pytest.mark.asyncio
async def test_collect_resource_accrues_by_elapsed_time(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    resource = KingdomResource(
        kingdom_id=kingdom.id, resource_type="emberlight",
        amount=100, rate_per_hour=10, last_collected_at=one_hour_ago,
    )
    session.add(resource)
    await session.flush()

    updated = await collect_resource(session, kingdom.id, "emberlight")

    # ~1 hour elapsed at rate 10/hr → should have accrued close to +10.
    # Allow a little slack for the real time this test takes to run.
    assert 109.9 <= updated.amount <= 110.5


@pytest.mark.asyncio
async def test_spend_raises_on_insufficient_resources_and_deducts_nothing(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    now = datetime.now(timezone.utc)
    session.add(KingdomResource(kingdom_id=kingdom.id, resource_type="emberlight", amount=50, rate_per_hour=0, last_collected_at=now))
    session.add(KingdomResource(kingdom_id=kingdom.id, resource_type="scrap", amount=5, rate_per_hour=0, last_collected_at=now))
    await session.flush()

    # emberlight is affordable, scrap is not — the whole spend should fail and
    # neither resource should be touched, not just the one that ran short.
    with pytest.raises(ValueError):
        await spend(session, kingdom.id, {"emberlight": 20, "scrap": 100})

    emberlight = await collect_resource(session, kingdom.id, "emberlight")
    scrap = await collect_resource(session, kingdom.id, "scrap")
    assert emberlight.amount == 50
    assert scrap.amount == 5


@pytest.mark.asyncio
async def test_spend_deducts_all_resources_when_affordable(session):
    world = await make_world(session)
    bloodline = await make_bloodline(session)
    kingdom = await make_kingdom(session, world.id, bloodline.id)

    now = datetime.now(timezone.utc)
    session.add(KingdomResource(kingdom_id=kingdom.id, resource_type="emberlight", amount=50, rate_per_hour=0, last_collected_at=now))
    session.add(KingdomResource(kingdom_id=kingdom.id, resource_type="scrap", amount=50, rate_per_hour=0, last_collected_at=now))
    await session.flush()

    await spend(session, kingdom.id, {"emberlight": 20, "scrap": 10})

    emberlight = await collect_resource(session, kingdom.id, "emberlight")
    scrap = await collect_resource(session, kingdom.id, "scrap")
    assert emberlight.amount == 30
    assert scrap.amount == 40
