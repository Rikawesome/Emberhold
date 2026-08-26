"""Run once after migrations, before any players register:

    python -m scripts.seed_reference_data

Seeds the five bloodlines and their troop rosters from app/data/.
"""

import asyncio

from sqlalchemy import select

from app.core.db import async_session
from app.data.bloodlines import BLOODLINES
from app.data.troop_types import TROOP_TYPES
from app.models.player import Bloodline
from app.models.troop import TroopType


async def seed() -> None:
    async with async_session() as session:
        existing = await session.scalar(select(Bloodline))
        if existing:
            print("Bloodlines already seeded — skipping.")
            return

        key_to_id = {}
        for data in BLOODLINES:
            bloodline = Bloodline(**data)
            session.add(bloodline)
            await session.flush()
            key_to_id[data["key"]] = bloodline.id

        for data in TROOP_TYPES:
            bloodline_key = data.pop("bloodline_key")
            session.add(TroopType(bloodline_id=key_to_id[bloodline_key], **data))

        await session.commit()
        print(f"Seeded {len(BLOODLINES)} bloodlines and {len(TROOP_TYPES)} troop types.")


if __name__ == "__main__":
    asyncio.run(seed())
