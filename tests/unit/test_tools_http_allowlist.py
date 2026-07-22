import httpx
import pytest
import respx

from aegis.agent.tools.base import ToolExecutionError
from aegis.agent.tools.http_allowlist import HttpAllowlistArgs, HttpAllowlistTool


@respx.mock
async def test_allowed_domain_returns_body() -> None:
    respx.get("https://example.com/status").mock(
        return_value=httpx.Response(200, text="ok")
    )
    tool = HttpAllowlistTool(allowed_domains=["example.com"])

    result = await tool.run(HttpAllowlistArgs(url="https://example.com/status"))

    assert result["status_code"] == 200
    assert result["body"] == "ok"


async def test_rejects_domain_not_in_allowlist() -> None:
    tool = HttpAllowlistTool(allowed_domains=["example.com"])
    with pytest.raises(ToolExecutionError):
        await tool.run(HttpAllowlistArgs(url="https://evil.example.org/steal"))


async def test_rejects_non_https_scheme() -> None:
    tool = HttpAllowlistTool(allowed_domains=["example.com"])
    with pytest.raises(ToolExecutionError):
        await tool.run(HttpAllowlistArgs(url="http://example.com/status"))


async def test_rejects_loopback_host_even_if_allowlisted() -> None:
    tool = HttpAllowlistTool(allowed_domains=["localhost"])
    with pytest.raises(ToolExecutionError):
        await tool.run(HttpAllowlistArgs(url="https://localhost/admin"))


async def test_rejects_unresolvable_host() -> None:
    tool = HttpAllowlistTool(allowed_domains=["this-domain-does-not-exist.invalid"])
    with pytest.raises(ToolExecutionError):
        await tool.run(HttpAllowlistArgs(url="https://this-domain-does-not-exist.invalid/x"))


@respx.mock
async def test_truncates_large_response_body() -> None:
    tool = HttpAllowlistTool(allowed_domains=["example.com"])
    tool.max_response_bytes = 10
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(200, text="0123456789abcdef")
    )

    result = await tool.run(HttpAllowlistArgs(url="https://example.com/big"))

    assert result["truncated"] is True
    assert len(result["body"]) == 10
