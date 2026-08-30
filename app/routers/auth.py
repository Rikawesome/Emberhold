import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.core.security import create_access_token, hash_password, verify_password

from app.models.player import Player
from app.schemas.player import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse
from app.services import kingdoms as kingdom_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)):
    existing = await session.scalar(select(Player).where(Player.username == payload.username))
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    player = Player(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    session.add(player)
    await session.flush()  # get player.id before creating the kingdom

    # Auto-assign bloodline (weighted toward the least-populated) and create the
    # player's first kingdom + capital tile. See services/kingdoms.py.
    await kingdom_service.create_starter_kingdom(session, player.id)

    await session.commit()
    return RegisterResponse(player_id=player.id, username=player.username)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
    player = await session.scalar(select(Player).where(Player.username == payload.username))
    if not player or not verify_password(payload.password, player.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_access_token(subject=str(player.id))
    return TokenResponse(access_token=token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    player_id: uuid.UUID = Depends(get_current_player_id),
):
    """Issue a fresh JWT token for an active session."""
    token = create_access_token(subject=str(player_id))
    return TokenResponse(access_token=token)

