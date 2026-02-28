"""Alembic migration smoke tests against a real PostgreSQL container.

Verifies that:
- The database schema setup in conftest.py (simulating Alembic head) is correct
- pgvector extension is present
- Expected tables exist with correct structure
- Standard AumOS functions (set_tenant_context) are installed
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


pytestmark = [pytest.mark.integration, pytest.mark.phase0]


class TestMigrationSmoke:
    """Verify the baseline schema is correctly installed."""

    async def test_test_tenant_table_exists(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """test_tenant_table must exist in the public schema."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'test_tenant_table'"
                )
            )
            row = result.fetchone()
        assert row is not None, "test_tenant_table does not exist"

    async def test_tenants_table_exists(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """tenants table must exist (seeded by conftest.py schema setup)."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'tenants'"
                )
            )
            row = result.fetchone()
        assert row is not None, "tenants table does not exist"

    async def test_set_tenant_context_function_exists(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """set_tenant_context() PL/pgSQL function must be installed."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT routine_name FROM information_schema.routines "
                    "WHERE routine_schema = 'public' "
                    "AND routine_name = 'set_tenant_context'"
                )
            )
            row = result.fetchone()
        assert row is not None, "set_tenant_context function not installed"

    async def test_set_tenant_context_function_works(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """set_tenant_context() must correctly set app.current_tenant configuration."""
        test_tenant_id = "migration-smoke-test-tenant"
        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_tenant_context(:tid)"),
                {"tid": test_tenant_id},
            )
            result = await session.execute(
                text("SELECT current_setting('app.current_tenant', TRUE)")
            )
            value = result.scalar()
        assert value == test_tenant_id, (
            f"set_tenant_context set wrong value: {value!r}"
        )

    async def test_pgvector_extension_available(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """pgvector must be installed and the vector type must be usable."""
        async with db_session_factory() as session:
            # If pgvector is installed, this CAST should succeed
            result = await session.execute(
                text("SELECT '[1.0, 2.0, 3.0]'::vector(3)")
            )
            value = result.scalar()
        assert value is not None, "pgvector vector type not working"

    async def test_test_tenant_table_columns(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """test_tenant_table must have the expected columns: id, tenant_id, name, created_at."""
        expected_columns = {"id", "tenant_id", "name", "created_at"}
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'test_tenant_table' "
                    "AND table_schema = 'public'"
                )
            )
            actual_columns = {row[0] for row in result.fetchall()}
        assert expected_columns <= actual_columns, (
            f"Missing columns: {expected_columns - actual_columns}"
        )

    async def test_rls_policy_survives_reconnection(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """RLS policies persist across connections — they are stored in the catalog."""
        # Open a fresh connection and verify the policy is still there
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM pg_policies "
                    "WHERE tablename = 'test_tenant_table'"
                )
            )
            count = result.scalar()
        assert count >= 1, "RLS policy missing after reconnection"
