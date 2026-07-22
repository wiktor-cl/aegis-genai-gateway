# Runbook

Operational procedures for Aegis. Written for the shape this repository actually is —
single Postgres instance, single API replica in `docker-compose.yml`, no live cloud provider
traffic (see [ADR-0003](adr/0003-local-first-contract-testing.md)) — not aspirational
procedures for infrastructure that doesn't exist here.

## Health checks

```bash
curl http://localhost:8000/health      # {"status": "ok", "environment": "..."}
curl http://localhost:8000/metrics     # Prometheus text format
docker compose exec api alembic current   # confirms migrations are applied (expect: 0002 (head))
```

If `/health` is unreachable but the container is running, check `docker compose logs api` —
the most common first-run cause is a missing/incorrect policy path env var (see
`docker-compose.yml`'s `AEGIS_*_POLICY_PATH` block) or `alembic upgrade head` never having been
run.

## Incident: extended provider outage (Bedrock or Foundry)

Referenced from `knowledge_base_docs.json` (kb-005) and
[ADR-0006](adr/0006-per-provider-circuit-breaker.md#Powiązane). The per-provider circuit breaker
(`src/aegis/providers/circuit_breaker.py`) already stops routing to a provider after 5
consecutive failures and fails over automatically — this procedure is for when you want to
**proactively** stop sending any traffic to a degraded provider ahead of it tripping the
breaker on its own, or when the outage is confirmed to be extended (hours, not minutes) and you
want a paper trail rather than relying on transient breaker state.

1. Confirm the outage isn't Aegis-side: `curl` the provider's own status page, check
   `docker compose logs api` for the specific `ProviderUnavailableError`/`ProviderTimeoutError`
   messages (`src/aegis/providers/local_provider.py`,`bedrock_provider.py`,`foundry_provider.py`
   all raise these with the upstream status code/message included).
2. Edit `policies/routing.yaml`: for the affected rule (e.g.
   `internal-prefers-local-falls-back-to-cloud`), remove the degraded provider from `allow`, or
   reorder so `local` is first (it usually already is — see the rule's own comment: confidential
   data always resolves to `local` only, unconditionally, so this step only matters for
   `internal`/`public` rules).
3. Restart the API so it picks up the change (`ProviderRouter` is built once at startup —
   `build_router()` in `src/aegis/main.py` — there is no hot-reload): `docker compose restart
   api`.
4. Record the change: this is a YAML edit + redeploy, not a database change, so it's naturally
   visible in `git log policies/routing.yaml` — no separate incident log needed for *what*
   changed, only *why* (commit message).
5. Revert the same way once the provider's status page confirms recovery.

## Incident: a tenant is hard-stopped on budget

`POST /v1/agents/run` returns `429` once a tenant's month-to-date spend reaches 100% of
`monthly_budget_usd` (see [cost-model.md](cost-model.md)). This is expected, working behavior,
not a bug — the runbook here is about verifying it and, if warranted, granting relief:

1. Confirm: `GET /v1/cost/report?tenant_id=<id>` (admin key) or the Console Dashboard.
2. If the spend is legitimate and the tenant needs a higher limit: edit
   `policies/tenants.yaml`'s `monthly_budget_usd` for that tenant and restart the API
   (`TenantRegistry.from_yaml` is also loaded once at startup, same as the routing policy).
3. If the spend looks anomalous (a bug in a caller's retry loop, a leaked API key being
   abused): check `GET /v1/agents/runs?tenant_id=<id>` for a burst of runs in a short window,
   and consider `POST /v1/admin/api-keys/{key_id}/revoke` on the specific key rather than
   raising the whole tenant's budget.

## Incident: guardrail false positive blocking legitimate traffic

`GuardrailPipeline` (`src/aegis/governance/pipeline.py`) is regex-based by design (see
[ADR-0003](adr/0003-local-first-contract-testing.md)'s sibling reasoning applied to guardrails —
deterministic and auditable over ML-based). A legitimate request matching, e.g., the
prompt-injection pattern `ignore (all |any )?(previous|above|prior) instructions` will be
blocked.

1. Get the exact matched text from the `audit_log` (`action="guardrail_request"`, `policy_rule`,
   `detail.matches` — queryable via `sql_query_readonly` in an agent run, or directly against
   Postgres).
2. If the pattern is genuinely too broad, narrow the regex in
   `src/aegis/governance/prompt_injection.py` (or `pii.py`/`secrets.py` for the other
   guardrails) — this is a code change, goes through the normal PR + CI +
   [eval-gate](../eval/README.md) process like any other, specifically *because* a guardrail
   regression is exactly the kind of change the eval-gate exists to catch
   (`eval/cases/guardrails.yaml` has explicit false-positive cases for this reason).
3. If the tenant's policy is simply stricter than this caller needs (e.g. `legal_hold`'s
   `pii.action: block` instead of `redact`), the fix is a `policies/tenants.yaml` change
   (different `guardrail_policy` for that tenant), not a regex change.

## Database migrations

Migrations are a **separate, explicit step** (`docker compose exec api alembic upgrade head`),
never baked into the API container's startup — see the root README's "Run it" section. This is
deliberate: if the API ever scales to multiple replicas, every replica running migrations at
container-start would race on `CREATE TABLE`/`ALTER TABLE` against the same database. Run
migrations once, from one place, before starting (or restarting) the API replicas.

```bash
docker compose exec api alembic current        # what's applied now
docker compose exec api alembic upgrade head   # apply pending migrations
docker compose exec api alembic downgrade -1   # roll back one revision, if needed
```

## Backup and retention

One Postgres instance holds `agent_runs`/`agent_steps`, `audit_log`, `cost_entries`, and
`api_keys` — see [ADR-0004](adr/0004-postgres-for-audit-cost-and-trace.md) for why one database
rather than one per concern. Concretely:

- **Backup**: standard `pg_dump`/point-in-time-recovery for the single `aegis` database — no
  multi-database coordination needed for a consistent snapshot.
- **Retention differs per table**, which a single database does *not* give you for free:
  - `audit_log` — compliance-driven, long retention (this repo does not set a TTL; a real
    deployment should decide a real number based on its own compliance requirements).
  - `agent_steps` — `knowledge_base_docs.json` (kb-008) documents a 90-day retention target for
    full step traces. Not automated in this repository (no scheduled job exists); a real
    deployment would add a periodic delete job (`DELETE FROM agent_steps WHERE started_at <
    now() - interval '90 days'`) or table partitioning by month, either logging engine.
  - `cost_entries` — needed for month-to-date budget math (`CostTracker.month_to_date_usd`
    only ever queries the current month), so anything older than a couple of months is safe to
    archive/delete on the same cadence as `agent_steps`.

## API key rotation and database credentials

- **API keys** (per-tenant, used for `Authorization: Bearer <key_id>.<secret>` — the only auth
  mechanism actually implemented; see `aegis.tenancy.rbac`): rotate via
  `POST /v1/admin/api-keys/{key_id}/rotate` (admin role) — this revokes the old key and mints a
  new one in the same call, `aegis.tenancy.api_keys.ApiKeyStore.rotate`. The Console's Admin
  page wraps this endpoint directly.
- **Database credentials** (`AEGIS_DATABASE_URL`, the Postgres connection string the API
  authenticates to Postgres with): rotation is **manual and out-of-band**, deliberately not
  automated — see `infra/terraform/secrets.tf`'s comment on why `CKV2_AWS_57` (automatic
  Secrets Manager rotation) is skipped: AWS's built-in Postgres rotation template assumes
  RDS/Aurora, and this project's `docker-compose.yml` runs plain `postgres:16-alpine`. To
  rotate: create the new Postgres role/password, update the secret in Secrets Manager/Key Vault
  (or `.env` locally), restart the API so it picks up the new `AEGIS_DATABASE_URL` (there is no
  hot-reload of settings), then revoke the old Postgres role once the restart is confirmed
  healthy (`GET /health`).

