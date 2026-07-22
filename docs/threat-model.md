# Threat Model (STRIDE)

Scope: the Aegis gateway and agent runtime as implemented in this repository — the provider
router, the agent tool-calling loop, the four built-in tools, governance/guardrails,
multi-tenancy/RBAC, and cost tracking. Out of scope: physical infrastructure security of
whatever cloud/on-prem environment eventually hosts this (covered generically by standard
cloud-provider shared-responsibility guidance, not re-derived here), and the security of Ollama
itself as a piece of third-party software.

Two threats get dedicated depth because the product context calls them out explicitly:
**prompt injection** and **data exfiltration**. **Cost abuse** gets its own section as the third
explicitly-named concern.

---

## Spoofing

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| S1 | Caller impersonates another tenant's API key | Argon2-hashed secrets (`aegis.tenancy.api_keys`); raw secret shown once, never recoverable, only compared via `argon2.verify` | Key material leaked out-of-band (e.g. committed to a repo) is not detectable by Aegis itself — rotation (`ApiKeyStore.rotate`) is the remediation path, not prevention |
| S2 | Caller forges a `tenant_id` in a request body to act as another tenant | `tenant_id` is never read from the request body for scoping purposes — it comes exclusively from the authenticated `Principal` (see ADR-0005); `AgentRunIn`/`ChatCompletionIn` don't even have a `tenant_id` field | None identified within current scope |

## Tampering

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| T1 | **Prompt injection**: attacker-controlled text in the user message (or in tool output fed back into context) tries to override the system prompt or exfiltrate instructions | `aegis.governance.prompt_injection` heuristic screening (block action by default) on every request, at both the chat-completion and agent-run entry points | Pattern-matching has a false-negative rate against novel phrasings by construction (see ADR/module docstring) — this is a documented limitation, not a hidden one. A production deployment should layer an LLM-based classifier on top |
| T2 | Prompt injection via **tool output** (a `knowledge_base_search` result or an `http_get` response body contains injected instructions) | Tool results are appended as `role=tool` messages, distinct from `system`/`user` — a well-behaved model should not treat tool content as instructions, but Aegis does not currently re-screen tool *output* for injection patterns before it re-enters the conversation | **Open gap**, tracked here rather than silently accepted: re-running `screen_for_injection` on tool results before they're appended to `messages` in `AgentRuntime` would close this; not implemented in this sprint |
| T3 | Model-issued SQL tries to write/delete via `sql_query_readonly` | Statement validated: single statement only, must start `SELECT`/`WITH`, rejected if any DDL/DML keyword appears anywhere (catches data-modifying CTEs too), result wrapped in an outer `LIMIT` | Regex-based keyword rejection could in principle miss a Postgres-specific writable construct not yet enumerated; **defense in depth recommended**: run this tool's DB connection as a role with SELECT-only grants at the database level, not just application-level validation |
| T4 | Model-issued HTTP request via `http_get` reaches an internal/private service (SSRF) | https-only, domain allowlist (tenant policy, never model input), resolved IP checked against private/loopback/link-local/reserved ranges, redirects never auto-followed | DNS-rebinding TOCTOU between the allowlist check and the actual request (documented in the tool's own module docstring) — not closed in this sprint |
| T5 | Calculator tool used to execute arbitrary code via a crafted "expression" | AST-walking evaluator; only numeric literals, arithmetic operators, and an explicit function allowlist are ever evaluated — no `eval()`/`exec()` anywhere in the call path | None identified — this is the one path in the codebase deliberately built to have zero code-execution surface, verified by `tests/unit/test_tools_calculator.py` including an explicit `__import__(...)` rejection test |

## Repudiation

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| R1 | A tenant/actor denies having triggered a run or caused a guardrail action | Append-only `audit_log` records tenant, actor (API key id), action, model/provider, tokens, and which guardrail rule fired, for every governed action | `AuditStore` is insert-only *by convention* in application code; the database role used by the app is not yet restricted to INSERT-only at the grant level — see `docs/runbook.md` for the recommended follow-up |
| R2 | Agent-run outcome disputed ("the model never said that") | Every step (LLM call, tool call) is persisted with full input/output before the run proceeds; `TraceStore.replay()`/`AgentRuntime.replay()` reconstruct the run deterministically from storage alone | None identified within current scope |

## Information Disclosure

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| I1 | **Data exfiltration**: confidential/restricted data sent to a public cloud provider via misrouting | `policies/routing.yaml`'s first rule resolves `confidential`/`restricted` classification to `local` only, unconditionally — no rule ordering below it can override this without an explicit, reviewable YAML change (ADR-0002) | A caller mis-classifying its own data (marking confidential data as `internal`/`public`) bypasses this by construction — classification is caller-asserted, not independently verified by Aegis; independent content-based classification is a natural next step, not implemented |
| I2 | PII in the request body leaks to a provider or into logs | `aegis.governance.pii` redacts (default) or blocks (configurable per tenant, e.g. `legal_hold` policy) email/phone/credit-card (Luhn-validated)/SSN-like patterns before the request reaches any provider | Regex-based detection has real recall limits (see ADR-0003-adjacent reasoning applied to PII: deterministic and auditable over ML-based, at the cost of catching every possible PII format) |
| I3 | A provider or tool response echoes back a secret (API key, private key, JWT) that ended up in context | `aegis.governance.secrets` screens every response before it reaches the caller; blocks on any match | Pattern set is illustrative, not exhaustive — a novel credential format could slip through; this is the last line of defense, not the only one (secrets should not be in tool-accessible data stores in the first place) |
| I4 | Cross-tenant read of another tenant's agent-run trace (which may contain PII, tool outputs, business data) | Query-level tenant filtering (ADR-0005) — `viewer`/`developer` roles can never even observe that another tenant's run exists | `admin` role can read any tenant's data by design — a compromised admin credential has full read access; mitigated only by ADR-0005's key-rotation/audit trail, not prevented |
| I5 | Verbose error messages leak internal details (stack traces, connection strings) to API callers | Provider errors are normalized to `ProviderError` subtypes and mapped to clean HTTP status codes (502/503) before reaching the caller — see `routes_chat.py`/`routes_agent.py` | Not yet audited for every exception path (e.g. an unhandled exception in a route not wrapped by the provider-error handling could leak a FastAPI default 500 traceback in debug mode) — recommend `debug=False` and a catch-all exception handler before any real deployment |

## Denial of Service

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| D1 | A single tenant exhausts shared capacity (excessive requests, huge inputs) | `max_input_chars` per tenant guardrail policy rejects oversized input before it reaches a provider; per-tool timeouts (`Tool.timeout_s`) bound how long a single tool call can run | No request-rate limiting is implemented yet at the API layer — Redis is provisioned in the stack for this purpose (see stack description in README) but rate limiting itself is not wired up in this sprint; tracked as a gap, not silently omitted |
| D2 | A malfunctioning/malicious tool call loops or hangs, exhausting agent-run steps | `AgentConfig.max_steps` bounds the tool-calling loop; per-tool `asyncio.wait_for(..., timeout=tool.timeout_s)` bounds any single call | A pathological sequence of distinct tool calls, each individually fast, can still consume the full `max_steps`/`token_budget` — bounded, but not cheap; cost is capped by the budget enforcement (see Cost Abuse below) |
| D3 | One misbehaving cloud provider degrades the whole gateway's latency | Per-provider circuit breaker (ADR-0006) stops routing to a provider after repeated failures, failing over instead of retrying a known-broken candidate on every request | Circuit breaker state is per-process (see ADR-0006's accepted trade-off) — a multi-replica deployment converges independently, with a brief window of inconsistency across replicas |

