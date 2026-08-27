import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.kingdom import BloodlineStatus, Kingdom
from app.models.player import Bloodline
from app.models.tile import Tile, TileGarrison
from app.models.troop import TroopType
from app.schemas.kingdom import BloodlineStatusEntry, BloodlineStatusResponse
from app.schemas.tile import TileListResponse, TileResponse

router = APIRouter(prefix="/worlds", tags=["worlds"])


@router.get("/{world_id}/tiles", response_model=TileListResponse)
async def get_tiles_in_viewport(
    world_id: uuid.UUID,
    bbox: str = Query(..., description="x1,y1,x2,y2"),
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    x1, y1, x2, y2 = (int(v) for v in bbox.split(","))
    tiles = (
        await session.execute(
            select(Tile).where(
                Tile.world_id == world_id,
                Tile.x >= x1,
                Tile.x <= x2,
                Tile.y >= y1,
                Tile.y <= y2,
            )
        )
    ).scalars().all()

    # Foresight (Wardens): a Wardens kingdom, or any kingdom viewing its own tile,
    # sees the real per-troop-type breakdown instead of just a count. Look up the
    # requester's kingdom + bloodline once, not per tile.
    requester_kingdom = await session.scalar(
        select(Kingdom).where(Kingdom.player_id == player_id)
    )

    requester_is_wardens = False
    if requester_kingdom is not None:
        bloodline = await session.get(Bloodline, requester_kingdom.bloodline_id)
        requester_is_wardens = (
            bloodline is not None and bloodline.key == "wardens"
        )

    results = []

    for tile in tiles:
        garrison_total = await session.scalar(
            select(
                func.coalesce(func.sum(TileGarrison.quantity), 0)
            ).where(
                TileGarrison.tile_id == tile.id
            )
        )

        breakdown = None
        owns_tile = (
            requester_kingdom is not None
            and tile.owner_kingdom_id == requester_kingdom.id
        )

        if owns_tile or requester_is_wardens:
            rows = (
                await session.execute(
                    select(TileGarrison).where(
                        TileGarrison.tile_id == tile.id
                    )
                )
            ).scalars().all()

            if rows:
                troop_types = (
                    await session.execute(
                        select(TroopType).where(
                            TroopType.id.in_(
                                {r.troop_type_id for r in rows}
                            )
                        )
                    )
                ).scalars().all()

                key_by_id = {t.id: t.key for t in troop_types}
                breakdown = {}

                for r in rows:
                    key = key_by_id.get(
                        r.troop_type_id,
                        str(r.troop_type_id),
                    )
                    breakdown[key] = breakdown.get(key, 0) + r.quantity

        results.append(
            TileResponse(
                id=tile.id,
                x=tile.x,
                y=tile.y,
                terrain_type=tile.terrain_type,
                resonance_affinity=tile.resonance_affinity,
                owner_kingdom_id=tile.owner_kingdom_id,
                garrison_summary=int(garrison_total or 0),
                garrison_breakdown=breakdown,
            )
        )

    return TileListResponse(tiles=results)


@router.get(
    "/{world_id}/bloodlines",
    response_model=BloodlineStatusResponse,
)
async def get_bloodline_status(
    world_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(BloodlineStatus).where(
                BloodlineStatus.world_id == world_id
            )
        )
    ).scalars().all()

    bloodlines_by_id = {
        b.id: b
        for b in (await session.execute(select(Bloodline))).scalars().all()
    }

    entries = []

    for row in rows:
        bloodline = bloodlines_by_id.get(row.bloodline_id)

        if bloodline is None:
            continue

        if row.in_fade:
            status = "at_risk"
        elif row.total_income < row.total_upkeep * 1.2:
            status = "struggling"
        else:
            status = (
                "strong"
                if row.total_income > row.total_upkeep * 2
                else "stable"
            )

        entries.append(
            BloodlineStatusEntry(
                key=bloodline.key,
                status=status,
                total_income=row.total_income,
                total_upkeep=row.total_upkeep,
                in_fade=row.in_fade,
            )
        )

    return BloodlineStatusResponse(bloodlines=entries)
