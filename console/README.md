# Aegis Console

Operator console for the Aegis gateway: cost dashboard, trigger/inspect agent runs (full
step-by-step trace), and admin API key management. React + TypeScript + Tailwind (v4), built
with Vite.

## Running it

The console talks to the Aegis API through a dev-server proxy (`/api/*` → `http://localhost:8000`,
see `vite.config.ts`) so no CORS configuration is needed on the FastAPI side.

```bash
# 1. bring up the API (from the repo root)
docker compose up --build
docker compose exec api alembic upgrade head   # first run only — creates the schema

# 2. bootstrap the first admin API key (from the repo root, host Python env)
AEGIS_DATABASE_URL=postgresql+asyncpg://aegis:aegis@localhost:5432/aegis \
    python scripts/seed.py --tenant-id acme-support --role admin
# paste the printed "key_id.secret" token into the console's login screen

# 3. run the console
cd console
npm install
npm run dev
```

## Why no generated API client

The API surface is small (5 endpoints) and stable; `src/api/types.ts` mirrors the Pydantic
models by hand. Past that size, generating a client from the OpenAPI schema (already served at
`/docs`/`/openapi.json` via FastAPI) would be the better trade-off — not done here to avoid a
codegen step for a surface this small.

## Auth model

There is no "who am I" endpoint — the console never learns its own role in advance. This is
intentional, not a gap: RBAC is enforced at the API/query layer (see
[ADR-0005](../docs/adr/0005-rbac-enforced-at-query-layer.md)), so the console doesn't need to
know the caller's role to be secure, only to decide what to *show*. A non-admin simply gets a
403 from the Admin page's actions, exactly as the API would for any other caller.

## Scripts

- `npm run dev` — dev server with API proxy
- `npm run build` — type-check (`tsc -b`) then production build
- `npm run lint` — oxlint
