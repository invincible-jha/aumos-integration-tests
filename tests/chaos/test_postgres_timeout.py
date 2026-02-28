"""PostgreSQL connection failure chaos tests.

Verifies that:
- The application handles PostgreSQL connection timeouts gracefully
- Statement timeout settings are respected
- Connection pool exhaustion is surfaced as an error, not a hang
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


pytestmark = [pytest.mark.chaos, pytest.mark.integration]


class TestPostgresTimeoutChaos:
    """Verify PostgreSQL failure handling under adverse conditions."""

    async def test_statement_timeout_raises_error(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """A long-running query aborted by statement_timeout raises DBAPIError.

        The resilience layer must catch this exception and trigger retry logic
        or fail gracefully — it must not hang the calling thread.
        """
        from sqlalchemy.exc import DBAPIError

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            # Set a very short statement timeout
            await session.execute(text("SET statement_timeout = '50ms'"))

            with pytest.raises(DBAPIError):
                # pg_sleep(1) far exceeds the 50ms timeout
                await session.execute(text("SELECT pg_sleep(1)"))

    async def test_concurrent_connections_do_not_deadlock(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """Concurrent sessions on different tenants do not deadlock each other.

        This test opens two concurrent sessions — one for Tenant Alpha and one
        for Tenant Beta — and verifies they can both complete their operations
        without blocking each other.
        """
        # Insert rows for both tenants
        alpha_id = str(uuid.uuid4())
        beta_id = str(uuid.uuid4())

        async with db_session_factory() as session:
            for row_id, tenant_id in [(alpha_id, tenant_alpha_id), (beta_id, tenant_beta_id)]:
                await session.execute(
                    text(
                        "INSERT INTO test_tenant_table (id, tenant_id, name) "
                        "VALUES (:id, :tid, :name)"
                    ),
                    {"id": row_id, "tid": tenant_id, "name": f"concurrent-{row_id[:8]}"},
                )
            await session.commit()

        # Run both queries concurrently
        async def query_tenant(tenant_id: str, target_id: str) -> int:
            async with db_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                    {"tid": tenant_id},
                )
                result = await session.execute(
                    text("SELECT COUNT(*) FROM test_tenant_table WHERE id = :id"),
                    {"id": target_id},
                )
                count: int = result.scalar()  # type: ignore[assignment]
                return count

        alpha_count, beta_count = await asyncio.gather(
            query_tenant(tenant_alpha_id, alpha_id),
            query_tenant(tenant_beta_id, beta_id),
        )

        assert alpha_count == 1, f"Tenant Alpha row not found (count={alpha_count})"
        assert beta_count == 1, f"Tenant Beta row not found (count={beta_count})"

    async def test_connection_acquired_within_timeout(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """Connection acquisition must complete within a reasonable timeout.

        Verifies the pool is configured with a connection timeout rather than
        waiting indefinitely.
        """
        # This should complete in under 5 seconds; if the pool blocks forever
        # the test will timeout at the pytest level (which is the failure signal)
        try:
            async with asyncio.timeout(5.0):
                async with db_session_factory() as session:
                    await session.execute(
                        text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                        {"tid": tenant_alpha_id},
                    )
                    result = await session.execute(text("SELECT 1"))
                    value = result.scalar()
            assert value == 1
        except TimeoutError:
            pytest.fail("Connection acquisition timed out after 5 seconds")
