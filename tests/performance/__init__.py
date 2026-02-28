"""Performance baseline tests using pytest-benchmark.

Asserts latency SLOs for critical AumOS operations:
- Auth token validation: p99 < 50ms under load
- Kafka event publish: p95 < 10ms per event
- PostgreSQL query with RLS: p99 < 20ms for tenant-scoped list
- Redis rate limit check: p95 < 5ms

All tests require AUMOS_USE_TESTCONTAINERS=true.
"""
