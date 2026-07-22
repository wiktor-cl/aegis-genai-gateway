"""Allowlisted HTTP GET tool.

SSRF defenses (see docs/threat-model.md, "agent tool used to reach internal
services"):
  1. only `https://` URLs are accepted,
  2. the hostname must be in a configured allowlist (from tenant policy, not
     model input),
  3. the hostname is resolved and every returned address is checked against
     private/loopback/link-local/reserved ranges before the request is made,
  4. redirects are never followed automatically — a redirect to a
     non-allowlisted or private host is exactly the classic SSRF-via-redirect
     bypass, so the tool returns the redirect response itself instead of
     chasing it.

Known limitation: the allowlist/IP check and the actual request are two
separate network operations (DNS could theoretically change in between —
a "DNS rebinding" TOCTOU). Closing that fully requires resolving once and
connecting directly to the pinned IP with the original Host header, which
is a reasonable hardening step for a real deployment but is not implemented
here to keep the tool's code readable for this portfolio project.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from aegis.agent.tools.base import Tool, ToolExecutionError


class HttpAllowlistArgs(BaseModel):
    url: str = Field(..., description="https:// URL to fetch; host must be in the allowlist")


class HttpAllowlistTool(Tool[HttpAllowlistArgs]):
    name = "http_get"
    description = "Fetch a URL via HTTP GET. Only hosts in the configured allowlist are permitted."
    args_model = HttpAllowlistArgs
    timeout_s = 8.0
    max_response_bytes = 20_000

    def __init__(self, allowed_domains: list[str], timeout_s: float = 8.0) -> None:
        self._allowed_domains = {d.lower() for d in allowed_domains}
        self.timeout_s = timeout_s

    def _validate_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        if parsed.scheme != "https":
            raise ToolExecutionError("only https:// URLs are allowed")
        host = (parsed.hostname or "").lower()
        if host not in self._allowed_domains:
            raise ToolExecutionError(f"host '{host}' is not in the allowlist")
        self._reject_private_ip(host)
        return raw_url

    def _reject_private_ip(self, host: str) -> None:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ToolExecutionError(f"could not resolve host '{host}': {exc}") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ToolExecutionError(
                    f"host '{host}' resolves to a non-public address ({ip}) — refusing"
                )

    async def run(self, arguments: HttpAllowlistArgs) -> dict:
        url = self._validate_url(arguments.url)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=False) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise ToolExecutionError(f"request failed: {exc}") from exc

        truncated = len(resp.text) > self.max_response_bytes
        return {
            "status_code": resp.status_code,
            "body": resp.text[: self.max_response_bytes],
            "truncated": truncated,
        }
