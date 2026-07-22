"""Agent runtime — the tool-calling loop.

One call to `AgentRuntime.run()` is one agent session: it repeatedly calls
the provider router (ADR-0002), executes any tool calls the model asks for,
and feeds the results back, until the model stops asking for tools, the step
limit is hit, or the token budget is exhausted. Every step (LLM call or tool
call) is persisted via `TraceStore` before moving on, which is what makes
`AgentRuntime.replay()` able to reconstruct a run's outcome from the database
alone — no provider or tool is called again during a replay.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from aegis.agent.tools.base import Tool, ToolExecutionError
from aegis.agent.tools.registry import ToolRegistry
from aegis.agent.trace import ReplayedRun, StepRecord, TraceStore
from aegis.providers.base import ChatMessage, ChatRequest, ProviderError, Role
from aegis.providers.router import ProviderRouter, RoutingContext


@dataclass
class AgentConfig:
    max_steps: int = 8
    token_budget: int = 20_000
    tool_retry_max_attempts: int = 3
    tool_retry_backoff_base_s: float = 0.5


@dataclass
class AgentRunResult:
    run_id: uuid.UUID
    status: str
    """completed | failed | budget_exceeded | max_steps_exceeded"""
    final_output: str | None
    total_input_tokens: int
    total_output_tokens: int
    step_count: int


class AgentRuntime:
    def __init__(
        self,
        router: ProviderRouter,
        tools: ToolRegistry,
        trace_store: TraceStore,
        config: AgentConfig | None = None,
    ) -> None:
        self._router = router
        self._tools = tools
        self._trace = trace_store
        self._config = config or AgentConfig()

    async def run(
        self,
        tenant_id: str,
        agent_name: str,
        system_prompt: str,
        user_message: str,
        routing_context: RoutingContext,
    ) -> AgentRunResult:
        cfg = self._config
        run_id = await self._trace.start_run(
            tenant_id=tenant_id,
            agent_name=agent_name,
            max_steps=cfg.max_steps,
            token_budget=cfg.token_budget,
            data_classification=routing_context.data_classification,
            cost_tier=routing_context.cost_tier,
        )

        messages: list[ChatMessage] = [
            ChatMessage(role=Role.SYSTEM, content=system_prompt),
            ChatMessage(role=Role.USER, content=user_message),
        ]
        total_input = 0
        total_output = 0

        for step_index in range(cfg.max_steps):
            request = ChatRequest(
                messages=messages,
                model="",
                tools=self._tools.specs(),
                tenant_id=tenant_id,
                request_id=str(run_id),
            )
            started = time.monotonic()
            try:
                response = await self._router.route(request, routing_context)
            except ProviderError as exc:
                await self._trace.record_step(
                    run_id,
                    step_index,
                    StepRecord(
                        step_type="llm_call",
                        input={"messages": [m.model_dump(mode="json") for m in messages]},
                        error=str(exc),
                        duration_ms=_elapsed_ms(started),
                    ),
                )
                await self._trace.finish_run(run_id, status="failed", error=str(exc))
                return AgentRunResult(
                    run_id, "failed", None, total_input, total_output, step_index + 1
                )

            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

            await self._trace.record_step(
                run_id,
                step_index,
                StepRecord(
                    step_type="llm_call",
                    input={"messages": [m.model_dump(mode="json") for m in messages]},
                    output=response.model_dump(mode="json"),
                    provider_name=response.provider_name,
                    model=response.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    duration_ms=_elapsed_ms(started),
                ),
            )

            if total_input + total_output > cfg.token_budget:
                await self._trace.finish_run(
                    run_id, status="budget_exceeded", error="token budget exceeded"
                )
                return AgentRunResult(
                    run_id, "budget_exceeded", None, total_input, total_output, step_index + 1
                )

            messages.append(response.message)

            if not response.tool_calls:
                await self._trace.finish_run(
                    run_id, status="completed", final_output=response.message.content
                )
                return AgentRunResult(
                    run_id,
                    "completed",
                    response.message.content,
                    total_input,
                    total_output,
                    step_index + 1,
                )

            for tool_call in response.tool_calls:
                tool = self._tools.get(tool_call.name)
                error: str | None
                if tool is None:
                    error = f"unknown tool: {tool_call.name}"
                    result_content = json.dumps({"error": error})
                    await self._trace.record_step(
                        run_id,
                        step_index,
                        StepRecord(
                            step_type="tool_call",
                            tool_name=tool_call.name,
                            input=tool_call.arguments,
                            error=error,
                        ),
                    )
                else:
                    result_content, error, retry_count, duration_ms = (
                        await self._execute_tool_with_retry(tool, tool_call.arguments)
                    )
                    await self._trace.record_step(
                        run_id,
                        step_index,
                        StepRecord(
                            step_type="tool_call",
                            tool_name=tool.name,
                            input=tool_call.arguments,
                            output=None if error else {"result": result_content},
                            error=error,
                            retry_count=retry_count,
                            duration_ms=duration_ms,
                        ),
                    )
                messages.append(
                    ChatMessage(
                        role=Role.TOOL,
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=result_content,
                    )
                )

        await self._trace.finish_run(
            run_id, status="max_steps_exceeded", error="max steps exceeded"
        )
        return AgentRunResult(
            run_id, "max_steps_exceeded", None, total_input, total_output, cfg.max_steps
        )

    async def _execute_tool_with_retry(
        self, tool: Tool[Any], arguments: dict
    ) -> tuple[str, str | None, int, int]:
        started = time.monotonic()
        try:
            validated_args = tool.args_model.model_validate(arguments)
        except ValidationError as exc:
            error = f"invalid tool arguments: {exc}"
            return json.dumps({"error": error}), error, 0, _elapsed_ms(started)

        last_error: str | None = None
        max_attempts = self._config.tool_retry_max_attempts
        for attempt in range(max_attempts):
            try:
                result = await asyncio.wait_for(tool.run(validated_args), timeout=tool.timeout_s)
                return json.dumps(result, default=str), None, attempt, _elapsed_ms(started)
            except ToolExecutionError as exc:
                # not retryable: bad/malformed input, retrying the same call won't help
                return json.dumps({"error": str(exc)}), str(exc), attempt, _elapsed_ms(started)
            except TimeoutError:
                last_error = f"tool timed out after {tool.timeout_s}s"
            except Exception as exc:  # noqa: BLE001 — unexpected/transient tool failure, retry
                last_error = str(exc)

            if attempt < max_attempts - 1:
                backoff = self._config.tool_retry_backoff_base_s * (2**attempt)
                await asyncio.sleep(backoff)

        return json.dumps({"error": last_error}), last_error, max_attempts, _elapsed_ms(started)

    async def replay(self, run_id: uuid.UUID) -> ReplayedRun:
        return await self._trace.replay(run_id)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
