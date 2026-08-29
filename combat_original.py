"""Baseline deterministic combat resolution.

This module intentionally contains no troop abilities.  Combat is resolved from
troop quantities, troop attack/defense stats, and the existing fortification
building state only.
"""

import uuid
from datetime import datetime, timezone
from math import ceil
from typing import Dict, List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.march import CombatLog, March
from app.models.tile import Building, Tile, TileGarrison
from app.models.troop import TroopType


def calculate_casualties(quantity: int, own_power: int, opposing_power: int) -> int:
    """Return deterministic casualties for one troop stack.

    Casualties are proportional to the ratio of opposing power to the stack's
    total relevant power.  A ratio of 1.0 or greater destroys the whole stack.
    ``ceil`` ensures a non-zero opposing force always causes at least one
    casualty in a non-zero stack.

    The result is always in [0, quantity].
    """
    quantity = max(0, int(quantity))
    own_power = max(0, int(own_power))
    opposing_power = max(0, int(opposing_power))

    if quantity == 0 or own_power == 0 or opposing_power == 0:
        return 0
    if opposing_power >= own_power:
        return quantity

    casualties = ceil(quantity * opposing_power / own_power)
    return min(quantity, max(0, casualties))


def calculate_stack_casualties(
    troop_list: List[Dict], power_key: str, opposing_power: int
) -> List[int]:
    """Calculate casualties for each troop stack deterministically.

    The same casualty ratio is applied to every stack on a side.  This preserves
    each stack's composition while avoiding random casualty selection.
    """
    total_power = sum(max(0, t["qty"]) * max(0, t[power_key]) for t in troop_list)
    if total_power <= 0:
        return [0] * len(troop_list)

    return [
        calculate_casualties(
            quantity=t["qty"],
            own_power=total_power,
            opposing_power=opposing_power,
        )
        for t in troop_list
    ]


async def get_fortification_bonus(session: AsyncSession, tile_id: uuid.UUID) -> int:
    """Return the existing numeric fortification contribution.

    The current repository has a ``fortification`` Building with a ``level``
    field, but no separate fortification-combat formula.  Level is therefore the
    only existing numeric value that can be used without inventing another
    mechanic.  A fortification contributes its level to defender defense.
    """
    building = await session.scalar(
        select(Building)
        .where(
            Building.tile_id == tile_id,
            Building.building_type == "fortification",
        )
        .with_for_update()
    )
    return max(0, int(building.level)) if building else 0


async def _load_troop_type(
    session: AsyncSession, troop_type_id: uuid.UUID | str
) -> TroopType:
    troop_type = await session.get(TroopType, uuid.UUID(str(troop_type_id)))
    if troop_type is None:
        raise ValueError(f"Troop type {troop_type_id} not found")
    return troop_type


async def _get_existing_combat_log(
    session: AsyncSession, march_id: uuid.UUID
) -> CombatLog | None:
    return await session.scalar(
        select(CombatLog)
        .where(CombatLog.march_id == march_id)
        .order_by(CombatLog.resolved_at.desc())
    )


