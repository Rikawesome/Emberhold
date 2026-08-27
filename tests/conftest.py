"""Test DB fixtures.

Requires a separate test database — don't point this at your real dev DB, since
create_all/drop_all wipes everything. Set TEST_DATABASE_URL in your environment or
.env, e.g.:

    TEST_DATABASE_URL=postgresql+asyncpg://longdimming:longdimming@localhost:5432/longdimming_test

Each test runs inside a transaction that's rolled back at the end, so tests never
leak state into each other — you don't need to manually clean up between tests.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# asyncpg is incompatible with Windows' default ProactorEventLoop — it doesn't raise
# an error, it just hangs on certain operations. This forces the SelectorEventLoop
# policy before any event loop is created. Must run at import time, before pytest-asyncio
# sets anything up — hence it's here at the top of conftest.py rather than in a fixture.
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.db import Base
from app.models.kingdom import Kingdom, World
from app.models.march import March
from app.models.player import Bloodline, Player
from app.models.tile import Tile, TileGarrison
from app.models.troop import TroopType

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://longdimming:longdimming@localhost:5432/longdimming_test"
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        # Reset the schema outright rather than trusting drop_all's dependency
        # ordering — on some FK graphs it fails with "DependentObjectsStillExistError"
        # even though the tables are correctly related. A full schema reset sidesteps
        # that entirely and guarantees a clean slate at the start of every test run.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


from typing import AsyncIterator # Add this import at the top of your file if it's missing

@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    connection = await engine.connect()
    transaction = await connection.begin()
    async_session = async_sessionmaker(bind=connection, expire_on_commit=False)
    sess = async_session()

    yield sess

    await sess.close()
    await transaction.rollback()
    await connection.close()



# ---------- factory helpers for building test data quickly ----------

async def make_world(session: AsyncSession) -> World:
    world = World(name="Test World")
    session.add(world)
    await session.flush()
    return world


async def make_bloodline(session: AsyncSession, key: str | None = None) -> Bloodline:
    # Use a unique key if none is provided to prevent database constraint collision errors
    if key is None:
        key = f"bloodline_{uuid.uuid4().hex[:12]}"
    
    bloodline = Bloodline(
        key=key, name=key.title().replace("_", " "), resonance_type="emberdust",
        strength_desc="test", weakness_desc="test",
    )
    session.add(bloodline)
    await session.flush()
    return bloodline


async def make_tile(session: AsyncSession, world_id: uuid.UUID, x: int = 0, y: int = 0, owner_kingdom_id=None) -> Tile:
    tile = Tile(world_id=world_id, x=x, y=y, terrain_type="plain", base_yield={}, owner_kingdom_id=owner_kingdom_id)
    session.add(tile)
    await session.flush()
    return tile


async def make_player(session: AsyncSession, username: str | None = None) -> Player:
    username = username or f"test_{uuid.uuid4().hex[:12]}"
    player = Player(
        username=username, email=f"{username}@example.test", password_hash="not-a-real-hash",
    )
    session.add(player)
    await session.flush()
    return player


async def make_kingdom(session: AsyncSession, world_id: uuid.UUID, bloodline_id: uuid.UUID, player_id=None) -> Kingdom:
    if player_id is None:
        player = await make_player(session)
        player_id = player.id

    kingdom = Kingdom(
        player_id=player_id,
        world_id=world_id, bloodline_id=bloodline_id, name="Test Hold",
        kindling_shield_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # already expired by default
    )
    session.add(kingdom)
    await session.flush()
    return kingdom


async def make_troop_type(
    session: AsyncSession, bloodline_id: uuid.UUID | None = None, key: str | None = None,
    stats: dict | None = None, ability_key: str | None = None,
) -> TroopType:
    # Use a unique key if none is provided to avoid overlapping test failures
    if key is None:
        key = f"troop_{uuid.uuid4().hex[:12]}"

    troop = TroopType(
        bloodline_id=bloodline_id, key=key, name=key.title().replace("_", " "), tier="basic",
        stats=stats or {"attack": 1, "defense": 1}, ability_key=ability_key, resource_costs={},
    )
    session.add(troop)
    await session.flush()
    return troop


async def make_garrison(session: AsyncSession, tile_id, kingdom_id, troop_type_id, quantity: int) -> TileGarrison:
    garrison = TileGarrison(tile_id=tile_id, kingdom_id=kingdom_id, troop_type_id=troop_type_id, quantity=quantity)
    session.add(garrison)
    await session.flush()
    return garrison


async def make_march(session: AsyncSession, world_id, kingdom_id, origin_tile_id, target_tile_id, quantity: int, troop_type_id) -> March:
    march = March(
        world_id=world_id, kingdom_id=kingdom_id, origin_tile_id=origin_tile_id, target_tile_id=target_tile_id,
        troop_stack=[{"troop_type_id": str(troop_type_id), "quantity": quantity}],
        march_type="attack",
        departure_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        arrival_at=datetime.now(timezone.utc),  # already arrived, ready to resolve
        status="marching",
    )
    session.add(march)
    await session.flush()
    return march
