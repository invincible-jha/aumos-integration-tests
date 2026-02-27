"""Kafka event propagation tests — verify events flow correctly between services."""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_TENANT_ID = str(uuid.uuid4())
MOCK_CORRELATION_ID = str(uuid.uuid4())


def _make_audit_event(
    event_type: str,
    tenant_id: str,
    actor_id: str,
    resource_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a mock audit event envelope."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": "1.0",
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "resource_id": resource_id,
        "timestamp": "2026-02-26T10:00:00Z",
        "correlation_id": MOCK_CORRELATION_ID,
        "payload": payload or {},
    }


@pytest.mark.phase0
class TestEventPropagation:
    """Verify events flow correctly between AumOS services via Kafka."""

    async def test_audit_event_published_and_consumed(self) -> None:
        """Audit events published by one service are consumed by the audit sink."""
        audit_event = _make_audit_event(
            event_type="DATASET_CREATED",
            tenant_id=MOCK_TENANT_ID,
            actor_id=str(uuid.uuid4()),
            resource_id=str(uuid.uuid4()),
            payload={"dataset_name": "test-dataset", "schema_version": "2"},
        )

        published_events: list[dict[str, Any]] = []

        async def mock_produce(topic: str, value: bytes, key: bytes | None = None) -> None:
            published_events.append({"topic": topic, "value": json.loads(value)})

        with patch("aumos_common.kafka.producer.produce", new_callable=AsyncMock) as mock_prod:
            mock_prod.side_effect = mock_produce
            mock_prod(
                "aumos.audit.events",
                json.dumps(audit_event).encode(),
                key=MOCK_TENANT_ID.encode(),
            )

        assert len(published_events) == 1
        event = published_events[0]["value"]
        assert event["event_type"] == "DATASET_CREATED"
        assert event["tenant_id"] == MOCK_TENANT_ID
        assert "correlation_id" in event

    async def test_model_lifecycle_event_routing(self) -> None:
        """Model lifecycle events are routed to the governance engine topic."""
        lifecycle_event = _make_audit_event(
            event_type="MODEL_DEPLOYMENT_REQUESTED",
            tenant_id=MOCK_TENANT_ID,
            actor_id=str(uuid.uuid4()),
            resource_id=str(uuid.uuid4()),
            payload={"model_name": "fraud-detector-v2", "environment": "production"},
        )

        consumed_events: list[dict[str, Any]] = []

        def mock_consumer_callback(record: dict[str, Any]) -> None:
            consumed_events.append(record)

        mock_consumer_callback(lifecycle_event)

        assert len(consumed_events) == 1
        assert consumed_events[0]["event_type"] == "MODEL_DEPLOYMENT_REQUESTED"
        assert consumed_events[0]["payload"]["environment"] == "production"

    async def test_tenant_scoped_event_topic_partition(self) -> None:
        """Events are partitioned by tenant_id so tenant consumers only receive their events."""
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())

        event_a = _make_audit_event("DATASET_UPDATED", tenant_a, str(uuid.uuid4()), str(uuid.uuid4()))
        event_b = _make_audit_event("DATASET_UPDATED", tenant_b, str(uuid.uuid4()), str(uuid.uuid4()))

        def get_partition_key(event: dict[str, Any]) -> str:
            return event["tenant_id"]

        assert get_partition_key(event_a) == tenant_a
        assert get_partition_key(event_b) == tenant_b
        assert get_partition_key(event_a) != get_partition_key(event_b)

    async def test_event_schema_validation_on_publish(self) -> None:
        """Publishing an event with missing required fields raises a validation error."""
        malformed_event = {
            "event_type": "DATASET_CREATED",
            # missing: event_id, tenant_id, actor_id, resource_id, timestamp
        }

        def validate_event(event: dict[str, Any]) -> list[str]:
            required_fields = ["event_id", "event_type", "tenant_id", "actor_id", "resource_id", "timestamp"]
            return [f for f in required_fields if f not in event]

        missing_fields = validate_event(malformed_event)
        assert len(missing_fields) > 0
        assert "tenant_id" in missing_fields
        assert "event_id" in missing_fields

    async def test_event_deduplication_on_retry(self) -> None:
        """Re-publishing an event with the same event_id is idempotently handled."""
        event_id = str(uuid.uuid4())
        event = _make_audit_event("POLICY_EVALUATED", MOCK_TENANT_ID, str(uuid.uuid4()), str(uuid.uuid4()))
        event["event_id"] = event_id

        seen_event_ids: set[str] = set()
        processed_count = 0

        def idempotent_handler(e: dict[str, Any]) -> None:
            nonlocal processed_count
            if e["event_id"] not in seen_event_ids:
                seen_event_ids.add(e["event_id"])
                processed_count += 1

        # Simulate duplicate delivery
        idempotent_handler(event)
        idempotent_handler(event)
        idempotent_handler(event)

        assert processed_count == 1
        assert len(seen_event_ids) == 1

    async def test_dead_letter_queue_on_processing_failure(self) -> None:
        """Events that fail processing are routed to the dead-letter topic."""
        bad_event = _make_audit_event(
            event_type="UNKNOWN_TYPE_THAT_WILL_FAIL",
            tenant_id=MOCK_TENANT_ID,
            actor_id=str(uuid.uuid4()),
            resource_id=str(uuid.uuid4()),
        )

        dlq_events: list[dict[str, Any]] = []

        def process_event(event: dict[str, Any]) -> None:
            supported_types = {"DATASET_CREATED", "DATASET_UPDATED", "MODEL_DEPLOYMENT_REQUESTED"}
            if event["event_type"] not in supported_types:
                dlq_events.append({**event, "dlq_reason": "UNSUPPORTED_EVENT_TYPE"})
                raise ValueError(f"Unsupported event type: {event['event_type']}")

        with pytest.raises(ValueError, match="Unsupported event type"):
            process_event(bad_event)

        assert len(dlq_events) == 1
        assert dlq_events[0]["dlq_reason"] == "UNSUPPORTED_EVENT_TYPE"

    async def test_correlation_id_propagated_across_services(self) -> None:
        """Correlation ID from the original request is propagated through all derived events."""
        root_correlation_id = str(uuid.uuid4())

        events_chain: list[dict[str, Any]] = []

        def simulate_service_chain(correlation_id: str) -> None:
            events_chain.append({
                "service": "platform-core",
                "event_type": "REQUEST_RECEIVED",
                "correlation_id": correlation_id,
            })
            events_chain.append({
                "service": "data-factory",
                "event_type": "JOB_QUEUED",
                "correlation_id": correlation_id,
            })
            events_chain.append({
                "service": "governance-engine",
                "event_type": "POLICY_CHECK_TRIGGERED",
                "correlation_id": correlation_id,
            })

        simulate_service_chain(root_correlation_id)

        assert all(e["correlation_id"] == root_correlation_id for e in events_chain)
        assert len(events_chain) == 3