async def resolve_march(session: AsyncSession, march_id: uuid.UUID) -> CombatLog:
    """Resolve one attack exactly once.

    The march row is locked before checking its status.  The target tile and its
    garrisons are then locked in a stable order.  No commit occurs here: callers
    own the transaction boundary, so any exception can roll the complete
    resolution back atomically.
    """
    march = await session.scalar(
        select(March).where(March.id == march_id).with_for_update()
    )
    if march is None:
        raise ValueError(f"March {march_id} not found")

    if march.status != "marching":
        if march.status == "resolved":
            existing_log = await _get_existing_combat_log(session, march.id)
            if existing_log is not None:
                return existing_log
        raise ValueError(f"March {march_id} is not in a resolvable state")

    target_tile = await session.scalar(
        select(Tile).where(Tile.id == march.target_tile_id).with_for_update()
    )
    if target_tile is None:
        raise ValueError(f"Target tile {march.target_tile_id} not found")

    defender_garrisons = (
        await session.execute(
            select(TileGarrison)
            .where(TileGarrison.tile_id == target_tile.id)
            .with_for_update()
        )
    ).scalars().all()

    attacker_troops = []
    attacker_offense = 0
    for entry in march.troop_stack:
        quantity = max(0, int(entry["quantity"]))
        troop_type = await _load_troop_type(session, entry["troop_type_id"])
        attack = max(0, int(troop_type.stats.get("attack", 0)))
        defense = max(0, int(troop_type.stats.get("defense", 0)))
        attacker_offense += quantity * attack
        attacker_troops.append(
            {
                "troop_type_id": troop_type.id,
                "qty": quantity,
                "attack": attack,
                "defense": defense,
            }
        )

    defender_troops = []
    defender_offense = 0
    defender_defense = 0
    for garrison in defender_garrisons:
        quantity = max(0, int(garrison.quantity))
        troop_type = await _load_troop_type(session, garrison.troop_type_id)
        attack = max(0, int(troop_type.stats.get("attack", 0)))
        defense = max(0, int(troop_type.stats.get("defense", 0)))
        defender_offense += quantity * attack
        defender_defense += quantity * defense
        defender_troops.append(
            {
                "garrison": garrison,
                "troop_type_id": troop_type.id,
                "qty": quantity,
                "attack": attack,
                "defense": defense,
            }
        )

    fortification_bonus = await get_fortification_bonus(session, target_tile.id)
    defender_defense_with_fortification = defender_defense + fortification_bonus

    # Strict comparison is retained from the existing baseline:
    # attacker offense > defender defense means attacker victory.
    attacker_wins = attacker_offense > defender_defense_with_fortification

    if attacker_wins:
        attacker_casualties = calculate_stack_casualties(
            attacker_troops, "attack", defender_defense_with_fortification
        )
        defender_casualties = [t["qty"] for t in defender_troops]
    else:
        attacker_casualties = [t["qty"] for t in attacker_troops]
        defender_casualties = calculate_stack_casualties(
            defender_troops, "defense", attacker_offense
        )

    attacker_survivors = [
        max(0, t["qty"] - attacker_casualties[i])
        for i, t in enumerate(attacker_troops)
    ]
    defender_survivors = [
        max(0, t["qty"] - defender_casualties[i])
        for i, t in enumerate(defender_troops)
    ]

    # A capture is only an ownership change when the target belongs to another
    # kingdom (or is neutral).  The march's troops were already deducted from
    # their origin garrison, so only survivors are inserted at the destination.
    defender_kingdom_id = target_tile.owner_kingdom_id

    if attacker_wins and target_tile.owner_kingdom_id != march.kingdom_id:
        target_tile.owner_kingdom_id = march.kingdom_id
        target_tile.version += 1

        # Existing target garrisons belong to the defeated side. Remove the rows
        # instead of leaving zero-quantity records behind.
        for garrison in defender_garrisons:
            await session.delete(garrison)

        for troop, survivor_qty in zip(attacker_troops, attacker_survivors):
            if survivor_qty <= 0:
                continue

            existing = await session.scalar(
                select(TileGarrison)
                .where(
                    TileGarrison.tile_id == target_tile.id,
                    TileGarrison.kingdom_id == march.kingdom_id,
                    TileGarrison.troop_type_id == troop["troop_type_id"],
                )
                .with_for_update()
            )
            if existing:
                # This is only a pre-existing destination garrison.  March
                # troops are not added to the origin again, so this cannot
                # duplicate the dispatched stack.
                existing.quantity += survivor_qty
            else:
                session.add(
                    TileGarrison(
                        tile_id=target_tile.id,
                        kingdom_id=march.kingdom_id,
                        troop_type_id=troop["troop_type_id"],
                        quantity=survivor_qty,
                    )
                )

        outcome = "captured"

    else:
        # Failed attacks preserve ownership. Defender survivors remain on the
        # tile, and zero-quantity rows are removed.
        for troop, survivor_qty in zip(defender_troops, defender_survivors):
            garrison = troop["garrison"]
            if survivor_qty > 0:
                garrison.quantity = survivor_qty
            else:
                await session.delete(garrison)

        outcome = "repelled"

    march.status = "resolved"
    march.version += 1

    attacker_casualty_total = sum(attacker_casualties)
    defender_casualty_total = sum(defender_casualties)
    attacker_survivor_total = sum(attacker_survivors)
    defender_survivor_total = sum(defender_survivors)

    log = CombatLog(
        march_id=march.id,
        attacker_kingdom_id=march.kingdom_id,
        defender_kingdom_id=defender_kingdom_id,
        result={
            "outcome": outcome,
            "attacker_power": attacker_offense,
            "defender_power": defender_defense,
            "fortification_bonus": fortification_bonus,
            "defender_power_with_fortification": defender_defense_with_fortification,
            "attacker_casualties": attacker_casualty_total,
            "defender_casualties": defender_casualty_total,
            "attacker_survivors": attacker_survivor_total,
            "defender_survivors": defender_survivor_total,
        },
        resolved_at=datetime.now(timezone.utc),
    )
    session.add(log)
    return log
