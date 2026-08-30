"""Deterministic combat resolution with troop abilities.

This module preserves the original combat lifecycle while adding the combat-time
abilities currently implemented by Emberhold.

Implemented here:
- Scorch (Cinder Archers): amplified attacker offense.
- Chill (Frost Slingers): reduces attacker offense when defending.
- Bulwark (Glacial Wardens): some defending troops survive a losing battle.
- Breach (Siege Engineers): bonus offense against built tiles.
- Aegis Core (Forgeguard): adjacent allied Forgeguards add defense.

Handled elsewhere:
- Foresight (Seers): scouting/intel effect.
- Flash March (Stormrunners): march travel-time effect.

Scorch and Chill are currently applied to the battle in which they participate.
Persistent "next engagement" effects would require additional tile state and a
database migration.
"""

import uuid
from datetime import datetime, timezone
from math import ceil
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kingdom import Kingdom
from app.models.march import CombatLog, March
from app.models.tile import Building, Tile, TileGarrison
from app.models.troop import TroopType



# ---------------------------------------------------------------------------
# Tunable ability values
# ---------------------------------------------------------------------------

SCORCH_OFFENSE_MULTIPLIER = 2.0
CHILL_OFFENSE_REDUCTION = 0.5
BULWARK_SURVIVAL_RATE = 0.5
BREACH_OFFENSE_MULTIPLIER = 1.5
AEGIS_ADJACENT_DEFENSE_BONUS = 2.0


# ---------------------------------------------------------------------------
# Baseline casualty helpers
# ---------------------------------------------------------------------------

def calculate_casualties(
    quantity: int,
    own_power: int,
    opposing_power: int,
) -> int:
    """Return deterministic casualties for one troop stack.

    Casualties are proportional to the ratio of opposing power to the stack's
    total relevant power. A ratio of 1.0 or greater destroys the whole stack.

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
    troop_list: List[Dict],
    power_key: str,
    opposing_power: int,
) -> List[int]:
    """Calculate deterministic casualties for each troop stack.

    The same casualty ratio is applied to every stack on a side. This preserves
    each stack's composition while avoiding random casualty selection.
    """
    total_power = sum(
        max(0, int(t["qty"])) * max(0, int(t[power_key]))
        for t in troop_list
    )

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


# ---------------------------------------------------------------------------
# Existing baseline helpers
# ---------------------------------------------------------------------------

async def get_fortification_bonus(
    session: AsyncSession,
    tile_id: uuid.UUID,
) -> int:
    """Return the existing numeric fortification contribution.

    Fortification level is currently the numeric defensive contribution used
    by the existing combat system.
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
    session: AsyncSession,
    troop_type_id: uuid.UUID | str,
) -> TroopType:
    troop_type = await session.get(
        TroopType,
        uuid.UUID(str(troop_type_id)),
    )

    if troop_type is None:
        raise ValueError(f"Troop type {troop_type_id} not found")

    return troop_type


async def _get_existing_combat_log(
    session: AsyncSession,
    march_id: uuid.UUID,
) -> CombatLog | None:
    return await session.scalar(
        select(CombatLog)
        .where(CombatLog.march_id == march_id)
        .order_by(CombatLog.resolved_at.desc())
    )


# ---------------------------------------------------------------------------
# Ability helpers
# ---------------------------------------------------------------------------

def _neighbor_coords(
    x: int,
    y: int,
) -> list[tuple[int, int]]:
    """Return orthogonally adjacent coordinates."""
    return [
        (x - 1, y),
        (x + 1, y),
        (x, y - 1),
        (x, y + 1),
    ]


async def _load_troop_types(
    session: AsyncSession,
    troop_type_ids: set[uuid.UUID],
) -> dict[uuid.UUID, TroopType]:
    """Load multiple troop types in one query."""
    if not troop_type_ids:
        return {}

    rows = (
        await session.execute(
            select(TroopType).where(
                TroopType.id.in_(troop_type_ids)
            )
        )
    ).scalars().all()

    return {troop.id: troop for troop in rows}


