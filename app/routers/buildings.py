import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.kingdom import Kingdom
from app.models.tile import Building, BuildingQueue, Tile
from app.schemas.tile import BuildQueueEntry, BuildRequest
from app.services import production

router = APIRouter(prefix="/kingdoms/{kingdom_id}", tags=["buildings"])


# Placeholder balance values.
# Move these to app/data/ once building balance is finalized.
BUILDING_COSTS = {
    "wellspring_tap": {"scrap": 30, "emberlight": 10},
    "grove_farm": {"scrap": 25, "sustenance": 5},
    "ashfield_works": {"scrap": 20},
    "barracks": {"scrap": 40, "emberlight": 15},
    "fortification": {"scrap": 50},
}

BUILD_DURATION_MINUTES = {
    "wellspring_tap": 30,
    "grove_farm": 20,
    "ashfield_works": 25,
    "barracks": 45,
    "fortification": 60,
}


@router.post(
    "/tiles/{tile_id}/build",
    response_model=BuildQueueEntry,
    status_code=202,
)
async def build_on_tile(
    kingdom_id: uuid.UUID,
    tile_id: uuid.UUID,
    payload: BuildRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    # ------------------------------------------------------------------
    # Validate kingdom ownership.
    # ------------------------------------------------------------------
    kingdom = await session.get(Kingdom, kingdom_id)

    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(
            status_code=403,
            detail="Not your kingdom",
        )

    # ------------------------------------------------------------------
    # Validate building type before touching resources.
    # ------------------------------------------------------------------
    costs = BUILDING_COSTS.get(payload.building_type)

    if costs is None:
        raise HTTPException(
            status_code=422,
            detail="Unknown building type",
        )

    # ------------------------------------------------------------------
    # Lock the tile.
    #
    # This serializes concurrent construction attempts against the same
    # tile. Without this, two requests can both observe an empty tile.
    # ------------------------------------------------------------------
    tile = await session.scalar(
        select(Tile)
        .where(
            Tile.id == tile_id,
            Tile.owner_kingdom_id == kingdom_id,
        )
        .with_for_update()
    )

    if tile is None:
        # Deliberately don't reveal whether the tile exists but belongs
        # to somebody else.
        raise HTTPException(
            status_code=403,
            detail="Tile not owned by this kingdom",
        )

    # ------------------------------------------------------------------
    # A tile can only have one completed building.
    # ------------------------------------------------------------------
    existing_building = await session.scalar(
        select(Building)
        .where(Building.tile_id == tile_id)
    )

    if existing_building is not None:
        raise HTTPException(
            status_code=409,
            detail="Tile already has a building",
        )

    # ------------------------------------------------------------------
    # A tile can only have one active construction.
    # ------------------------------------------------------------------
    existing_queue = await session.scalar(
        select(BuildingQueue)
        .where(
            BuildingQueue.tile_id == tile_id,
            BuildingQueue.status == "in_progress",
        )
        .with_for_update()
    )

    if existing_queue is not None:
        raise HTTPException(
            status_code=409,
            detail="Tile already has a building under construction",
        )

    # ------------------------------------------------------------------
    # Spend resources only after all structural validation succeeds.
    # ------------------------------------------------------------------
    try:
        await production.spend(
            session,
            kingdom_id,
            costs,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    # ------------------------------------------------------------------
    # Create construction queue entry.
    # ------------------------------------------------------------------
    now = datetime.now(timezone.utc)

    completes_at = now + timedelta(
        minutes=BUILD_DURATION_MINUTES[payload.building_type]
    )

    entry = BuildingQueue(
        tile_id=tile_id,
        building_type=payload.building_type,
        started_at=now,
        completes_at=completes_at,
        status="in_progress",
    )

    session.add(entry)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()

        # Database-level uniqueness is the final guard against races.
        raise HTTPException(
            status_code=409,
            detail="Tile already has a building or active construction",
        )

    return BuildQueueEntry(
        queue_id=entry.id,
        tile_id=tile_id,
        building_type=entry.building_type,
        completes_at=entry.completes_at,
    )


@router.get(
    "/building-queue",
    response_model=list[BuildQueueEntry],
)
async def get_building_queue(
    kingdom_id: uuid.UUID,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)

    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(
            status_code=403,
            detail="Not your kingdom",
        )

    entries = (
        await session.execute(
            select(BuildingQueue)
            .join(Tile, Tile.id == BuildingQueue.tile_id)
            .where(
                Tile.owner_kingdom_id == kingdom_id,
                BuildingQueue.status == "in_progress",
            )
            .order_by(BuildingQueue.completes_at)
        )
    ).scalars().all()

    return [
        BuildQueueEntry(
            queue_id=entry.id,
            tile_id=entry.tile_id,
            building_type=entry.building_type,
            completes_at=entry.completes_at,
        )
        for entry in entries
    ]
