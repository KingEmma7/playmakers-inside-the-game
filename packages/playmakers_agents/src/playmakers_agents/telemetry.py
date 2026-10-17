from __future__ import annotations

import os

SERVICE_NAME = "playmakers-api"
_configured = False


def configure_tracing(service_name: str = SERVICE_NAME) -> bool:
    """Send Agent Framework spans to Application Insights when its connection string is set.

    Off by default, so offline runs and CI never import or contact Azure Monitor.
    """
    global _configured
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return False
    if _configured:
        return True
    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor

    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    configure_azure_monitor(connection_string=connection_string)
    # Match data is synthetic, so prompts and responses may be recorded for the Tracing view.
    enable_instrumentation(enable_sensitive_data=os.getenv("PLAYMAKERS_TRACE_CONTENT", "1") == "1")
    _configured = True
    return True
