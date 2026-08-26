import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.kingdom import Kingdom
from app.models.player import Bloodline
from app.schemas.kingdom import KingdomResponse
from app.services import production

router = APIRouter(prefix="/kingdoms", tags=["kingdoms"])


@router.get("/me", response_model=KingdomResponse)
async def get_my_kingdom(
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = None
    # A player currently has one kingdom in the default world (Section 6 of the
    # design doc doesn't yet cover multi-world play per player — extend here if that changes).
    from sqlalchemy import select

    kingdom = await session.scalar(select(Kingdom).where(Kingdom.player_id == player_id))
    if kingdom is None:
        raise HTTPException(status_code=404, detail="No kingdom found for this player")

    bloodline = await session.get(Bloodline, kingdom.bloodline_id)
    resources = await production.collect_all(session, kingdom.id)
    await session.commit()

    return KingdomResponse(
        id=kingdom.id,
        name=kingdom.name,
        bloodline=bloodline.key,
        world_id=kingdom.world_id,
        capital_tile_id=kingdom.capital_tile_id,
        kindling_shield_expires_at=kingdom.kindling_shield_expires_at,
        resources=resources,
    )


@router.get("/{kingdom_id}", response_model=KingdomResponse)
async def get_kingdom_public(
    kingdom_id: uuid.UUID,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    """Public view. TODO: respect Wardens intel bonus for the requester (garrison
    visibility) and strip private queue details that /me includes.
    """
    kingdom = await session.get(Kingdom, kingdom_id)
    if kingdom is None:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    bloodline = await session.get(Bloodline, kingdom.bloodline_id)
    resources = await production.collect_all(session, kingdom.id)
    await session.commit()

    return KingdomResponse(
        id=kingdom.id,
        name=kingdom.name,
        bloodline=bloodline.key,
        world_id=kingdom.world_id,
        capital_tile_id=kingdom.capital_tile_id,
        kindling_shield_expires_at=kingdom.kindling_shield_expires_at,
        resources=resources,
    )