**Note on `AEGIS_JWT_SIGNING_KEY`/`AEGIS_JWT_ALGORITHM`**: these settings exist in
`src/aegis/config.py` and `python-jose` is a project dependency, but no code path in this
repository currently issues or verifies a JWT — all authentication today is the API-key scheme
above. These settings are reserved for a planned JWT-based auth mode, not a currently-active
one; treat any reference to "JWT auth" elsewhere as forward-looking, not a description of
what's running.

## Reading the audit log for an incident

`audit_log` (`src/aegis/governance/audit.py`) is meant to be insert-only — application code
never updates or deletes a row. **This is enforced by convention today, not by a database
grant** (see `docs/threat-model.md`, R1) — a real deployment should additionally restrict the
database role the API runs as to `INSERT`-only on this specific table, so a future code change
or a compromised credential can't silently rewrite history. Not configured in this repository
(no database-role-per-table setup exists in `docker-compose.yml`/Terraform/Bicep here); tracked
as an explicit gap, not a hidden one.

To investigate an incident, query `audit_log` filtered by `tenant_id`/`run_id`/`action`/time
range — every guardrail hit, every `agent_run`, every admin key operation, and the budget
hard-stop event all go through this one table, so a single query usually answers "what
happened, to whom, and which policy rule fired."
