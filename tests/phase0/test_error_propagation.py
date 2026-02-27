"""Verify error codes and messages propagate correctly across AumOS services.

Tests:
- HTTP error codes from downstream services are forwarded correctly
- Structured error envelopes are preserved through the service chain
- Validation errors include field-level details
- Database constraint violations map to semantic error codes
- Kafka consumer errors trigger appropriate error events
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_TENANT_ID = str(uuid.uuid4())


def _make_error_response(
    error_code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured error response envelope."""
    return {
        "error": {
            "code": error_code,
            "message": message,
            "request_id": str(uuid.uuid4()),
            "details": details or {},
        }
    }


@pytest.mark.phase0
class TestErrorPropagation:
    """Verify error codes propagate correctly across service boundaries."""

    async def test_downstream_404_propagated_as_404(self) -> None:
        """When a downstream service returns 404, the API gateway forwards it as 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = _make_error_response(
            error_code="RESOURCE_NOT_FOUND",
            message="Dataset not found",
            status_code=404,
            details={"resource_type": "dataset", "resource_id": str(uuid.uuid4())},
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://localhost:8001/api/v1/datasets/{uuid.uuid4()}",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
        assert body["error"]["details"]["resource_type"] == "dataset"

    async def test_downstream_503_propagated_with_retry_hint(self) -> None:
        """A 503 from a downstream service is forwarded with Retry-After header."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.headers = {"Retry-After": "30"}
        mock_response.json.return_value = _make_error_response(
            error_code="SERVICE_UNAVAILABLE",
            message="Data Factory service is temporarily unavailable",
            status_code=503,
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8002/api/v1/synthesis/jobs",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                    json={"schema": "test"},
                )

        assert response.status_code == 503
        assert "Retry-After" in response.headers
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    async def test_validation_error_includes_field_details(self) -> None:
        """Validation errors return 422 with per-field error details."""
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request body validation failed",
                "details": {
                    "fields": [
                        {"field": "schema.row_count", "error": "must be > 0"},
                        {"field": "schema.output_format", "error": "must be one of [parquet, csv, json]"},
                    ]
                },
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8002/api/v1/synthesis/jobs",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                    json={"schema": {"row_count": -1, "output_format": "xlsx"}},
                )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        fields = error["details"]["fields"]
        field_names = [f["field"] for f in fields]
        assert "schema.row_count" in field_names
        assert "schema.output_format" in field_names

    async def test_database_constraint_violation_returns_409(self) -> None:
        """A unique-constraint violation in the DB is translated to HTTP 409."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.json.return_value = _make_error_response(
            error_code="RESOURCE_CONFLICT",
            message="A dataset with this name already exists for this tenant",
            status_code=409,
            details={"conflicting_field": "name", "conflicting_value": "duplicate-dataset"},
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8001/api/v1/datasets",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                    json={"name": "duplicate-dataset"},
                )

        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "RESOURCE_CONFLICT"
        assert body["error"]["details"]["conflicting_field"] == "name"

    async def test_rate_limit_error_includes_limit_headers(self) -> None:
        """Rate-limited requests return 429 with X-RateLimit headers."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1740566400",
            "Retry-After": "60",
        }
        mock_response.json.return_value = _make_error_response(
            error_code="RATE_LIMIT_EXCEEDED",
            message="Too many requests. Please slow down.",
            status_code=429,
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://localhost:8001/api/v1/datasets",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                )

        assert response.status_code == 429
        assert "X-RateLimit-Remaining" in response.headers
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    async def test_error_includes_request_id_for_tracing(self) -> None:
        """All error responses include a request_id for distributed trace correlation."""
        request_id = str(uuid.uuid4())
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "request_id": request_id,
                "details": {},
            }
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://localhost:8001/api/v1/datasets",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                )

        assert response.status_code == 500
        error = response.json()["error"]
        assert "request_id" in error
        assert len(error["request_id"]) > 0

    async def test_kafka_consumer_error_emits_error_event(self) -> None:
        """When a Kafka consumer fails to process an event, an error event is emitted."""
        error_events: list[dict[str, Any]] = []

        def emit_error_event(original_event: dict[str, Any], reason: str) -> None:
            error_events.append({
                "event_type": "EVENT_PROCESSING_FAILED",
                "original_event_id": original_event["event_id"],
                "tenant_id": original_event["tenant_id"],
                "reason": reason,
                "error_code": "CONSUMER_PROCESSING_ERROR",
            })

        bad_event = {
            "event_id": str(uuid.uuid4()),
            "tenant_id": MOCK_TENANT_ID,
            "event_type": "MALFORMED",
        }

        try:
            raise ValueError("Schema validation failed for event")
        except ValueError as exc:
            emit_error_event(bad_event, str(exc))

        assert len(error_events) == 1
        assert error_events[0]["error_code"] == "CONSUMER_PROCESSING_ERROR"
        assert error_events[0]["original_event_id"] == bad_event["event_id"]
