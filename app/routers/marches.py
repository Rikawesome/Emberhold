import uuid
from datetime import datetime, timedelta, timezone


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.kingdom import Kingdom
from app.models.march import March
from app.models.tile import Tile, TileGarrison
from app.models.troop import TroopType
from app.schemas.march import MarchRequest, MarchResponse, MarchStatusEntry
from app.services import marches as march_service

router = APIRouter(
    prefix="/kingdoms/{kingdom_id}/marches",
    tags=["marches"],
)


@router.post("", response_model=MarchResponse, status_code=202)
async def create_march(
    kingdom_id: uuid.UUID,
    payload: MarchRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)

    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(
            status_code=403,
            detail="Not your kingdom",
        )

    # Validate march_type
    if payload.march_type not in ["attack", "reinforce", "return"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid march type: {payload.march_type}",
        )

    origin = await session.get(Tile, payload.origin_tile_id)
    target = await session.get(Tile, payload.target_tile_id)

    if origin is None or origin.owner_kingdom_id != kingdom_id:
        raise HTTPException(
            status_code=403,
            detail="Origin tile not owned by this kingdom",
        )

    if target is None:
        raise HTTPException(
            status_code=404,
            detail="Target tile not found",
        )

    # Target relationship validation
    if payload.march_type == "attack" and target.owner_kingdom_id == kingdom_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot attack your own territory",
        )
        
    if payload.march_type == "reinforce" and target.owner_kingdom_id != kingdom_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot reinforce territory you do not own",
        )

    if await march_service.check_kindling_shield(target, session):
        raise HTTPException(
            status_code=403,
            detail="Target is under a Kindling Shield",
        )

    # Validate origin garrison has enough troops and deduct them.
    # Lock in deterministic order to avoid deadlocks.
    sorted_troop_stack = sorted(
        payload.troop_stack,
        key=lambda e: e.troop_type_id,
    )

    for entry in sorted_troop_stack:
        # Lock the garrison row for this troop type at the origin tile.
        garrison_result = await session.execute(
            select(TileGarrison)
            .where(
                TileGarrison.tile_id == origin.id,
                TileGarrison.kingdom_id == kingdom_id,
                TileGarrison.troop_type_id == entry.troop_type_id,
            )
            .with_for_update()
        )

        garrison = garrison_result.scalar_one_or_none()

        if garrison is None or garrison.quantity < entry.quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient troops for troop type "
                    f"{entry.troop_type_id}: requested {entry.quantity}, "
                    f"available {garrison.quantity if garrison else 0}"
                ),
            )

        # Deduct troops from garrison.
        garrison.quantity -= entry.quantity
        
        # Clean up the garrison row if the stack is fully depleted.
        if garrison.quantity == 0:
            await session.delete(garrison)

    # Determine whether the march contains a Stormrunner.
    troop_type_ids = {
        entry.troop_type_id
        for entry in payload.troop_stack
    }

    troop_types = (
        await session.execute(
            select(TroopType).where(
                TroopType.id.in_(troop_type_ids)
            )
        )
    ).scalars().all()

    has_flash_march = any(
        troop_type.ability_key == "flash_march"
        for troop_type in troop_types
    )

    now = datetime.now(timezone.utc)

    if has_flash_march:
        if kingdom.flash_march_available_at and now < kingdom.flash_march_available_at:
            raise HTTPException(
                status_code=400,
                detail="Flash March is on cooldown",
            )
        kingdom.flash_march_available_at = now + timedelta(hours=1)

    travel_time = march_service.calculate_travel_time(
        origin,
        target,
        has_flash_march=has_flash_march,
    )

    arrival_at = now + travel_time


    march = March(
        world_id=kingdom.world_id,
        kingdom_id=kingdom_id,
        origin_tile_id=origin.id,
        target_tile_id=target.id,
        troop_stack=[
            entry.model_dump(mode="json")
            for entry in payload.troop_stack
        ],
        march_type=payload.march_type,
        departure_at=now,
        arrival_at=arrival_at,
    )

    session.add(march)
    await session.commit()

    return MarchResponse(
        march_id=march.id,
        departure_at=now,
        arrival_at=arrival_at,
    )


@router.get(
    "",
    response_model=list[MarchStatusEntry],
)
async def list_marches(
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

    rows = (
        await session.execute(
            select(March).where(
                March.kingdom_id == kingdom_id
            )
        )
    ).scalars().all()

    return [
        MarchStatusEntry(
            march_id=march.id,
            origin_tile_id=march.origin_tile_id,
            target_tile_id=march.target_tile_id,
            march_type=march.march_type,
            status=march.status,
            arrival_at=march.arrival_at,
        )
        for march in rows
    ]