"""
OpenTelemetry setup for VA Loan Concierge.

Initializes tracing with Azure Monitor export so conversation threads,
agent routing decisions, and tool calls appear in Application Insights.

No-ops gracefully when APPLICATIONINSIGHTS_CONNECTION_STRING is absent
(local dev without App Insights).
"""

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Module-level tracer — importable by other modules for custom spans.
# Set after setup_telemetry() configures the provider; falls back to
# the no-op tracer if telemetry is disabled.
_tracer = None


def get_tracer():
    """Return the configured OTel tracer, or a no-op tracer if not set up."""
    global _tracer
    if _tracer is None:
        from opentelemetry import trace
        _tracer = trace.get_tracer("va-loan-concierge")
    return _tracer


def setup_telemetry(app: FastAPI) -> bool:
    """
    Initialize OpenTelemetry with Azure Monitor exporter.

    Returns True if telemetry was configured, False if skipped (no
    connection string). Safe to call multiple times — subsequent calls
    are no-ops.
    """
    conn_str = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn_str:
        logger.info("telemetry: APPLICATIONINSIGHTS_CONNECTION_STRING not set — telemetry disabled")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

        resource = Resource.create({
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "va-loan-concierge"),
            "service.version": "1.0.0",
        })

        provider = TracerProvider(resource=resource)
        exporter = AzureMonitorTraceExporter(connection_string=conn_str)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Instrument frameworks.
        FastAPIInstrumentor.instrument_app(app)
        RequestsInstrumentor().instrument()
        AioHttpClientInstrumentor().instrument()

        global _tracer
        _tracer = trace.get_tracer("va-loan-concierge")

        logger.info("telemetry: OpenTelemetry configured with Azure Monitor exporter")
        return True

    except ImportError as exc:
        logger.warning("telemetry: OTel packages not installed — telemetry disabled (%s)", exc)
        return False
    except Exception as exc:
        logger.warning("telemetry: failed to initialize — telemetry disabled (%s)", exc)
        return False
