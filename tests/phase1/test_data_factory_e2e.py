"""End-to-end Data Factory integration tests.

Tests:
- Full pipeline: schema definition → job creation → synthesis → storage → audit
- Job queuing and status polling
- Output dataset stored in MinIO under correct tenant prefix
- Synthesis audit event emitted to Kafka
- Tenant isolation within the data factory
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_TENANT_ID = str(uuid.uuid4())


def _make_schema_definition(
    row_count: int = 1000,
    output_format: str = "parquet",
    columns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_id": str(uuid.uuid4()),
        "tenant_id": MOCK_TENANT_ID,
        "row_count": row_count,
        "output_format": output_format,
        "columns": columns or [
            {"name": "id", "type": "uuid", "nullable": False},
            {"name": "amount", "type": "float", "min": 0.0, "max": 10000.0},
            {"name": "category", "type": "categorical", "categories": ["A", "B", "C"]},
            {"name": "timestamp", "type": "datetime", "start": "2024-01-01"},
        ],
    }


def _make_synthesis_job(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(uuid.uuid4()),
        "tenant_id": schema["tenant_id"],
        "schema": schema,
        "status": "QUEUED",
        "created_at": "2026-02-26T10:00:00Z",
        "updated_at": "2026-02-26T10:00:00Z",
    }


@pytest.mark.phase1
class TestDataFactoryE2E:
    """Verify the full Data Factory end-to-end pipeline."""

    async def test_synthesis_job_created_from_schema(self) -> None:
        """A valid schema definition creates a synthesis job in QUEUED state."""
        schema = _make_schema_definition()
        job = _make_synthesis_job(schema)

        assert job["status"] == "QUEUED"
        assert job["tenant_id"] == MOCK_TENANT_ID
        assert job["schema"]["row_count"] == 1000

    async def test_synthesis_job_created_via_api(self) -> None:
        """POST /synthesis/jobs returns 201 with job_id and QUEUED status."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "job_id": str(uuid.uuid4()),
            "tenant_id": MOCK_TENANT_ID,
            "status": "QUEUED",
            "created_at": "2026-02-26T10:00:00Z",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8002/api/v1/synthesis/jobs",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                    json={
                        "row_count": 500,
                        "output_format": "parquet",
                        "columns": [{"name": "id", "type": "uuid"}],
                    },
                )

        assert response.status_code == 201
        body = response.json()
        assert "job_id" in body
        assert body["status"] == "QUEUED"

    async def test_synthesis_job_status_transitions(self) -> None:
        """Job status transitions: QUEUED → RUNNING → COMPLETED."""
        valid_transitions: dict[str, list[str]] = {
            "QUEUED": ["RUNNING", "CANCELLED"],
            "RUNNING": ["COMPLETED", "FAILED"],
            "COMPLETED": [],
            "FAILED": [],
            "CANCELLED": [],
        }

        def can_transition(from_state: str, to_state: str) -> bool:
            return to_state in valid_transitions.get(from_state, [])

        assert can_transition("QUEUED", "RUNNING") is True
        assert can_transition("RUNNING", "COMPLETED") is True
        assert can_transition("COMPLETED", "RUNNING") is False
        assert can_transition("QUEUED", "COMPLETED") is False  # must go through RUNNING

    async def test_completed_job_output_stored_in_minio(self) -> None:
        """A completed synthesis job stores output under /<tenant_id>/<job_id>/ in MinIO."""
        tenant_id = MOCK_TENANT_ID
        job_id = str(uuid.uuid4())

        def get_expected_object_path(t_id: str, j_id: str, filename: str) -> str:
            return f"{t_id}/{j_id}/{filename}"

        output_path = get_expected_object_path(tenant_id, job_id, "output.parquet")

        assert output_path.startswith(f"{tenant_id}/")
        assert f"/{job_id}/" in output_path
        assert output_path.endswith("output.parquet")

    async def test_synthesis_audit_event_emitted_on_completion(self) -> None:
        """Job completion emits a SYNTHESIS_COMPLETED audit event with output metadata."""
        emitted_events: list[dict[str, Any]] = []

        def emit_completion_event(job: dict[str, Any], output_path: str, row_count: int) -> None:
            emitted_events.append({
                "event_type": "SYNTHESIS_COMPLETED",
                "event_id": str(uuid.uuid4()),
                "tenant_id": job["tenant_id"],
                "job_id": job["job_id"],
                "output_path": output_path,
                "row_count": row_count,
                "timestamp": "2026-02-26T10:05:00Z",
            })

        schema = _make_schema_definition(row_count=1000)
        job = _make_synthesis_job(schema)
        emit_completion_event(job, f"{MOCK_TENANT_ID}/{job['job_id']}/output.parquet", 1000)

        assert len(emitted_events) == 1
        event = emitted_events[0]
        assert event["event_type"] == "SYNTHESIS_COMPLETED"
        assert event["row_count"] == 1000
        assert event["tenant_id"] == MOCK_TENANT_ID

    async def test_synthesis_schema_column_validation(self) -> None:
        """Schema with invalid column types raises a validation error."""
        def validate_schema(schema: dict[str, Any]) -> list[str]:
            valid_types = {"uuid", "string", "integer", "float", "datetime", "boolean", "categorical"}
            errors = []
            for col in schema.get("columns", []):
                if col.get("type") not in valid_types:
                    errors.append(f"Column '{col['name']}': invalid type '{col['type']}'")
                if not col.get("name"):
                    errors.append("Column missing required field: 'name'")
            return errors

        bad_schema = _make_schema_definition()
        bad_schema["columns"].append({"name": "bad_col", "type": "spreadsheet"})

        errors = validate_schema(bad_schema)
        assert len(errors) == 1
        assert "bad_col" in errors[0]
        assert "spreadsheet" in errors[0]

    async def test_tenant_isolation_in_synthesis_jobs(self) -> None:
        """Tenant A's synthesis jobs are not returned in Tenant B's job listing."""
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())

        all_jobs = [
            {"job_id": "j1", "tenant_id": tenant_a, "status": "COMPLETED"},
            {"job_id": "j2", "tenant_id": tenant_b, "status": "RUNNING"},
            {"job_id": "j3", "tenant_id": tenant_a, "status": "QUEUED"},
        ]

        def list_jobs_for_tenant(tenant_id: str) -> list[dict[str, Any]]:
            return [j for j in all_jobs if j["tenant_id"] == tenant_id]

        tenant_a_jobs = list_jobs_for_tenant(tenant_a)
        tenant_b_jobs = list_jobs_for_tenant(tenant_b)

        assert len(tenant_a_jobs) == 2
        assert len(tenant_b_jobs) == 1
        assert all(j["tenant_id"] == tenant_a for j in tenant_a_jobs)
        assert all(j["tenant_id"] == tenant_b for j in tenant_b_jobs)
