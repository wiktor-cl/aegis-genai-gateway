"""Runs `EvalCase`s against the real system, scripted only at the provider
boundary (see docs/adr/0008-eval-gate-golden-fixtures.md).

`chat` mode exercises `GuardrailPipeline.screen_request`/`screen_response`
around a single `GoldenScriptProvider.chat()` call — the same shape as
`routes_chat.py`. `agent` mode runs the full `AgentRuntime` (real tools,
real guardrails, in-memory SQLite trace store) with the tool-calling loop
scripted by the case's golden fixtures.
"""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass, field
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aegis.agent.runtime import AgentConfig, AgentRuntime
from aegis.agent.tools.calculator import CalculatorTool
from aegis.agent.tools.http_allowlist import HttpAllowlistTool
from aegis.agent.tools.knowledge_base import KnowledgeBaseSearchTool
from aegis.agent.tools.registry import ToolRegistry
from aegis.agent.tools.sql_readonly import SqlReadOnlyTool
from aegis.agent.trace import TraceStore
from aegis.config import REPO_ROOT
from aegis.db.base import Base
from aegis.eval.golden_provider import GoldenScriptProvider
from aegis.eval.models import Assertion, EvalCase
from aegis.governance.pipeline import GuardrailPipeline
from aegis.governance.policies import GuardrailPolicySet
from aegis.providers.base import ChatMessage, ChatRequest, Role
from aegis.providers.router import ProviderRouter, RoutingContext, RoutingPolicy

ROUTING_YAML = REPO_ROOT / "policies" / "routing.yaml"
GUARDRAILS_YAML = REPO_ROOT / "policies" / "guardrails.yaml"

EVAL_HTTP_ALLOWED_HOST = "eval-fixtures.test"


@dataclass
class AssertionResult:
    assertion: Assertion
    passed: bool
    detail: str = ""


@dataclass
class EvalCaseResult:
    case_id: str
    category: str
    mode: str
    passed: bool
    assertion_results: list[AssertionResult] = field(default_factory=list)
    error: str | None = None


def _check_assertion(
    a: Assertion,
    *,
    status: str,
    response_text: str | None,
    input_text: str,
    tools_called: list[str],
) -> AssertionResult:
    text = response_text or ""
    if a.type == "contains":
        ok = a.value in text
    elif a.type == "not_contains":
        ok = a.value not in text
    elif a.type == "regex":
        ok = re.search(a.value, text) is not None
    elif a.type == "status_equals":
        ok = status == a.value
    elif a.type == "tool_called":
        ok = a.value in tools_called
    elif a.type == "input_contains":
        ok = a.value in input_text
    elif a.type == "input_not_contains":
        ok = a.value not in input_text
    else:
        return AssertionResult(a, False, f"unknown assertion type: {a.type!r}")
    detail = "" if ok else f"{a.type}({a.value!r}) failed — status={status!r} text={text!r}"
    return AssertionResult(a, ok, detail)


def _guardrail_pipeline() -> GuardrailPipeline:
    return GuardrailPipeline(GuardrailPolicySet.from_yaml(GUARDRAILS_YAML))


async def _run_chat_case(case: EvalCase) -> EvalCaseResult:
    guardrails = _guardrail_pipeline()
    pre = guardrails.screen_request(case.user_message, case.guardrail_policy)

    if not pre.allowed:
        status, response_text, input_text = "blocked_request", None, case.user_message
    else:
        provider = GoldenScriptProvider(case)
        request = ChatRequest(
            messages=[
                ChatMessage(role=Role.SYSTEM, content=case.system_prompt),
                ChatMessage(role=Role.USER, content=pre.text),
            ],
            model="",
            tenant_id="eval",
            request_id=case.id,
        )
        response = await provider.chat(request)
        post = guardrails.screen_response(response.message.content, case.guardrail_policy)
        if not post.allowed:
            status, response_text = "blocked_response", None
        else:
            status, response_text = "completed", post.text
        input_text = pre.text

    results = [
        _check_assertion(
            a, status=status, response_text=response_text, input_text=input_text, tools_called=[]
        )
        for a in case.assertions
    ]
    return EvalCaseResult(
        case_id=case.id,
        category=case.category,
        mode=case.mode,
        passed=all(r.passed for r in results),
        assertion_results=results,
    )


