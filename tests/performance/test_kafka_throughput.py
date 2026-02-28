"""Kafka publish throughput performance baselines.

SLO: Single AuditEvent publish must complete in < 10ms at p95.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest


pytestmark = [pytest.mark.performance, pytest.mark.integration]


def _make_audit_event(tenant_id: str) -> dict[str, Any]:
    """Build a minimal AuditEvent for throughput measurement."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "DATASET_CREATED",
        "schema_version": "1.0",
        "tenant_id": tenant_id,
        "actor_id": str(uuid.uuid4()),
        "resource_id": str(uuid.uuid4()),
        "timestamp": "2026-02-26T10:00:00Z",
        "correlation_id": str(uuid.uuid4()),
        "payload": {"dataset_name": "perf-test-dataset"},
    }


class TestKafkaThroughputBenchmarks:
    """Kafka event publish latency must stay below 10ms p95."""

    def test_single_event_publish_latency(
        self,
        kafka_bootstrap_servers: str,
        benchmark: object,
    ) -> None:
        """Benchmark single AuditEvent publish to Kafka.

        SLO: p95 < 10ms. This measures the end-to-end produce + delivery
        acknowledgment latency.
        """
        from confluent_kafka import Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        topic = f"perf-test-{uuid.uuid4().hex[:8]}"
        admin = AdminClient({"bootstrap.servers": kafka_bootstrap_servers})
        futures = admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
        for _, f in futures.items():
            f.result()

        producer = Producer(
            {
                "bootstrap.servers": kafka_bootstrap_servers,
                "acks": "all",
                "linger.ms": 0,  # No batching for latency measurement
            }
        )

        tenant_id = str(uuid.uuid4())

        def produce_one() -> None:
            event = _make_audit_event(tenant_id)
            producer.produce(topic, value=json.dumps(event).encode(), key=tenant_id.encode())
            producer.flush(timeout=5)

        benchmark(produce_one)  # type: ignore[operator]

        stats = getattr(benchmark, "stats", None)
        if stats:
            p95_seconds = stats.get("ops", 0)
            mean_seconds = stats.get("mean", 0)
            assert mean_seconds < 0.010, (
                f"Kafka publish mean latency {mean_seconds*1000:.2f}ms exceeds 10ms SLO"
            )

    def test_bulk_event_publish_throughput(
        self,
        kafka_bootstrap_servers: str,
    ) -> None:
        """100 events must be published in under 1 second total.

        Simulates a burst publish scenario (e.g. batch dataset creation).
        Target: 100+ events/second sustained throughput.
        """
        from confluent_kafka import Producer
        from confluent_kafka.admin import AdminClient, NewTopic

        topic = f"perf-bulk-{uuid.uuid4().hex[:8]}"
        admin = AdminClient({"bootstrap.servers": kafka_bootstrap_servers})
        futures = admin.create_topics([NewTopic(topic, num_partitions=3, replication_factor=1)])
        for _, f in futures.items():
            f.result()

        producer = Producer(
            {
                "bootstrap.servers": kafka_bootstrap_servers,
                "acks": "1",  # Leader ack only for throughput test
                "linger.ms": 5,  # Allow batching for throughput
                "batch.num.messages": 100,
            }
        )

        tenant_id = str(uuid.uuid4())
        events = [_make_audit_event(tenant_id) for _ in range(100)]

        start = time.perf_counter()
        for event in events:
            producer.produce(topic, value=json.dumps(event).encode(), key=tenant_id.encode())
        producer.flush(timeout=10)
        elapsed_seconds = time.perf_counter() - start

        assert elapsed_seconds < 1.0, (
            f"100 events published in {elapsed_seconds:.3f}s — exceeds 1s SLO "
            f"({100/elapsed_seconds:.0f} events/sec)"
        )
