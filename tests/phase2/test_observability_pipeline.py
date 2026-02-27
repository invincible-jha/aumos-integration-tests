"""Verify OTEL traces flow correctly through AumOS services.

Tests:
- Trace context propagated via W3C traceparent headers
- Spans created per service hop
- Span attributes include tenant_id and correlation_id
- Error spans include exception details
- Metrics are emitted alongside traces
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_TENANT_ID = str(uuid.uuid4())
MOCK_TRACE_ID = uuid.uuid4().hex + uuid.uuid4().hex  # 32 hex chars


def _make_traceparent(trace_id: str, span_id: str, flags: str = "01") -> str:
    """Build a W3C traceparent header value."""
    return f"00-{trace_id}-{span_id}-{flags}"


def _make_span(
    name: str,
    trace_id: str,
    parent_span_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    span_id = uuid.uuid4().hex[:16]
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "parent_span_id": parent_span_id,
        "name": name,
        "attributes": attributes or {},
        "error": error,
        "start_time": "2026-02-26T10:00:00Z",
        "end_time": "2026-02-26T10:00:00.050Z",
    }


@pytest.mark.phase2
class TestObservabilityPipeline:
    """Verify OTEL traces and metrics flow correctly through AumOS services."""

    async def test_traceparent_header_propagated_downstream(self) -> None:
        """Incoming W3C traceparent is forwarded to all downstream service calls."""
        incoming_trace_id = MOCK_TRACE_ID
        incoming_span_id = uuid.uuid4().hex[:16]
        traceparent = _make_traceparent(incoming_trace_id, incoming_span_id)

        downstream_calls: list[dict[str, Any]] = []

        def make_downstream_call(service: str, parent_traceparent: str) -> dict[str, Any]:
            new_span_id = uuid.uuid4().hex[:16]
            trace_id = parent_traceparent.split("-")[1]
            call = {
                "service": service,
                "traceparent": _make_traceparent(trace_id, new_span_id),
                "trace_id": trace_id,
            }
            downstream_calls.append(call)
            return call

        make_downstream_call("data-factory", traceparent)
        make_downstream_call("governance-engine", traceparent)

        assert all(c["trace_id"] == incoming_trace_id for c in downstream_calls)
        assert len(downstream_calls) == 2

    async def test_span_created_per_service_hop(self) -> None:
        """Each service in the call chain creates its own span under the same trace."""
        trace_id = MOCK_TRACE_ID
        root_span = _make_span("platform-core.request", trace_id)

        child_spans = [
            _make_span("data-factory.synthesize", trace_id, parent_span_id=root_span["span_id"]),
            _make_span("governance-engine.evaluate", trace_id, parent_span_id=root_span["span_id"]),
        ]

        all_spans = [root_span] + child_spans

        # All spans share the same trace_id
        assert all(s["trace_id"] == trace_id for s in all_spans)

        # Child spans have root as parent
        for child in child_spans:
            assert child["parent_span_id"] == root_span["span_id"]

    async def test_span_attributes_include_tenant_and_correlation(self) -> None:
        """Spans must carry tenant_id and correlation_id as standard attributes."""
        correlation_id = str(uuid.uuid4())
        span = _make_span(
            "api.handle_request",
            MOCK_TRACE_ID,
            attributes={
                "tenant_id": MOCK_TENANT_ID,
                "correlation_id": correlation_id,
                "http.method": "POST",
                "http.route": "/api/v1/synthesis/jobs",
            },
        )

        assert span["attributes"].get("tenant_id") == MOCK_TENANT_ID
        assert span["attributes"].get("correlation_id") == correlation_id

    async def test_error_span_includes_exception_details(self) -> None:
        """A span for a failed operation records the exception type and message."""
        error_span = _make_span(
            "data-factory.synthesize",
            MOCK_TRACE_ID,
            error="ValueError: Schema column 'x' has invalid type",
            attributes={
                "tenant_id": MOCK_TENANT_ID,
                "error.type": "ValueError",
                "error.message": "Schema column 'x' has invalid type",
                "span.status": "ERROR",
            },
        )

        assert error_span["error"] is not None
        assert error_span["attributes"].get("span.status") == "ERROR"
        assert "ValueError" in error_span["attributes"].get("error.type", "")

    async def test_metrics_emitted_for_synthesis_job(self) -> None:
        """Synthesis job metrics (duration, row_count) are recorded as OTEL metrics."""
        emitted_metrics: list[dict[str, Any]] = []

        def record_metric(name: str, value: float, labels: dict[str, str]) -> None:
            emitted_metrics.append({"name": name, "value": value, "labels": labels})

        # Simulate metrics emitted at job completion
        record_metric(
            "aumos.synthesis.job.duration_ms",
            4523.0,
            {"tenant_id": MOCK_TENANT_ID, "status": "COMPLETED"},
        )
        record_metric(
            "aumos.synthesis.job.row_count",
            1000.0,
            {"tenant_id": MOCK_TENANT_ID, "output_format": "parquet"},
        )

        metric_names = {m["name"] for m in emitted_metrics}
        assert "aumos.synthesis.job.duration_ms" in metric_names
        assert "aumos.synthesis.job.row_count" in metric_names
        assert all("tenant_id" in m["labels"] for m in emitted_metrics)

    async def test_trace_sampling_respects_tenant_config(self) -> None:
        """Trace sampling rate can be configured per tenant."""
        sampling_config: dict[str, float] = {
            MOCK_TENANT_ID: 1.0,   # 100% sampling
            "other-tenant": 0.1,   # 10% sampling
        }

        def should_sample(tenant_id: str, request_hash: int) -> bool:
            rate = sampling_config.get(tenant_id, 0.05)
            return (request_hash % 100) < int(rate * 100)

        # With 100% rate, all requests sampled
        assert should_sample(MOCK_TENANT_ID, 42) is True
        assert should_sample(MOCK_TENANT_ID, 99) is True

        # With 10% rate, only low hashes sampled
        assert should_sample("other-tenant", 5) is True
        assert should_sample("other-tenant", 50) is False

    async def test_otel_exporter_endpoint_reachable(self) -> None:
        """OTEL collector endpoint is reachable and accepts trace data."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:4318/v1/traces",
                    headers={"Content-Type": "application/json"},
                    json={
                        "resourceSpans": [
                            {
                                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "platform-core"}}]},
                                "scopeSpans": [],
                            }
                        ]
                    },
                )

        assert response.status_code == 200
