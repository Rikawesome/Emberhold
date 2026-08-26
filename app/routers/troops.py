import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_player_id
from app.models.kingdom import Kingdom
from app.models.tile import Tile
from app.models.troop import TrainingQueue, TroopType
from app.schemas.troop import TrainRequest, TrainingQueueEntry
from app.services import production

router = APIRouter(prefix="/kingdoms/{kingdom_id}", tags=["troops"])

TRAIN_MINUTES_PER_UNIT = 5  # placeholder — tune during playtesting, likely tier-dependent


@router.post("/tiles/{tile_id}/train", response_model=TrainingQueueEntry, status_code=202)
async def train_troops(
    kingdom_id: uuid.UUID,
    tile_id: uuid.UUID,
    payload: TrainRequest,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)
    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(status_code=403, detail="Not your kingdom")

    tile = await session.get(Tile, tile_id)
    if tile is None or tile.owner_kingdom_id != kingdom_id:
        raise HTTPException(status_code=403, detail="Tile not owned by this kingdom")

    troop_type = await session.get(TroopType, payload.troop_type_id)
    if troop_type is None:
        raise HTTPException(status_code=422, detail="Unknown troop type")

    # Signature troops require the matching bloodline — see design doc Section 4.
    if troop_type.tier == "signature" and troop_type.bloodline_id != kingdom.bloodline_id:
        raise HTTPException(status_code=422, detail="This signature troop isn't available to your bloodline")

    total_costs = {res: amt * payload.quantity for res, amt in troop_type.resource_costs.items()}
    try:
        await production.spend(session, kingdom_id, total_costs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    now = datetime.now(timezone.utc)
    completes_at = now + timedelta(minutes=TRAIN_MINUTES_PER_UNIT * payload.quantity)
    entry = TrainingQueue(
        kingdom_id=kingdom_id, tile_id=tile_id, troop_type_id=troop_type.id,
        quantity=payload.quantity, started_at=now, completes_at=completes_at,
    )
    session.add(entry)
    await session.commit()

    return TrainingQueueEntry(
        queue_id=entry.id, tile_id=tile_id, troop_type=troop_type.key,
        quantity=payload.quantity, completes_at=completes_at,
    )


@router.get("/training-queue", response_model=list[TrainingQueueEntry])
async def get_training_queue(
    kingdom_id: uuid.UUID,
    player_id: uuid.UUID = Depends(get_current_player_id),
    session: AsyncSession = Depends(get_session),
):
    kingdom = await session.get(Kingdom, kingdom_id)
    if kingdom is None or kingdom.player_id != player_id:
        raise HTTPException(status_code=403, detail="Not your kingdom")

    rows = (
        await session.execute(
            select(TrainingQueue, TroopType)
            .join(TroopType, TroopType.id == TrainingQueue.troop_type_id)
            .where(TrainingQueue.kingdom_id == kingdom_id, TrainingQueue.status == "in_progress")
        )
    ).all()

    return [
        TrainingQueueEntry(queue_id=q.id, tile_id=q.tile_id, troop_type=t.key, quantity=q.quantity, completes_at=q.completes_at)
        for q, t in rows
    ]
