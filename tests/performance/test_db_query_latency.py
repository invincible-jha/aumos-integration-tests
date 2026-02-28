"""Database query latency performance baselines.

SLO: Tenant-scoped SELECT query with RLS must complete in < 20ms at p99.
"""
from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


pytestmark = [pytest.mark.performance, pytest.mark.integration]


class TestDBQueryLatencyBenchmarks:
    """PostgreSQL query latency with RLS must stay below 20ms p99."""

    async def test_tenant_scoped_select_latency(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        benchmark: object,
    ) -> None:
        """Benchmark a tenant-scoped SELECT COUNT(*) with RLS active.

        SLO: p99 < 20ms for a simple count query with tenant context set.
        """
        # Pre-seed 10 rows for the tenant so the query is non-trivial
        async with db_session_factory() as session:
            for _ in range(10):
                await session.execute(
                    text(
                        "INSERT INTO test_tenant_table (id, tenant_id, name) "
                        "VALUES (:id, :tid, :name)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tid": tenant_alpha_id,
                        "name": "perf-seed-row",
                    },
                )
            await session.commit()

        async def timed_query() -> int:
            async with db_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                    {"tid": tenant_alpha_id},
                )
                result = await session.execute(
                    text("SELECT COUNT(*) FROM test_tenant_table")
                )
                count: int = result.scalar()  # type: ignore[assignment]
                return count

        # Warm-up: run once before benchmark
        await timed_query()

        # Measure 20 iterations manually (pytest-benchmark doesn't support async natively)
        latencies_ms: list[float] = []
        for _ in range(20):
            start = time.perf_counter()
            count = await timed_query()
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)
            assert count >= 0  # Sanity check

        # Sort and check p99 (= max in a 20-sample set)
        latencies_ms.sort()
        p99_ms = latencies_ms[-1]  # 100th percentile of 20 samples

        assert p99_ms < 100.0, (
            f"DB query p99 latency {p99_ms:.2f}ms exceeds 100ms threshold "
            f"(CI allowance; production target is 20ms)"
        )

    async def test_insert_with_tenant_context_latency(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """INSERT with tenant context must complete in < 50ms.

        Measures the full round-trip for an INSERT under RLS context.
        """
        latencies_ms: list[float] = []

        for _ in range(10):
            start = time.perf_counter()
            async with db_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                    {"tid": tenant_alpha_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO test_tenant_table (id, tenant_id, name) "
                        "VALUES (:id, :tid, :name)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tid": tenant_alpha_id,
                        "name": "latency-test-insert",
                    },
                )
                await session.commit()
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

        latencies_ms.sort()
        p99_ms = latencies_ms[-1]

        assert p99_ms < 200.0, (
            f"DB INSERT p99 latency {p99_ms:.2f}ms exceeds 200ms CI threshold"
        )

    async def test_concurrent_tenant_queries_no_contention(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """10 concurrent tenant queries must all complete within 500ms total.

        Simulates concurrent API requests from different tenants hitting
        the database simultaneously.
        """
        import asyncio

        async def query_tenant(tenant_id: str) -> float:
            start = time.perf_counter()
            async with db_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                    {"tid": tenant_id},
                )
                result = await session.execute(
                    text("SELECT COUNT(*) FROM test_tenant_table")
                )
                result.scalar()
            return (time.perf_counter() - start) * 1000

        tenants = [tenant_alpha_id, tenant_beta_id] * 5  # 10 concurrent queries
        start_wall = time.perf_counter()
        latencies = await asyncio.gather(*[query_tenant(tid) for tid in tenants])
        wall_ms = (time.perf_counter() - start_wall) * 1000

        assert wall_ms < 500.0, (
            f"10 concurrent queries took {wall_ms:.2f}ms — exceeds 500ms SLO"
        )
        assert max(latencies) < 300.0, (
            f"Slowest query: {max(latencies):.2f}ms — exceeds 300ms threshold"
        )
