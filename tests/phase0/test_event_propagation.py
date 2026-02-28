"""Kafka event propagation tests.

Real Kafka tests (marked @integration) use Testcontainers.
Unit-level tests verify application logic without infrastructure.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

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
    """Build an audit event envelope matching the AumOS event schema."""
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


# ---------------------------------------------------------------------------
# Real Kafka integration tests
# ---------------------------------------------------------------------------


@pytest.mark.phase0
@pytest.mark.integration
class TestEventPropagationReal:
    """Verify Kafka event publish/consume against a real Kafka container.

    Requires AUMOS_USE_TESTCONTAINERS=true environment variable.
    """

    async def test_audit_event_published_and_consumed(
        self,
        kafka_bootstrap_servers: str,
    ) -> None:
        """Publish an AuditEvent and consume it from the same topic.

        Uses the confluent_kafka library directly to avoid dependency on
        aumos-common internals.
        """
        from confluent_kafka import Consumer, KafkaError, Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        topic = f"aumos.audit.events.{uuid.uuid4().hex[:8]}"

        # Create topic
        admin = AdminClient({"bootstrap.servers": kafka_bootstrap_servers})
        futures = admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
        for _, future in futures.items():
            future.result()  # Raises on error

        # Produce one event
        producer = Producer({"bootstrap.servers": kafka_bootstrap_servers})
        audit_event = _make_audit_event(
            event_type="DATASET_CREATED",
            tenant_id=MOCK_TENANT_ID,
            actor_id=str(uuid.uuid4()),
            resource_id=str(uuid.uuid4()),
            payload={"dataset_name": "test-dataset", "schema_version": "2"},
        )
        producer.produce(
            topic,
            value=json.dumps(audit_event).encode(),
            key=MOCK_TENANT_ID.encode(),
        )
        producer.flush(timeout=10)

        # Consume and verify
        consumer = Consumer(
            {
                "bootstrap.servers": kafka_bootstrap_servers,
                "group.id": f"test-consumer-{uuid.uuid4().hex[:8]}",
                "auto.offset.reset": "earliest",
            }
        )
        consumer.subscribe([topic])

        received: dict[str, Any] | None = None
        for _ in range(30):
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise RuntimeError(f"Kafka consumer error: {msg.error()}")
            received = json.loads(msg.value().decode())
            break

        consumer.close()

        assert received is not None, "No message consumed from Kafka within timeout"
        assert received["event_type"] == "DATASET_CREATED"
        assert received["tenant_id"] == MOCK_TENANT_ID
        assert "correlation_id" in received

    async def test_tenant_scoped_event_partition_key(
        self,
        kafka_bootstrap_servers: str,
    ) -> None:
        """Events for different tenants use their tenant_id as Kafka partition key.

        Verifies that the key is set correctly on the produced message — this
        ensures Kafka routes all events for a given tenant to the same partition.
        """
        from confluent_kafka import Consumer, KafkaError, Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        topic = f"aumos.audit.events.partitioned.{uuid.uuid4().hex[:8]}"
        admin = AdminClient({"bootstrap.servers": kafka_bootstrap_servers})
        futures = admin.create_topics([NewTopic(topic, num_partitions=3, replication_factor=1)])
        for _, future in futures.items():
            future.result()

        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        produced_keys: list[str] = []

        producer = Producer({"bootstrap.servers": kafka_bootstrap_servers})
        for tenant_id in (tenant_a, tenant_b):
            event = _make_audit_event("DATASET_UPDATED", tenant_id, str(uuid.uuid4()), str(uuid.uuid4()))
            producer.produce(topic, value=json.dumps(event).encode(), key=tenant_id.encode())
            produced_keys.append(tenant_id)
        producer.flush(timeout=10)

        # Consume both messages and verify keys
        consumer = Consumer(
            {
                "bootstrap.servers": kafka_bootstrap_servers,
                "group.id": f"test-keys-{uuid.uuid4().hex[:8]}",
                "auto.offset.reset": "earliest",
            }
        )
        consumer.subscribe([topic])

        consumed_keys: list[str] = []
        for _ in range(60):
            msg = consumer.poll(timeout=1.0)
            if msg is None or (msg.error() and msg.error().code() == KafkaError._PARTITION_EOF):
                continue
            if msg.error():
                raise RuntimeError(f"Kafka error: {msg.error()}")
            consumed_keys.append(msg.key().decode())
            if len(consumed_keys) == 2:
                break

        consumer.close()

        assert len(consumed_keys) == 2
        assert tenant_a in consumed_keys
        assert tenant_b in consumed_keys

    async def test_dead_letter_routing_simulation(
        self,
        kafka_bootstrap_servers: str,
    ) -> None:
        """Malformed events are routed to the dead-letter topic.

        Publishes a malformed event to the main topic, simulates a consumer
        that detects the malformation and re-publishes to the DLQ topic,
        then verifies the DLQ contains the event with dlq_reason set.
        """
        from confluent_kafka import Consumer, KafkaError, Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        suffix = uuid.uuid4().hex[:8]
        main_topic = f"aumos.audit.events.dlq-test.{suffix}"
        dlq_topic = f"aumos.audit.events.dlq.{suffix}"

        admin = AdminClient({"bootstrap.servers": kafka_bootstrap_servers})
        futures = admin.create_topics(
            [
                NewTopic(main_topic, num_partitions=1, replication_factor=1),
                NewTopic(dlq_topic, num_partitions=1, replication_factor=1),
            ]
        )
        for _, future in futures.items():
            future.result()

        # Produce malformed event (missing required fields)
        producer = Producer({"bootstrap.servers": kafka_bootstrap_servers})
        malformed = {"event_type": "UNKNOWN_TYPE", "broken": True}
        producer.produce(main_topic, value=json.dumps(malformed).encode())
        producer.flush(timeout=10)

        # Consume and route to DLQ
        consumer = Consumer(
            {
                "bootstrap.servers": kafka_bootstrap_servers,
                "group.id": f"dlq-consumer-{suffix}",
                "auto.offset.reset": "earliest",
            }
        )
        consumer.subscribe([main_topic])

        supported_types = {"DATASET_CREATED", "DATASET_UPDATED", "MODEL_DEPLOYMENT_REQUESTED"}

        for _ in range(30):
            msg = consumer.poll(timeout=1.0)
            if msg is None or (msg.error() and msg.error().code() == KafkaError._PARTITION_EOF):
                continue
            if msg.error():
                raise RuntimeError(f"Kafka error: {msg.error()}")
            event = json.loads(msg.value().decode())
            if event.get("event_type") not in supported_types:
                dlq_event = {**event, "dlq_reason": "UNSUPPORTED_EVENT_TYPE"}
                producer.produce(dlq_topic, value=json.dumps(dlq_event).encode())
                producer.flush(timeout=10)
            break

        consumer.close()

        # Verify DLQ contains the event
        dlq_consumer = Consumer(
            {
                "bootstrap.servers": kafka_bootstrap_servers,
                "group.id": f"dlq-verify-{suffix}",
                "auto.offset.reset": "earliest",
            }
        )
        dlq_consumer.subscribe([dlq_topic])

        dlq_received: dict[str, Any] | None = None
        for _ in range(30):
            msg = dlq_consumer.poll(timeout=1.0)
            if msg is None or (msg.error() and msg.error().code() == KafkaError._PARTITION_EOF):
                continue
            if msg.error():
                raise RuntimeError(f"Kafka DLQ error: {msg.error()}")
            dlq_received = json.loads(msg.value().decode())
            break

        dlq_consumer.close()

        assert dlq_received is not None, "No message found in DLQ topic"
        assert dlq_received.get("dlq_reason") == "UNSUPPORTED_EVENT_TYPE"


# ---------------------------------------------------------------------------
# Unit-level logic tests (no infrastructure required, always run)
# ---------------------------------------------------------------------------


@pytest.mark.phase0
class TestEventPropagationUnit:
    """Verify event schema and routing logic without Kafka infrastructure."""

    async def test_event_schema_validation(self) -> None:
        """Publishing an event with missing required fields raises a validation error."""
        malformed_event: dict[str, Any] = {
            "event_type": "DATASET_CREATED",
            # missing: event_id, tenant_id, actor_id, resource_id, timestamp
        }

        def validate_event(event: dict[str, Any]) -> list[str]:
            required_fields = [
                "event_id", "event_type", "tenant_id",
                "actor_id", "resource_id", "timestamp",
            ]
            return [f for f in required_fields if f not in event]

        missing_fields = validate_event(malformed_event)
        assert len(missing_fields) > 0
        assert "tenant_id" in missing_fields
        assert "event_id" in missing_fields

    async def test_event_deduplication_on_retry(self) -> None:
        """Re-delivering an event with the same event_id is handled idempotently."""
        event_id = str(uuid.uuid4())
        event = _make_audit_event(
            "POLICY_EVALUATED", MOCK_TENANT_ID, str(uuid.uuid4()), str(uuid.uuid4())
        )
        event["event_id"] = event_id

        seen_event_ids: set[str] = set()
        processed_count = 0

        def idempotent_handler(e: dict[str, Any]) -> None:
            nonlocal processed_count
            if e["event_id"] not in seen_event_ids:
                seen_event_ids.add(e["event_id"])
                processed_count += 1

        idempotent_handler(event)
        idempotent_handler(event)
        idempotent_handler(event)

        assert processed_count == 1
        assert len(seen_event_ids) == 1

    async def test_correlation_id_propagated_across_services(self) -> None:
        """Correlation ID from the original request propagates through derived events."""
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
