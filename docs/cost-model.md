# Cost model

How Aegis computes, tracks, and enforces cost — and, just as important, which numbers here are
real and which are simulated. See the root README's zero-cost constraint first if you haven't:
this section explains what "simulated cost" means concretely.

## Real vs. simulated

- **`LocalProvider` (Ollama) costs are real: $0.** `policies/pricing.yaml`'s `local` entry is
  `input_per_1k_usd: 0.0, output_per_1k_usd: 0.0` — not a placeholder, an accurate price, since
  Ollama has no per-token billing.
- **Bedrock/Foundry prices in `policies/pricing.yaml` are real *list* prices**, used to compute
  what a request *would have cost* had it actually gone to that provider. No real invoice was
  ever generated from these numbers in this repository — see
  [ADR-0003](adr/0003-local-first-contract-testing.md): those providers are never called live
  here, only against recorded fixtures in `tests/contract/`.

## How a cost entry is produced

Every provider call — real (`local`) or simulated (`bedrock`/`foundry`) — goes through
`CostTracker.record()` (`src/aegis/cost/tracker.py`) exactly once, from two call sites:

- `routes_chat.py`, after a successful `/v1/chat/completions` call.
- `AgentRuntime.run()` (`src/aegis/agent/runtime.py`), after every LLM step inside an agent run
  (an agent run can accumulate several `CostEntry` rows, one per step, not one per run).

```
cost_usd = (input_tokens / 1000) * pricing.input_per_1k_usd
         + (output_tokens / 1000) * pricing.output_per_1k_usd
```

`PricingTable.price_for()` falls back to `policies/pricing.yaml`'s `fallback` entry
(`$0`/`$0`) for any provider/model pair not explicitly listed — a request never fails or
raises just because a price is missing; it's recorded as free and the gap is visible in the
data (a `CostEntry` with an unexpectedly-low cost for a real provider is itself the signal
something needs updating in `pricing.yaml`).

## Why `float`, not a fixed-point/decimal type

Every `cost_usd` value here is a Python `float` (`CostEntry.cost_usd: Mapped[float]`), not
`Decimal`. This is a deliberate scope decision, not an oversight: Aegis's cost tracking is a
**usage-estimation and budget-enforcement signal**, not an invoicing system — nothing here
generates a bill a customer pays. A system that did (see the sibling portfolio project
`meterflow`, which does exactly that) would need `Decimal`/`BigDecimal` arithmetic and
cent-accurate rounding rules throughout; pulling that rigor into Aegis without an actual billing
use case behind it would be complexity with no corresponding requirement.

## Budget enforcement

`BudgetEnforcer.check()` (`src/aegis/cost/budgets.py`) computes month-to-date spend
(`CostTracker.month_to_date_usd()`, summing `cost_entries` since the 1st of the current month
in UTC) against the tenant's `monthly_budget_usd` (`policies/tenants.yaml`):

| Spend vs. budget | `BudgetStatus` | What happens |
|---|---|---|
| < 80% | `ok` | Nothing |
| ≥ 80%, < 100% | `soft_alert` | Surfaced in the cost report (`GET /v1/cost/report`, console Dashboard); requests are **not** blocked |
| ≥ 100% | `hard_stop` | `POST /v1/agents/run` returns `429` **before** the agent runtime is invoked — no provider call, no further cost, an `audit_log` entry (`action="budget_hard_stop"`) is recorded |

The 80% threshold is `BudgetEnforcer.__init__`'s `soft_alert_threshold` parameter, not
hardcoded — a caller could construct a stricter enforcer per tenant if a future requirement
needed it; nothing does today.

## Known gap: mid-run overrun

Budget is checked **once, before** an agent run starts. A single expensive run is still bounded
by its own `AgentConfig.token_budget` (a per-run ceiling, separate from the monthly budget), but
a tenant sitting at 79% of its monthly budget can still start a run that pushes it past 100% —
enforcement doesn't (and structurally can't, without pausing mid-stream) preempt a run once
admitted. This mirrors the same gap documented in `docs/threat-model.md`'s "Cost Abuse" section;
listed here again because it's a cost-model property, not only a security one.

## Where this data goes

- `GET /v1/cost/report` — the tenant's month-to-date spend, budget, and status (see
  `src/aegis/api/routes_cost.py`); a non-admin can only ever see their own tenant's report.
- Console **Dashboard** page (`console/src/pages/DashboardPage.tsx`) renders exactly this
  endpoint's response as a progress bar.
- Every `agent_run`'s per-step cost is visible in the Console **Runs** page's step trace view
  (`total_input_tokens`/`total_output_tokens` per step — cost itself isn't repeated per step in
  the trace API today, only tokens; deriving cost from tokens + `policies/pricing.yaml` client-side
  is a reasonable follow-up, not implemented).