## Elevation of Privilege

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| E1 | `viewer`/`developer` role calls an admin-only endpoint (API key management) | `require_role(Role.ADMIN)` dependency rejects with 403 before the handler body runs (`routes_admin.py`) | None identified within current scope |
| E2 | A tool call escalates privilege by reaching data/systems the calling tenant shouldn't access | `sql_query_readonly` operates on the same DB session as the rest of the request (no separate elevated credential); `http_get`'s allowlist is tenant/deployment configuration, never model-supplied | The SQL tool's blast radius is bounded by whatever the app's own DB role can see — see T3's recommended database-level SELECT-only grant as the actual privilege boundary, not just the regex validation |
| E3 | Rotated/revoked API key still grants access via a cached credential somewhere | `ApiKeyStore.authenticate` always checks `revoked_at IS NULL` against the current DB row — no caching of authentication decisions across requests | If a caching layer (e.g. Redis) is added in front of authentication later, revocation latency would need explicit handling; not a risk today because no such cache exists |

---

## Cost Abuse (explicitly called out, per product context)

Beyond the DoS framing above, cost abuse is its own category because Aegis is a *billing*
boundary, not just an availability one:

- **Runaway single agent run**: bounded by `AgentConfig.max_steps` and `token_budget` — a run
  that would exceed budget mid-flight is stopped (`status="budget_exceeded"`) rather than
  allowed to keep calling a (real or simulated) paid provider.
- **Tenant exceeding its monthly allowance**: `BudgetEnforcer` computes month-to-date spend
  (`CostEntry` rows) against the tenant's `monthly_budget_usd`; `routes_agent.py` hard-stops
  (`429`) new runs once `BudgetStatus.HARD_STOP` is reached, with a soft alert at 80% for
  earlier visibility. This check happens *before* the agent runtime is invoked, not after.
- **Gap**: budget enforcement checks *before* a run starts, using spend recorded from prior runs
  — it cannot pre-empt a single very expensive run from exceeding budget mid-run beyond the
  per-run `token_budget` ceiling. Tightening per-run budgets relative to the remaining monthly
  allowance (rather than a fixed default) is a reasonable follow-up, not implemented here.

## Summary of open gaps (tracked, not hidden)

1. Tool *output* is not re-screened for prompt injection before re-entering the conversation (T2).
2. SQL tool relies on application-level query validation; no database-level SELECT-only role
   enforcement is configured in this repository (T3, E2).
3. HTTP allowlist tool has a DNS-rebinding TOCTOU window (T4).
4. No API-level request-rate limiting is wired up yet, despite Redis being provisioned for it (D1).
5. `audit_log` insert-only-ness is an application convention, not yet a database grant (R1).

These are listed here deliberately, in the same document a reviewer would read to assess the
system's security posture — the point of a threat model is to make gaps visible, not to imply
there are none.
