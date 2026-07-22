"""Eval-gate CLI: `python -m aegis.eval <cases_dir>`.

Loads every `EvalCase` under `cases_dir`, runs it (see runner.py — scripted
only at the provider boundary, docs/adr/0008), prints a Markdown summary,
optionally writes a JSON report, and exits non-zero if the pass rate falls
below `--min-pass-rate`. This is what `.github/workflows/ci.yml`'s
`eval-gate` job invokes as a merge gate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from aegis.eval.models import load_cases
from aegis.eval.report import build_report, to_json, to_markdown
from aegis.eval.runner import run_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Aegis eval-gate against golden fixtures.")
    parser.add_argument("cases_dir", type=Path, help="Directory of *.yaml eval case files")
    parser.add_argument("--out", type=Path, default=None, help="Write the JSON report to this path")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=1.0,
        help="Exit non-zero if the overall pass rate is below this (default: 1.0 — see ADR-0008)",
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.cases_dir)
    if not cases:
        print(f"no eval cases found under {args.cases_dir}", file=sys.stderr)
        return 1

    results = asyncio.run(run_cases(cases))
    report = build_report(results)

    print(to_markdown(report))
    if args.out is not None:
        args.out.write_text(to_json(report), encoding="utf-8")

    if report.pass_rate < args.min_pass_rate:
        print(
            f"\neval-gate FAILED: pass rate {report.pass_rate:.0%} "
            f"is below the required {args.min_pass_rate:.0%}",
            file=sys.stderr,
        )
        return 1

    print(f"\neval-gate passed: {report.passed}/{report.total} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
