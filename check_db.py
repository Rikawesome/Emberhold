import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://longdimming:longdimming@localhost:5432/longdimming_test"
)

async def main():
    engine = create_async_engine(URL)

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT key FROM bloodlines ORDER BY key")
        )
        rows = result.fetchall()

        print("Bloodlines currently in test DB:")
        for row in rows:
            print(row[0])

    await engine.dispose()

asyncio.run(main())
