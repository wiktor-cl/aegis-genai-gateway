"""AgentRuntime tests: tool-calling loop, budgets, retries, and replay.

Uses a ScriptedProvider (queues up canned ChatResponses, like a script for a
fake actor) instead of a real LLM, and small in-process fake tools, so the
whole loop is exercised deterministically and offline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.agent.runtime import AgentConfig, AgentRuntime
from aegis.agent.tools.base import Tool, ToolExecutionError
from aegis.agent.tools.registry import ToolRegistry
from aegis.agent.trace import TraceStore
from aegis.db.base import Base
from aegis.providers.base import (
    ChatMessage,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    LLMProvider,
    Role,
    StreamChunk,
    ToolCall,
    Usage,
)
from aegis.providers.router import ProviderRouter, RoutingContext, RoutingPolicy

ROUTING_YAML = (
    __import__("pathlib").Path(__file__).resolve().parents[2] / "policies" / "routing.yaml"
)


class ScriptedProvider(LLMProvider):
    """Returns one canned ChatResponse per call, in order."""

    def __init__(self, name: str, responses: list[ChatResponse]) -> None:
        self.name = name
        self._responses = list(responses)
        self.call_count = 0

    async def chat(self, request):
        self.call_count += 1
        return self._responses.pop(0)

    async def stream(self, request) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="")

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return True


class EchoArgs(BaseModel):
    value: str


class EchoTool(Tool[EchoArgs]):
    name = "echo"
    description = "Echoes back its input."
    args_model = EchoArgs
    timeout_s = 1.0

    def __init__(self, behavior: str = "success", fail_times: int = 0) -> None:
        self.behavior = behavior
        self.fail_times = fail_times
        self.calls = 0

    async def run(self, arguments: EchoArgs) -> dict:
        self.calls += 1
        if self.behavior == "tool_error":
            raise ToolExecutionError("bad input")
        if self.behavior == "flaky" and self.calls <= self.fail_times:
            raise RuntimeError("transient failure")
        return {"echoed": arguments.value}


def _final_response(content: str, provider_name: str = "local") -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role=Role.ASSISTANT, content=content),
        usage=Usage(input_tokens=10, output_tokens=5),
        provider_name=provider_name,
        model="llama3.1:8b",
    )


def _tool_call_response(tool_name: str, arguments: dict, call_id: str = "call-1") -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role=Role.ASSISTANT, content=""),
        tool_calls=[ToolCall(id=call_id, name=tool_name, arguments=arguments)],
        usage=Usage(input_tokens=20, output_tokens=8),
        provider_name="local",
        model="llama3.1:8b",
        finish_reason="tool_use",
    )


async def _make_runtime(
    responses: list[ChatResponse],
    tools: list[Tool] | None = None,
    config: AgentConfig | None = None,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()

    provider = ScriptedProvider("local", responses)
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    router = ProviderRouter(policy, providers={"local": provider})
    trace_store = TraceStore(session)
    registry = ToolRegistry(tools or [])
    runtime = AgentRuntime(router, registry, trace_store, config or AgentConfig())
    return runtime, provider, session, engine


CONFIDENTIAL_CONTEXT = RoutingContext(tenant_id="t-1", data_classification="confidential")


async def test_single_step_completion() -> None:
    runtime, provider, session, engine = await _make_runtime([_final_response("hello there")])

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "completed"
    assert result.final_output == "hello there"
    assert result.step_count == 1
    assert provider.call_count == 1
    await session.close()
    await engine.dispose()


async def test_tool_call_then_completion() -> None:
    tool = EchoTool()
    responses = [
        _tool_call_response("echo", {"value": "hi"}),
        _final_response("done"),
    ]
    runtime, provider, session, engine = await _make_runtime(responses, tools=[tool])

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "completed"
    assert result.final_output == "done"
    assert tool.calls == 1
    assert provider.call_count == 2
    await session.close()
    await engine.dispose()


async def test_unknown_tool_is_reported_and_run_continues() -> None:
    responses = [
        _tool_call_response("does_not_exist", {"value": "hi"}),
        _final_response("done"),
    ]
    runtime, provider, session, engine = await _make_runtime(responses, tools=[])

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "completed"
    assert result.final_output == "done"
    await session.close()
    await engine.dispose()


async def test_budget_exceeded_stops_the_run() -> None:
    big_usage_response = ChatResponse(
        message=ChatMessage(role=Role.ASSISTANT, content="partial"),
        usage=Usage(input_tokens=15_000, output_tokens=10_000),
        provider_name="local",
        model="llama3.1:8b",
    )
    runtime, provider, session, engine = await _make_runtime(
        [big_usage_response], config=AgentConfig(token_budget=20_000)
    )

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "budget_exceeded"
    assert result.final_output is None
    await session.close()
    await engine.dispose()


async def test_max_steps_exceeded() -> None:
    tool = EchoTool()
    # Every response asks for a tool call again, so the loop never finishes
    # naturally and must be stopped by the step limit.
    responses = [_tool_call_response("echo", {"value": f"turn-{i}"}) for i in range(5)]
    runtime, provider, session, engine = await _make_runtime(
        responses, tools=[tool], config=AgentConfig(max_steps=3)
    )

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "max_steps_exceeded"
    assert result.step_count == 3
    await session.close()
    await engine.dispose()


async def test_flaky_tool_succeeds_after_retry() -> None:
    tool = EchoTool(behavior="flaky", fail_times=1)
    responses = [_tool_call_response("echo", {"value": "hi"}), _final_response("done")]
    runtime, provider, session, engine = await _make_runtime(
        responses,
        tools=[tool],
        config=AgentConfig(tool_retry_max_attempts=3, tool_retry_backoff_base_s=0.01),
    )

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "completed"
    assert tool.calls == 2  # first attempt failed, second succeeded
    await session.close()
    await engine.dispose()


async def test_tool_execution_error_is_not_retried() -> None:
    tool = EchoTool(behavior="tool_error")
    responses = [_tool_call_response("echo", {"value": "hi"}), _final_response("done")]
    runtime, provider, session, engine = await _make_runtime(
        responses, tools=[tool], config=AgentConfig(tool_retry_max_attempts=3)
    )

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "completed"
    assert tool.calls == 1  # ToolExecutionError must not be retried
    await session.close()
    await engine.dispose()


async def test_invalid_tool_arguments_are_rejected_before_running() -> None:
    tool = EchoTool()
    # "value" is required by EchoArgs and missing here.
    responses = [_tool_call_response("echo", {}), _final_response("done")]
    runtime, provider, session, engine = await _make_runtime(responses, tools=[tool])

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)

    assert result.status == "completed"
    assert tool.calls == 0  # never actually invoked — args failed validation first
    await session.close()
    await engine.dispose()


async def test_replay_matches_the_original_run_without_calling_the_provider_again() -> None:
    tool = EchoTool()
    responses = [_tool_call_response("echo", {"value": "hi"}), _final_response("done")]
    runtime, provider, session, engine = await _make_runtime(responses, tools=[tool])

    result = await runtime.run("t-1", "demo", "system", "hi", CONFIDENTIAL_CONTEXT)
    calls_after_run = provider.call_count

    replayed = await runtime.replay(result.run_id)

    assert provider.call_count == calls_after_run  # no new provider calls during replay
    assert replayed.status == "completed"
    assert replayed.final_output == "done"
    assert len(replayed.steps) == 3  # llm_call, tool_call, llm_call
    await session.close()
    await engine.dispose()