async def _aegis_core_defense_bonus(
    session: AsyncSession,
    target_tile: Tile,
) -> float:
    """Calculate Aegis Core defense from adjacent allied tiles.

    Only Forgeguards stationed on orthogonally adjacent tiles belonging to the
    same kingdom as the target contribute to the aura.
    """
    if target_tile.owner_kingdom_id is None:
        return 0.0

    coords = set(
        _neighbor_coords(
            target_tile.x,
            target_tile.y,
        )
    )

    neighbor_tiles = (
        await session.execute(
            select(Tile).where(
                Tile.world_id == target_tile.world_id,
                Tile.owner_kingdom_id == target_tile.owner_kingdom_id,
            )
        )
    ).scalars().all()

    adjacent_owned = [
        tile
        for tile in neighbor_tiles
        if tile.id != target_tile.id
        and (tile.x, tile.y) in coords
    ]

    if not adjacent_owned:
        return 0.0

    adjacent_ids = [tile.id for tile in adjacent_owned]

    garrisons = (
        await session.execute(
            select(TileGarrison).where(
                TileGarrison.tile_id.in_(adjacent_ids)
            )
        )
    ).scalars().all()

    if not garrisons:
        return 0.0

    troop_types = await _load_troop_types(
        session,
        {g.troop_type_id for g in garrisons},
    )

    bonus = 0.0

    for garrison in garrisons:
        troop_type = troop_types.get(garrison.troop_type_id)

        if (
            troop_type is not None
            and troop_type.ability_key == "aegis_core"
        ):
            bonus += (
                max(0, int(garrison.quantity))
                * AEGIS_ADJACENT_DEFENSE_BONUS
            )

    return bonus


# ---------------------------------------------------------------------------
# Combat resolution
# ---------------------------------------------------------------------------

