import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


async def get_current_player_id(
    token: str = Depends(oauth2_scheme),
) -> uuid.UUID:
    player_id = decode_access_token(token)
    if player_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return uuid.UUID(player_id)


DbSession = Depends(get_session)
