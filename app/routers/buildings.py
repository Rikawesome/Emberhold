import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.kingdom import Kingdom
from app.models.tile import Building, BuildingQueue, Tile
from app.schemas.tile import BuildQueueEntry, BuildRequest
from app.services import production

router = APIRouter(prefix="/kingdoms/{kingdom_id}", tags=["buildings"])

# Placeholder costs/durations — move to app/data/ alongside troop_types.py once
# building balance is actually decided, matching Section 5 of the design doc.
BUILDING_COSTS = {
    "wellspring_tap": {"scrap": 30, "emberlight": 10},
    "grove_farm": {"scrap": 25, "sustenance": 5},
    "ashfield_works": {"scrap": 20},
    "barracks": {"scrap": 40, "emberlight": 15},
    "fortification": {"scrap": 50},
}
BUILD_DURATION_MINUTES = {
    "wellspring_tap": 30, "grove_farm": 20, "ashfield_works": 25, "barracks": 45, "fortification": 60,
}


@router.post("/tiles/{tile_id}/build", response_model=BuildQueueEntry, status_code=202)
async def build_on_tile(
    kingdom_id: uuid.UUID,
    tile_id: uuid.UUID,
    payload: BuildRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)
    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(status_code=403, detail="Not your kingdom")

    tile = await session.get(Tile, tile_id)
    if tile is None or tile.owner_kingdom_id != kingdom_id:
        raise HTTPException(status_code=403, detail="Tile not owned by this kingdom")

    existing = await session.scalar(select(Building).where(Building.tile_id == tile_id))
    if existing:
        raise HTTPException(status_code=409, detail="Tile already has a building")

    costs = BUILDING_COSTS.get(payload.building_type)
    if costs is None:
        raise HTTPException(status_code=422, detail="Unknown building type")

    try:
        await production.spend(session, kingdom_id, costs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    completes_at = datetime.now(timezone.utc) + timedelta(
        minutes=BUILD_DURATION_MINUTES.get(payload.building_type, 30)
    )
    entry = BuildingQueue(tile_id=tile_id, building_type=payload.building_type, completes_at=completes_at)
    session.add(entry)
    await session.commit()

    return BuildQueueEntry(
        queue_id=entry.id, tile_id=tile_id, building_type=payload.building_type, completes_at=completes_at
    )


@router.get("/building-queue", response_model=list[BuildQueueEntry])
async def get_building_queue(
    kingdom_id: uuid.UUID,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)
    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(status_code=403, detail="Not your kingdom")

    # TODO: join through Tile to filter to this kingdom's tiles once that relationship
    # is needed at scale — fine as a placeholder for a single-kingdom queue view.
    entries = (
        await session.execute(select(BuildingQueue).where(BuildingQueue.status == "in_progress"))
    ).scalars().all()

    return [
        BuildQueueEntry(queue_id=e.id, tile_id=e.tile_id, building_type=e.building_type, completes_at=e.completes_at)
        for e in entries
    ]
