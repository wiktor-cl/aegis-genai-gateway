"""Aggregates `EvalCaseResult`s into a pass/fail summary and renders it as
JSON (machine-readable, for tooling) and Markdown (for a human reading a CI
job log or a PR comment)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from aegis.eval.runner import EvalCaseResult


@dataclass
class CategorySummary:
    category: str
    total: int
    passed: int

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0


@dataclass
class EvalReport:
    results: list[EvalCaseResult]
    categories: list[CategorySummary] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0

    @property
    def failures(self) -> list[EvalCaseResult]:
        return [r for r in self.results if not r.passed]


def build_report(results: list[EvalCaseResult]) -> EvalReport:
    by_category: dict[str, list[EvalCaseResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)
    categories = [
        CategorySummary(category=cat, total=len(rs), passed=sum(1 for r in rs if r.passed))
        for cat, rs in sorted(by_category.items())
    ]
    return EvalReport(results=results, categories=categories)


def to_json(report: EvalReport) -> str:
    payload = {
        "total": report.total,
        "passed": report.passed,
        "pass_rate": report.pass_rate,
        "categories": [
            {"category": c.category, "total": c.total, "passed": c.passed, "pass_rate": c.pass_rate}
            for c in report.categories
        ],
        "cases": [
            {
                "id": r.case_id,
                "category": r.category,
                "mode": r.mode,
                "passed": r.passed,
                "error": r.error,
                "assertions": [
                    {
                        "type": a.assertion.type,
                        "value": a.assertion.value,
                        "passed": a.passed,
                        "detail": a.detail,
                    }
                    for a in r.assertion_results
                ],
            }
            for r in report.results
        ],
    }
    return json.dumps(payload, indent=2)


def to_markdown(report: EvalReport) -> str:
    lines = [
        "# Eval report",
        "",
        f"**{report.passed}/{report.total} cases passed** ({report.pass_rate:.0%})",
        "",
        "| Category | Passed | Total | Pass rate |",
        "|---|---|---|---|",
    ]
    for c in report.categories:
        lines.append(f"| {c.category} | {c.passed} | {c.total} | {c.pass_rate:.0%} |")

    if report.failures:
        lines += ["", "## Failures", ""]
        for r in report.failures:
            lines.append(f"### {r.case_id} ({r.category}/{r.mode})")
            if r.error:
                lines.append(f"- error: `{r.error}`")
            for a in r.assertion_results:
                if not a.passed:
                    lines.append(
                        f"- assertion `{a.assertion.type}={a.assertion.value!r}`: {a.detail}"
                    )
            lines.append("")

    return "\n".join(lines)
