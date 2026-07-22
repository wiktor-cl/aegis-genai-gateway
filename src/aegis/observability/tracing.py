"""OpenTelemetry setup.

One trace spans a whole agent session: the API request span is the root,
the router creates a child span per provider attempt (see
`aegis.providers.router`), and the runtime creates a child span per tool
call (see `aegis.agent.runtime`). A correlation ID (the request/run ID) is
attached to every span as an attribute so logs and traces can be joined.

If `AEGIS_OTEL_EXPORTER_OTLP_ENDPOINT` is unset (the default in this
offline-only repository), spans are exported to stdout via
`ConsoleSpanExporter` — never off-box, never to a paid backend. Under
pytest, the console exporter is skipped (spans are still created and
recorded in-process, just not printed) purely to keep test output readable;
this has no effect on what the app does outside of a test run.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Tracer

from aegis.config import settings

_configured = False


def configure_tracing() -> None:
    global _configured
    if _configured:
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    elif "PYTEST_CURRENT_TEST" not in os.environ:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str) -> Tracer:
    return trace.get_tracer(name)
