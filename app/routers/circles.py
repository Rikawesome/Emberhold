import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.circle import Circle, CircleMember, War
from app.models.kingdom import Kingdom
from app.schemas.circle import CircleInviteRequest, CircleResponse, CreateCircleRequest, DeclareWarRequest

router = APIRouter(prefix="/circles", tags=["circles"])


@router.post("", response_model=CircleResponse, status_code=201)
async def create_circle(
    payload: CreateCircleRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.scalar(
        select(Kingdom).where(Kingdom.player_id == player_id)
    )
    if kingdom is None:
        raise HTTPException(status_code=404, detail="No kingdom found for this player")

    circle = Circle(
        world_id=kingdom.world_id, bloodline_id=kingdom.bloodline_id,
        name=payload.name, created_by_kingdom_id=kingdom.id,
    )
    session.add(circle)
    await session.flush()
    session.add(CircleMember(circle_id=circle.id, kingdom_id=kingdom.id, role="leader"))
    await session.commit()
    return circle


@router.post("/{circle_id}/invite", status_code=204)
async def invite_to_circle(
    circle_id: uuid.UUID,
    payload: CircleInviteRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    """TODO: create an invite record and notify the invited kingdom over WebSocket.
    This scaffold just validates the circle exists.
    """
    circle = await session.get(Circle, circle_id)
    if circle is None:
        raise HTTPException(status_code=404, detail="Circle not found")


@router.post("/{circle_id}/join", status_code=204)
async def join_circle(
    circle_id: uuid.UUID,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.scalar(
        select(Kingdom).where(Kingdom.player_id == player_id)
    )
    circle = await session.get(Circle, circle_id)
    if circle is None or kingdom is None:
        raise HTTPException(status_code=404, detail="Circle or kingdom not found")
    if circle.bloodline_id != kingdom.bloodline_id:
        raise HTTPException(status_code=403, detail="Circles are scoped to a single bloodline")

    existing_member = await session.scalar(
        select(CircleMember).where(
            CircleMember.circle_id == circle_id,
            CircleMember.kingdom_id == kingdom.id,
        )
    )
    if existing_member is not None:
        raise HTTPException(status_code=409, detail="Already a member of this circle")

    session.add(CircleMember(circle_id=circle_id, kingdom_id=kingdom.id))
    await session.commit()


@router.post("/{circle_id}/wars", status_code=201)
async def declare_war(
    circle_id: uuid.UUID,
    payload: DeclareWarRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.scalar(
        select(Kingdom).where(Kingdom.player_id == player_id)
    )
    if kingdom is None:
        raise HTTPException(status_code=404, detail="No kingdom found for this player")

    member = await session.scalar(
        select(CircleMember).where(
            CircleMember.circle_id == circle_id,
            CircleMember.kingdom_id == kingdom.id,
        )
    )
    if member is None:
        raise HTTPException(status_code=403, detail="You are not a member of this circle")

    attacker = await session.get(Circle, circle_id)
    defender = await session.get(Circle, payload.defender_circle_id)
    if attacker is None or defender is None:
        raise HTTPException(status_code=404, detail="Circle not found")

    war = War(world_id=attacker.world_id, attacker_circle_id=attacker.id, defender_circle_id=defender.id)
    session.add(war)
    await session.commit()
    return {"war_id": war.id}

