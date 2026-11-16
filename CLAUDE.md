<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Auto-Ontology

Full-stack repo: Next.js frontend (`/frontend`) + FastAPI backend (`/auto_ontology`).

This file is for **Auto-Ontology maintainers**. User/partner agent skills live in
`skills/` — start at [`AGENTS.md`](./AGENTS.md).

## Dev Commands

Backend commands run from the repo root:

| Command | Description |
|---|---|
| `uv run uvicorn auto_ontology.server.__main__:create_app --factory --reload --host 127.0.0.1 --port 3001` | Start FastAPI on :3001 with hot reload |
| `uv run python -m auto_ontology.server` | Start FastAPI on :3001 without reload (what the container runs) |
| `uv run python -m auto_ontology.ingestion_service` | Start the ingestion service on :3002 |

The app factory is `create_app()` in `auto_ontology/server/__main__.py` — there is no
`auto_ontology/server/main.py`.

### Windows: one command for the whole stack

Only Postgres runs in Docker; the backend, ingestion service and frontend run from
source with hot reload, started in dependency order and health-gated at each step.

| Command | Description |
|---|---|
| `.\dev_tools\start-dev.ps1` | Postgres → backend (:3001) → ingestion (:3002) → frontend (:3010). Idempotent; `-Force` restarts everything |
| `.\dev_tools\smoke-test.ps1` | Read-only end-to-end check (health, sign-in, pages, ERD canvas) |
| `.\dev_tools\stop-dev.ps1` | Stop the three processes; Postgres keeps running (`-IncludePostgres` stops it too) |

Logs land in `logs\` (git-ignored). Prefer this over starting uvicorn by hand: two
reloaders on :3001 is the most common "it does not work" report.

### Where the docs are

`docs/README.md` indexes them. Read `docs/architecture/project-review.md` before
any structural refactor — it records the current layering, the known debt and the
agreed phase order.

## Frontend Rules

In [`frontend/CLAUDE.md`](./frontend/CLAUDE.md), loaded when working under `frontend/`.

## Backend Rules

- **The store is Postgres.** `auto_ontology/dal/` talks to it through SQLAlchemy (Core expressions and ORM entities — see the next bullet); `auto_ontology/dal/schema.py` is the single source of truth for the schema and `auto_ontology/dal/session.py` owns the pooled engine. Schema changes go through Alembic — `uv run alembic revision --autogenerate -m "..."` — never by hand-editing a migration that has been applied. Several column types and constraints are deliberate and non-obvious — read the comments in `schema.py` before changing a table.
- **ORM or Core, by job.** `auto_ontology/dal/models.py` maps every table in `schema.py` to an ORM entity (`__table__ = schema.zone`, so there is still exactly one DDL definition). Use the ORM for entity work — `session.get(Zone, id)`, `select(Zone)`, `zone.targets`, `db.add`/`db.delete` — and keep Core for set work: joins, `DISTINCT`, unions, `INSERT ... ON CONFLICT`. Open a session with `with orm_session() as db:`; inside `write_transaction()` it borrows that connection, so the two styles commit together. `dal/zones.py` is the worked example.
- **Chinese table comments live in `schema.py: TABLE_COMMENTS`.** They become `COMMENT ON TABLE` in Postgres via a migration, and `alembic check` treats them as part of the schema — change one and you must generate a migration. Per-column explanations live in `dal/models.py` as Chinese annotations plus docstrings.
- **Formatting/Linting**: Run `uv run ruff check auto_ontology/` and `uv run ruff format auto_ontology/` from repo root before committing.
- **Dependencies**: Managed with `uv`. Add dependencies via `uv add`, not pip. Do not edit `pyproject.toml` manually for deps.
- **API prefix**: All routes under `/api/`. Routes live in `auto_ontology/server/datasources/router.py`, orchestration in `auto_ontology/server/datasources/service.py`.
- **Type hints**: Required on all function signatures.
- **Exception handlers**: Use plain `def` (not `async def`) for `@app.exception_handler` functions. They perform no async I/O, so synchronous handlers are preferred.

## Git

- Commit messages: concise imperative style, no `Co-Authored-By` trailers.
- Branch from `main`.

### Opening a PR

**A PR is not done until every GitHub Actions workflow passes.** After opening
one, poll `gh pr checks <number>` until no check is pending, then fix whatever
failed and push again — repeat until the run is green. Report the final state
honestly; do not hand back a PR with unexamined or failing checks.

Run these locally first — they are the same gates CI applies, and catching a
failure here costs seconds instead of a CI round-trip:

| Check | Command | Catches |
|---|---|---|
| Ruff | `uv run ruff check auto_ontology/ && uv run ruff format --check auto_ontology/` | Backend lint/format |
| Pytest | `uv run pytest auto_ontology dev_tools -q` | Backend tests |
| OpenAPI | `uv run python -m dev_tools.generate_backend_openapi` | **Stale `docs/openapi/*.json`** |
| Frontend | `cd frontend && npx prettier --check . && pnpm lint && pnpm test && pnpm build` | Format, lint, unit tests, build |

The OpenAPI one is the easy one to miss: `docs/openapi/backend.json` and
`ingestion.json` are committed, and the spec embeds each route's **docstring**.
Editing a docstring on any `@router` handler — not just changing a signature or
model — makes the committed spec stale and fails "Backend spec is up to date".
Regenerate and commit the result whenever a route's code or docs change.
