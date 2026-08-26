from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.jobs import complete_queues, compute_bloodline_status, resolve_marches
from app.routers import auth, buildings, circles, kingdoms, marches, troops, worlds, ws

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Job cadence — see Section 4 of the backend architecture doc for what each does
    # and why. Tune intervals during playtesting; these are reasonable starting points.
    scheduler.add_job(resolve_marches.run, "interval", seconds=15, id="resolve_marches")
    scheduler.add_job(complete_queues.run, "interval", seconds=15, id="complete_queues")
    scheduler.add_job(compute_bloodline_status.run, "interval", minutes=5, id="compute_bloodline_status")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="The Long Dimming API", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(kingdoms.router)
app.include_router(worlds.router)
app.include_router(buildings.router)
app.include_router(troops.router)
app.include_router(marches.router)
app.include_router(circles.router)
app.include_router(ws.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