def _build_agent_tools(session: AsyncSession, allowed_http_hosts: list[str]) -> ToolRegistry:
    return ToolRegistry(
        [
            CalculatorTool(),
            KnowledgeBaseSearchTool(),
            SqlReadOnlyTool(session),
            HttpAllowlistTool(allowed_domains=allowed_http_hosts),
        ]
    )


async def _run_agent_case(case: EvalCase) -> EvalCaseResult:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    try:
        provider = GoldenScriptProvider(case)
        policy = RoutingPolicy.from_yaml(ROUTING_YAML)
        router = ProviderRouter(policy, providers={"local": provider})
        trace_store = TraceStore(session)
        tools = _build_agent_tools(session, [EVAL_HTTP_ALLOWED_HOST])
        guardrails = _guardrail_pipeline()
        runtime = AgentRuntime(router, tools, trace_store, AgentConfig(), guardrails=guardrails)
        context = RoutingContext(tenant_id="eval", data_classification="internal")

        needs_http_mock = any(g.tool == "http_get" for g in case.golden_tool_calls)
        if needs_http_mock:
            import respx  # dev-only; eval CLI is a dev/CI tool, never imported by the app

            # HttpAllowlistTool resolves DNS itself (SSRF defense, before the
            # actual request) — respx only mocks the httpx transport, so the
            # fixture host's resolution must be faked too or it 404s on a
            # real NXDOMAIN before respx ever gets involved.
            def _fake_getaddrinfo(host: str, *_args: object, **_kwargs: object) -> list[tuple]:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

            with (
                patch(
                    "aegis.agent.tools.http_allowlist.socket.getaddrinfo",
                    side_effect=_fake_getaddrinfo,
                ),
                respx.mock(assert_all_called=False) as mock,
            ):
                mock.get(url__regex=rf"^https://{re.escape(EVAL_HTTP_ALLOWED_HOST)}/.*").mock(
                    return_value=httpx.Response(
                        200, text="mocked fixture response, no live network"
                    )
                )
                result = await runtime.run(
                    "eval",
                    "eval-case",
                    case.system_prompt,
                    case.user_message,
                    context,
                    guardrail_policy_name=case.guardrail_policy,
                )
        else:
            result = await runtime.run(
                "eval",
                "eval-case",
                case.system_prompt,
                case.user_message,
                context,
                guardrail_policy_name=case.guardrail_policy,
            )

        replayed = await runtime.replay(result.run_id)
        tools_called = [s.tool_name for s in replayed.steps if s.tool_name and not s.error]

        results = [
            _check_assertion(
                a,
                status=result.status,
                response_text=result.final_output,
                input_text=case.user_message,
                tools_called=tools_called,
            )
            for a in case.assertions
        ]
        return EvalCaseResult(
            case_id=case.id,
            category=case.category,
            mode=case.mode,
            passed=all(r.passed for r in results),
            assertion_results=results,
        )
    finally:
        await session.close()
        await engine.dispose()


async def run_case(case: EvalCase) -> EvalCaseResult:
    try:
        if case.mode == "agent":
            return await _run_agent_case(case)
        return await _run_chat_case(case)
    except Exception as exc:  # noqa: BLE001 — a case that blows up must fail loudly, not crash the gate
        return EvalCaseResult(
            case_id=case.id, category=case.category, mode=case.mode, passed=False, error=str(exc)
        )


async def run_cases(cases: list[EvalCase]) -> list[EvalCaseResult]:
    return [await run_case(case) for case in cases]
