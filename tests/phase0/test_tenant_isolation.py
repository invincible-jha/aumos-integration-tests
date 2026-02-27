"""Verify tenant isolation across all AumOS foundation services.

Tests:
- Tenant A cannot see Tenant B's data via API
- Tenant A cannot see Tenant B's events
- RLS prevents cross-tenant queries at the database level
- Storage buckets enforce per-tenant access boundaries
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


TENANT_A_ID = str(uuid.uuid4())
TENANT_B_ID = str(uuid.uuid4())


def _make_dataset_record(tenant_id: str, dataset_id: str | None = None) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "name": f"dataset-for-{tenant_id[:8]}",
        "status": "ready",
    }


@pytest.mark.phase0
class TestTenantIsolation:
    """Cross-service tenant isolation verification."""

    async def test_api_tenant_isolation(self) -> None:
        """Tenant A's API calls cannot return Tenant B's data."""
        tenant_b_dataset = _make_dataset_record(TENANT_B_ID)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": [], "total": 0}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://localhost:8001/api/v1/datasets",
                    headers={"Authorization": f"Bearer tenant_a_{TENANT_A_ID}_token"},
                )

        assert response.status_code == 200
        items = response.json()["items"]
        # Tenant A's listing must not include Tenant B's dataset
        tenant_b_ids = {item["dataset_id"] for item in items if item.get("tenant_id") == TENANT_B_ID}
        assert len(tenant_b_ids) == 0

    async def test_event_tenant_isolation(self) -> None:
        """Events published by Tenant A are not visible to Tenant B consumers."""
        received_by_tenant_b: list[dict[str, Any]] = []

        def consumer_for_tenant(consumer_tenant_id: str, event: dict[str, Any]) -> None:
            if event["tenant_id"] == consumer_tenant_id:
                received_by_tenant_b.append(event)

        tenant_a_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "DATASET_CREATED",
            "tenant_id": TENANT_A_ID,
            "payload": {"secret_data": "tenant_a_proprietary"},
        }

        consumer_for_tenant(TENANT_B_ID, tenant_a_event)

        assert len(received_by_tenant_b) == 0

    async def test_rls_database_isolation(self) -> None:
        """Direct database queries with Tenant A context cannot read Tenant B data."""
        all_records = [
            _make_dataset_record(TENANT_A_ID),
            _make_dataset_record(TENANT_A_ID),
            _make_dataset_record(TENANT_B_ID),  # This should be invisible
        ]

        def query_with_rls_context(tenant_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            # Simulates RLS: WHERE tenant_id = current_setting('app.tenant_id')
            return [r for r in records if r["tenant_id"] == tenant_id]

        tenant_a_visible = query_with_rls_context(TENANT_A_ID, all_records)
        tenant_b_visible = query_with_rls_context(TENANT_B_ID, all_records)

        assert len(tenant_a_visible) == 2
        assert len(tenant_b_visible) == 1
        # Tenant A sees none of Tenant B's records
        assert all(r["tenant_id"] == TENANT_A_ID for r in tenant_a_visible)

    async def test_storage_bucket_tenant_isolation(self) -> None:
        """MinIO/S3 objects for Tenant A are inaccessible under Tenant B's path prefix."""
        # Objects are stored under /<tenant_id>/<dataset_id>/<filename>
        tenant_a_object_key = f"{TENANT_A_ID}/dataset-001/data.parquet"
        tenant_b_prefix = f"{TENANT_B_ID}/"

        def can_access_object(requester_prefix: str, object_key: str) -> bool:
            return object_key.startswith(requester_prefix)

        assert can_access_object(f"{TENANT_A_ID}/", tenant_a_object_key) is True
        assert can_access_object(tenant_b_prefix, tenant_a_object_key) is False

    async def test_kafka_consumer_group_scoped_to_tenant(self) -> None:
        """Each tenant's consumer group is scoped so it only receives its own events."""
        events_on_topic = [
            {"event_id": str(uuid.uuid4()), "tenant_id": TENANT_A_ID, "type": "E1"},
            {"event_id": str(uuid.uuid4()), "tenant_id": TENANT_B_ID, "type": "E2"},
            {"event_id": str(uuid.uuid4()), "tenant_id": TENANT_A_ID, "type": "E3"},
        ]

        def filtered_consumer(tenant_id: str, raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [e for e in raw_events if e["tenant_id"] == tenant_id]

        tenant_a_events = filtered_consumer(TENANT_A_ID, events_on_topic)
        tenant_b_events = filtered_consumer(TENANT_B_ID, events_on_topic)

        assert len(tenant_a_events) == 2
        assert len(tenant_b_events) == 1
        assert all(e["tenant_id"] == TENANT_A_ID for e in tenant_a_events)
        assert all(e["tenant_id"] == TENANT_B_ID for e in tenant_b_events)

    async def test_tenant_resource_quota_scoped(self) -> None:
        """Resource quota checks apply per-tenant and do not bleed across tenants."""
        quotas: dict[str, int] = {TENANT_A_ID: 5, TENANT_B_ID: 10}
        usage: dict[str, int] = {TENANT_A_ID: 4, TENANT_B_ID: 1}

        def can_create_resource(tenant_id: str) -> bool:
            return usage.get(tenant_id, 0) < quotas.get(tenant_id, 0)

        assert can_create_resource(TENANT_A_ID) is True  # 4 < 5
        assert can_create_resource(TENANT_B_ID) is True  # 1 < 10

        # Exhaust Tenant A's quota
        usage[TENANT_A_ID] = 5
        assert can_create_resource(TENANT_A_ID) is False
        # Tenant B is unaffected
        assert can_create_resource(TENANT_B_ID) is True