async def resolve_march(
    session: AsyncSession,
    march_id: uuid.UUID,
) -> CombatLog | None:
    """Resolve a march based on its type exactly once.

    The march row is locked before checking its status. The target tile and its
    garrisons are then locked before calculations.

    No commit occurs here. The caller owns the transaction boundary.
    """

    # -----------------------------------------------------------------------
    # Lock the march first.
    #
    # This preserves the original idempotent/concurrency behavior.
    # -----------------------------------------------------------------------
    march = await session.scalar(
        select(March)
        .where(March.id == march_id)
        .with_for_update()
    )

    if march is None:
        raise ValueError(f"March {march_id} not found")

    if march.status != "marching":
        if march.status == "resolved":
            if march.march_type in ("reinforce", "return"):
                return None

            existing_log = await _get_existing_combat_log(
                session,
                march.id,
            )

            if existing_log is not None:
                return existing_log

        raise ValueError(
            f"March {march_id} is not in a resolvable state"
        )

    # -----------------------------------------------------------------------
    # Route non-combat march lifecycles (Reinforce / Return)
    # -----------------------------------------------------------------------
    if march.march_type in ("reinforce", "return"):
        destination_tile_id = march.target_tile_id


        target_tile = await session.scalar(
            select(Tile)
            .where(Tile.id == destination_tile_id)
            .with_for_update()
        )

        if target_tile is None:
            raise ValueError(
                f"Destination tile {destination_tile_id} not found"
            )

        for entry in march.troop_stack:
            troop_type_id = uuid.UUID(str(entry["troop_type_id"]))
            quantity = max(0, int(entry["quantity"]))

            if quantity <= 0:
                continue

            existing = await session.scalar(
                select(TileGarrison)
                .where(
                    TileGarrison.tile_id == target_tile.id,
                    TileGarrison.kingdom_id == march.kingdom_id,
                    TileGarrison.troop_type_id == troop_type_id,
                )
                .with_for_update()
            )

            if existing:
                existing.quantity += quantity
            else:
                session.add(
                    TileGarrison(
                        tile_id=target_tile.id,
                        kingdom_id=march.kingdom_id,
                        troop_type_id=troop_type_id,
                        quantity=quantity,
                    )
                )

        march.status = "resolved"
        march.version += 1
        return None

    # -----------------------------------------------------------------------
    # Lock target tile for Combat (Attack)
    # -----------------------------------------------------------------------
    target_tile = await session.scalar(
        select(Tile)
        .where(Tile.id == march.target_tile_id)
        .with_for_update()
    )

    if target_tile is None:
        raise ValueError(
            f"Target tile {march.target_tile_id} not found"
        )

    # -----------------------------------------------------------------------
    # Lock defender garrisons.
    # -----------------------------------------------------------------------
    defender_garrisons = (
        await session.execute(
            select(TileGarrison)
            .where(TileGarrison.tile_id == target_tile.id)
            .with_for_update()
        )
    ).scalars().all()

    # -----------------------------------------------------------------------
    # Load troop types.
    # -----------------------------------------------------------------------
    attacker_type_ids = {
        uuid.UUID(str(entry["troop_type_id"]))
        for entry in march.troop_stack
    }

    defender_type_ids = {
        garrison.troop_type_id
        for garrison in defender_garrisons
    }

    troop_types = await _load_troop_types(
        session,
        attacker_type_ids | defender_type_ids,
    )

    # -----------------------------------------------------------------------
    # Build attacker stacks.
    # -----------------------------------------------------------------------
    attacker_troops = []
    attacker_offense = 0.0
    has_breach = False

    for entry in march.troop_stack:
        troop_type_id = uuid.UUID(
            str(entry["troop_type_id"])
        )

        troop_type = troop_types.get(troop_type_id)

        if troop_type is None:
            raise ValueError(
                f"Troop type {entry['troop_type_id']} not found"
            )

        quantity = max(
            0,
            int(entry["quantity"]),
        )

        attack = max(
            0,
            float(troop_type.stats.get("attack", 0)),
        )

        defense = max(
            0,
            float(troop_type.stats.get("defense", 0)),
        )

        effective_attack = quantity * attack

        # Scorch
        if troop_type.ability_key == "scorch":
            effective_attack *= SCORCH_OFFENSE_MULTIPLIER

        # Breach is checked against the target building below.
        if troop_type.ability_key == "breach":
            has_breach = True

        attacker_offense += effective_attack

        attacker_troops.append(
            {
                "troop_type_id": troop_type.id,
                "qty": quantity,
                "attack": attack,
                "defense": defense,
                "ability_key": troop_type.ability_key,
                "effective_power": effective_attack,
            }
        )

    # -----------------------------------------------------------------------
    # Build defender stacks.
    # -----------------------------------------------------------------------
    defender_troops = []
    defender_offense = 0
    defender_defense = 0

    for garrison in defender_garrisons:
        quantity = max(
            0,
            int(garrison.quantity),
        )

        troop_type = troop_types.get(
            garrison.troop_type_id
        )

        if troop_type is None:
            raise ValueError(
                f"Troop type {garrison.troop_type_id} not found"
            )

        attack = max(
            0,
            float(troop_type.stats.get("attack", 0)),
        )

        defense = max(
            0,
            float(troop_type.stats.get("defense", 0)),
        )

        defender_offense += quantity * attack
        defender_defense += quantity * defense

        defender_troops.append(
            {
                "garrison": garrison,
                "troop_type_id": troop_type.id,
                "qty": quantity,
                "attack": attack,
                "defense": defense,
                "ability_key": troop_type.ability_key,
            }
        )

    # -----------------------------------------------------------------------
    # Existing fortification defense.
    # -----------------------------------------------------------------------
    fortification_bonus = await get_fortification_bonus(
        session,
        target_tile.id,
    )

    defender_defense_with_fortification = (
        defender_defense + fortification_bonus
    )

    # -----------------------------------------------------------------------
    # Chill
    #
    # Each defending Chill troop reduces effective attacker offense.
    # -----------------------------------------------------------------------
    chill_count = sum(
        troop["qty"]
        for troop in defender_troops
        if troop["ability_key"] == "chill"
    )

    chill_reduction = (
        chill_count * CHILL_OFFENSE_REDUCTION
    )

    attacker_offense = max(
        0.0,
        attacker_offense - chill_reduction,
    )

    # -----------------------------------------------------------------------
    # Breach
    #
    # Siege Engineers receive their bonus if the target has any building.
    # -----------------------------------------------------------------------
    breach_bonus = 0.0

    if has_breach:
        target_has_building = await session.scalar(
            select(Building.id)
            .where(Building.tile_id == target_tile.id)
            .limit(1)
        )

        if target_has_building is not None:
            breach_bonus = (
                attacker_offense
                * (BREACH_OFFENSE_MULTIPLIER - 1)
            )

            attacker_offense *= BREACH_OFFENSE_MULTIPLIER

    # -----------------------------------------------------------------------
    # Aegis Core
    # -----------------------------------------------------------------------
    aegis_bonus = await _aegis_core_defense_bonus(
        session,
        target_tile,
    )

    defender_defense_with_abilities = (
        defender_defense_with_fortification
        + aegis_bonus
    )

    # -----------------------------------------------------------------------
    # Resolve winner.
    #
    # Preserve the original strict comparison:
    # attacker offense > defender defense => attacker victory.
    # -----------------------------------------------------------------------
    attacker_wins = (
        attacker_offense
        > defender_defense_with_abilities
    )

    # -----------------------------------------------------------------------
    # Casualties.
    # -----------------------------------------------------------------------
    if attacker_wins:
        attacker_power_for_casualties = attacker_offense

        if attacker_power_for_casualties <= 0:
            attacker_casualties = [
                troop["qty"]
                for troop in attacker_troops
            ]
        else:
            attacker_casualties = [
                calculate_casualties(
                    quantity=troop["qty"],
                    own_power=int(
                        attacker_power_for_casualties
                    ),
                    opposing_power=int(
                        defender_defense_with_abilities
                    ),
                )
                for troop in attacker_troops
            ]

        defender_casualties = []

        for troop in defender_troops:
            if troop["ability_key"] == "bulwark":
                survivor_qty = round(
                    troop["qty"] * BULWARK_SURVIVAL_RATE
                )
                casualty_qty = max(
                    0,
                    troop["qty"] - survivor_qty,
                )
            else:
                casualty_qty = troop["qty"]

            defender_casualties.append(casualty_qty)

    else:
        attacker_casualties = [
            troop["qty"]
            for troop in attacker_troops
        ]

        if defender_defense_with_abilities <= 0:
            defender_casualties = [
                troop["qty"]
                for troop in defender_troops
            ]
        else:
            defender_casualties = [
                calculate_casualties(
                    quantity=troop["qty"],
                    own_power=int(defender_defense_with_abilities),
                    opposing_power=int(attacker_offense),
                )
                for troop in defender_troops
            ]


    # -----------------------------------------------------------------------
    # Calculate survivors.
    # -----------------------------------------------------------------------
    attacker_survivors = [
        max(
            0,
            troop["qty"] - attacker_casualties[i],
        )
        for i, troop in enumerate(attacker_troops)
    ]

    defender_survivors = [
        max(
            0,
            troop["qty"] - defender_casualties[i],
        )
        for i, troop in enumerate(defender_troops)
    ]

    # -----------------------------------------------------------------------
    # Write combat results.
    # -----------------------------------------------------------------------
    defender_kingdom_id = target_tile.owner_kingdom_id

    if (
        attacker_wins
        and target_tile.owner_kingdom_id != march.kingdom_id
    ):
        # Capture the tile.
        target_tile.owner_kingdom_id = march.kingdom_id
        target_tile.version += 1

        for garrison in defender_garrisons:
            await session.delete(garrison)

        for troop, survivor_qty in zip(
            attacker_troops,
            attacker_survivors,
        ):
            if survivor_qty <= 0:
                continue

            existing = await session.scalar(
                select(TileGarrison)
                .where(
                    TileGarrison.tile_id == target_tile.id,
                    TileGarrison.kingdom_id == march.kingdom_id,
                    TileGarrison.troop_type_id
                    == troop["troop_type_id"],
                )
                .with_for_update()
            )

            if existing:
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

        bulwark_retreat_stack = []
        for troop, survivor_qty in zip(defender_troops, defender_survivors):
            if troop["ability_key"] == "bulwark" and survivor_qty > 0:
                bulwark_retreat_stack.append({
                    "troop_type_id": str(troop["troop_type_id"]),
                    "quantity": survivor_qty,
                })

        if bulwark_retreat_stack and defender_kingdom_id:
            defender_kingdom = await session.get(Kingdom, defender_kingdom_id)
            if defender_kingdom and defender_kingdom.capital_tile_id:
                now = datetime.now(timezone.utc)
                retreat_march = March(
                    world_id=target_tile.world_id,
                    kingdom_id=defender_kingdom_id,
                    origin_tile_id=target_tile.id,
                    target_tile_id=defender_kingdom.capital_tile_id,
                    troop_stack=bulwark_retreat_stack,
                    march_type="return",
                    departure_at=now,
                    arrival_at=now,
                    status="marching",
                )
                session.add(retreat_march)
                await session.flush()
                await resolve_march(session, retreat_march.id)


        outcome = "captured"
        from app.services import production
        await production.recalculate_production(session, march.kingdom_id)
        if defender_kingdom_id is not None:
            await production.recalculate_production(session, defender_kingdom_id)


    elif attacker_wins:
        # Attacked an already-owned tile: reinforcement/victory without capture.
        for troop, survivor_qty in zip(
            attacker_troops,
            attacker_survivors,
        ):
            if survivor_qty <= 0:
                continue

            existing = await session.scalar(
                select(TileGarrison)
                .where(
                    TileGarrison.tile_id == target_tile.id,
                    TileGarrison.kingdom_id == march.kingdom_id,
                    TileGarrison.troop_type_id
                    == troop["troop_type_id"],
                )
                .with_for_update()
            )

            if existing:
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

        # Apply calculated casualties to existing defender garrisons (Fix 1)
        for troop, survivor_qty in zip(
            defender_troops,
            defender_survivors,
        ):
            garrison = troop["garrison"]

            if survivor_qty > 0:
                garrison.quantity = survivor_qty
            else:
                await session.delete(garrison)

        outcome = "victorious"

    else:
        for troop, survivor_qty in zip(
            defender_troops,
            defender_survivors,
        ):
            garrison = troop["garrison"]

            if survivor_qty > 0:
                garrison.quantity = survivor_qty
            else:
                await session.delete(garrison)

        outcome = "repelled"

    # -----------------------------------------------------------------------
    # Finalize march.
    # -----------------------------------------------------------------------
    march.status = "resolved"
    march.version += 1

    attacker_casualty_total = sum(
        attacker_casualties
    )

    defender_casualty_total = sum(
        defender_casualties
    )

    attacker_survivor_total = sum(
        attacker_survivors
    )

    defender_survivor_total = sum(
        defender_survivors
    )

    # -----------------------------------------------------------------------
    # Combat log.
    # -----------------------------------------------------------------------
    log = CombatLog(
        march_id=march.id,
        attacker_kingdom_id=march.kingdom_id,
        defender_kingdom_id=defender_kingdom_id,
        result={
            "outcome": outcome,

            "attacker_power": attacker_offense,
            "defender_power": defender_defense_with_abilities,

            "fortification_bonus": fortification_bonus,
            "defender_power_with_fortification":
                defender_defense_with_fortification,

            "aegis_bonus": aegis_bonus,
            "defender_power_with_abilities":
                defender_defense_with_abilities,

            "chill_reduction": chill_reduction,
            "breach_bonus": breach_bonus,

            "attacker_casualties":
                attacker_casualty_total,
            "defender_casualties":
                defender_casualty_total,

            "attacker_survivors":
                attacker_survivor_total,
            "defender_survivors":
                defender_survivor_total,
        },
        resolved_at=datetime.now(timezone.utc),
    )

    session.add(log)

    return log