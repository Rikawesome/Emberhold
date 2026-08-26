import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.tile import Tile, TileGarrison
from app.schemas.kingdom import BloodlineStatusResponse, BloodlineStatusEntry
from app.schemas.tile import TileListResponse, TileResponse
from sqlalchemy import func

router = APIRouter(prefix="/worlds", tags=["worlds"])


@router.get("/{world_id}/tiles", response_model=TileListResponse)
async def get_tiles_in_viewport(
    world_id: uuid.UUID,
    bbox: str = Query(..., description="x1,y1,x2,y2"),
    session: AsyncSession = Depends(get_session),
):
    x1, y1, x2, y2 = (int(v) for v in bbox.split(","))
    tiles = (
        await session.execute(
            select(Tile).where(
                Tile.world_id == world_id,
                Tile.x >= x1, Tile.x <= x2,
                Tile.y >= y1, Tile.y <= y2,
            )
        )
    ).scalars().all()

    results = []
    for tile in tiles:
        garrison_total = await session.scalar(
            select(func.coalesce(func.sum(TileGarrison.quantity), 0)).where(TileGarrison.tile_id == tile.id)
        )
        results.append(
            TileResponse(
                id=tile.id, x=tile.x, y=tile.y, terrain_type=tile.terrain_type,
                resonance_affinity=tile.resonance_affinity, owner_kingdom_id=tile.owner_kingdom_id,
                garrison_summary=int(garrison_total or 0),
            )
        )
    return TileListResponse(tiles=results)


@router.get("/{world_id}/bloodlines", response_model=BloodlineStatusResponse)
async def get_bloodline_status(world_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """TODO: read from the bloodline_status table (populated by the
    compute_bloodline_status job) instead of returning a placeholder.
    """
    return BloodlineStatusResponse(bloodlines=[])
