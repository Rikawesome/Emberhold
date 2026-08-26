# The Long Dimming — Backend

Bloodline-based kingdom-building strategy game backend. FastAPI + Postgres (async
SQLAlchemy) + Redis + APScheduler.

Companion docs (design + architecture, written before this scaffold):
- `the-long-dimming-design-doc.md` — lore, bloodlines, resources, troop rosters, win condition
- `the-long-dimming-backend-architecture.md` — schema sketch and job breakdown
- `the-long-dimming-api-reference.md` — full endpoint contract, project structure, testing priorities

## Setup

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Start Postgres + Redis
docker compose up -d

# 3. Configure environment
cp .env.example .env
# edit .env — at minimum set JWT_SECRET to a real random string

# 4. Run migrations
alembic revision --autogenerate -m "initial schema"
alembic upgrade head

# 5. Seed reference data (five bloodlines + troop roster)
python -m scripts.seed_reference_data

# 6. Run the API
uvicorn app.main:app --reload
```

API docs (Swagger UI) will be at `http://localhost:8000/docs` once running.

## What's real vs. what's a TODO

This scaffold isn't a toy — auth, bloodline auto-assignment, resource production,
buildings, troop training, march creation, Circles, and the job scheduler all
actually run. What's intentionally left as a skeleton:

- **`app/services/combat.py`** — the row-locking/concurrency pattern is in place,
  but the per-ability math (Scorch, Chill, Bulwark, Foresight, Flash March, Breach,
  Aegis Core) isn't implemented. This is flagged as the highest-risk code in the
  project — see the testing section below before building it out.
- **`app/services/fade.py`** — income calculation is real; upkeep is a placeholder
  `0.0` until population/troops/buildings have a real cost formula.
- **World/map generation** — there's no procedural map generator yet.
  `claim_capital_tile()` in `app/services/kingdoms.py` creates tiles on the fly as a
  fallback so registration works standalone; a real generator is a separate task.
- **WebSocket auth** — `/ws/kingdoms/{id}` accepts connections unconditionally right
  now; needs a token check before it's safe to expose.
- **Kindling Shield check** — `check_kindling_shield()` in `app/services/marches.py`
  is a stub that always returns `False`; needs to actually compare against the
  target's owning kingdom's `kindling_shield_expires_at`.

Search the codebase for `TODO` to find every marked gap.

## Build order

Matches Section 12 of the API reference doc:

1. Models + initial migration (done — run `alembic revision --autogenerate` to generate it)
2. Auth + kingdom creation (done)
3. Production math (done)
4. Buildings + troops (done)
5. **Combat resolution + `resolve_marches` job — do this next.** Build and test in isolation.
6. Marches wired to the above (mostly done — needs garrison deduction on march creation, see TODO in `app/routers/marches.py`)
7. Circles/wars (done, minimal)
8. WebSocket auth (TODO)
9. Fade win condition — upkeep formula + actual win check (TODO)
10. Wire the Phaser frontend to these endpoints, replacing the demo files' procedural data

## Testing

```bash
# Needs a separate test database — never point this at your real dev DB, since the
# fixtures wipe it clean between runs.
createdb longdimming_test   # or: docker exec -it <postgres container> createdb -U longdimming longdimming_test
export TEST_DATABASE_URL="postgresql+asyncpg://longdimming:longdimming@localhost:5432/longdimming_test"
pytest
```

`tests/conftest.py` gives every test a real DB session wrapped in a transaction
that's rolled back afterward, so tests never leak state into each other, plus
factory helpers (`make_world`, `make_kingdom`, `make_tile`, etc.) for building test
data quickly.

`tests/test_production.py` and `tests/test_combat.py` are real, runnable tests, not
placeholders — including the concurrency test the API reference doc calls out
specifically: two simultaneous attacks against the same tile, run in genuinely
separate sessions via `asyncio.gather`, checked to confirm the row lock in
`resolve_march()` prevents both from reading the same pre-attack garrison value.

The combat tests currently check the *shape* of resolution (capture/repel,
ownership transfer, log written) against the placeholder power calculation in
`services/combat.py` — they'll need updating once real stat-weighted power lands,
but they pin down the behavior now so a refactor that breaks it gets caught
immediately. Add one new test per troop ability (Scorch, Chill, Bulwark, Foresight,
Flash March, Breach, Aegis Core) as each gets implemented, with hand-picked numbers
where you already know the right answer before running it.
