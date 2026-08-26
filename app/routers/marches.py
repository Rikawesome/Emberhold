import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.kingdom import Kingdom
from app.models.march import March
from app.models.tile import Tile, TileGarrison
from app.schemas.march import MarchRequest, MarchResponse, MarchStatusEntry
from app.services import marches as march_service

router = APIRouter(prefix="/kingdoms/{kingdom_id}/marches", tags=["marches"])


@router.post("", response_model=MarchResponse, status_code=202)
async def create_march(
    kingdom_id: uuid.UUID,
    payload: MarchRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)
    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(status_code=403, detail="Not your kingdom")

    origin = await session.get(Tile, payload.origin_tile_id)
    target = await session.get(Tile, payload.target_tile_id)
    if origin is None or origin.owner_kingdom_id != kingdom_id:
        raise HTTPException(status_code=403, detail="Origin tile not owned by this kingdom")
    if target is None:
        raise HTTPException(status_code=404, detail="Target tile not found")

    if await march_service.check_kindling_shield(target, session):
        raise HTTPException(status_code=403, detail="Target is under a Kindling Shield")

    # Validate origin garrison has enough troops and deduct them
    # Lock in deterministic order to avoid deadlocks
    sorted_troop_stack = sorted(payload.troop_stack, key=lambda e: e.troop_type_id)
    for entry in sorted_troop_stack:
        # Lock the garrison row for this troop type at the origin tile
        garrison_result = await session.execute(
            select(TileGarrison)
            .where(
                TileGarrison.tile_id == origin.id,
                TileGarrison.kingdom_id == kingdom_id,
                TileGarrison.troop_type_id == entry.troop_type_id
            )
            .with_for_update()
        )
        garrison = garrison_result.scalar_one_or_none()
        
        if garrison is None or garrison.quantity < entry.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient troops for troop type {entry.troop_type_id}: "
                       f"requested {entry.quantity}, available {garrison.quantity if garrison else 0}"
            )
        
        # Deduct troops from garrison
        garrison.quantity -= entry.quantity

    travel_time = march_service.calculate_travel_time(origin, target)
    now = datetime.now(timezone.utc)
    arrival_at = now + travel_time

    march = March(
        world_id=kingdom.world_id, kingdom_id=kingdom_id,
        origin_tile_id=origin.id, target_tile_id=target.id,
        troop_stack=[e.model_dump(mode="json") for e in payload.troop_stack],
        march_type=payload.march_type, departure_at=now, arrival_at=arrival_at,
    )
    session.add(march)
    await session.commit()

    return MarchResponse(march_id=march.id, departure_at=now, arrival_at=arrival_at)


@router.get("", response_model=list[MarchStatusEntry])
async def list_marches(
    kingdom_id: uuid.UUID,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)
    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(status_code=403, detail="Not your kingdom")

    rows = (
        await session.execute(select(March).where(March.kingdom_id == kingdom_id))
    ).scalars().all()

    return [
        MarchStatusEntry(
            march_id=m.id, origin_tile_id=m.origin_tile_id, target_tile_id=m.target_tile_id,
            march_type=m.march_type, status=m.status, arrival_at=m.arrival_at,
        )
        for m in rows
    ]
