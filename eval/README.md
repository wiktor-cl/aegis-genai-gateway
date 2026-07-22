# Aegis eval harness

58 hand-authored cases across 5 categories, run as a merge gate in CI
(`.github/workflows/ci.yml`, job `eval-gate`). See
[ADR-0008](../docs/adr/0008-eval-gate-golden-fixtures.md) for why this is
scripted only at the `LLMProvider` boundary — the tool-calling loop,
guardrails, and every tool are real code, exercised for real.

## Categories

| File | What it checks |
|---|---|
| `cases/chat_quality.yaml` | Single-shot chat responses: format/instruction-following, refusal correctness |
| `cases/tool_use.yaml` | Each of the 4 tools (`calculator`, `knowledge_base_search`, `sql_query_readonly`, `http_get`) invoked successfully through the real agent loop |
| `cases/tool_safety.yaml` | Defense-in-depth rejections (SQL DDL/multi-statement, calculator code-injection, HTTP SSRF/scheme, unknown tool, bad arguments) — see docs/threat-model.md T3-T5 |
| `cases/guardrails.yaml` | PII redact vs. block per tenant policy, prompt-injection blocking, secret-leak blocking, and false-positive checks (benign input must NOT be redacted/blocked) |
| `cases/robustness.yaml` | Step-limit enforcement, empty/non-English input, guardrails combined with the tool loop |

## Case format

```yaml
cases:
  - id: unique-id
    category: tool_use
    mode: chat            # chat | agent (default: chat)
    user_message: "..."
    guardrail_policy: standard   # optional, defaults to policies/guardrails.yaml's default
    golden_tool_calls:           # agent mode only — what a good model would ask for
      - tool: calculator
        arguments: { expression: "6 * 7" }
    golden_final_text: "6 * 7 is 42."
    assertions:
      - type: contains          # contains | not_contains | regex | status_equals |
                                 # tool_called | input_contains | input_not_contains
        value: "42"
```

`input_contains`/`input_not_contains` check the guardrail-*screened* request text (useful for
proving PII redaction) and are only meaningful in `chat` mode — in `agent` mode the assertion
context uses the raw `user_message`, since the redacted text isn't returned to the caller by
`AgentRuntime.run()` (a known limitation, not a bug).

## Running it

```bash
# CI mode — same as the eval-gate job, scripted provider, zero network/model
python -m aegis.eval.cli eval/cases --out eval-report.json

# fail the run below a threshold explicitly (CI defaults to 1.0 — see ADR-0008)
python -m aegis.eval.cli eval/cases --min-pass-rate 1.0
```

Every case here runs against `GoldenScriptProvider`, never a live model — see ADR-0008 for why.
To evaluate answer *quality* from a real local model, point `LocalProvider` at a running Ollama
instance and drive these same `user_message`/`assertions` pairs through `ChatRequest` directly;
that's a manual/local workflow, not part of this CI gate.
