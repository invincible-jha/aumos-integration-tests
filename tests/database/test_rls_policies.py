"""Comprehensive RLS policy tests against a real PostgreSQL container.

Verifies that the RLS policy framework works correctly:
- Policies exist and are enabled (pg_policies, pg_class)
- Row filtering is enforced by the database engine, not application code
- INSERT WITH CHECK prevents cross-tenant data injection
- DELETE filtering prevents cross-tenant row removal
- Multi-tenant data partitioning is correct
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


pytestmark = [pytest.mark.integration, pytest.mark.phase0]


class TestRLSPolicyCatalog:
    """Verify RLS policy metadata in PostgreSQL system catalogs."""

    async def test_tenant_table_has_rls_enabled(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """test_tenant_table must have relrowsecurity=true in pg_class."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'test_tenant_table'"
                )
            )
            row = result.fetchone()
        assert row is not None, "test_tenant_table not in pg_class"
        assert row[0] is True, "relrowsecurity must be enabled"
        assert row[1] is True, "relforcerowsecurity must be enabled"

    async def test_tenant_isolation_policy_exists(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """tenant_isolation policy must exist in pg_policies."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT policyname, cmd, qual IS NOT NULL AS has_using, "
                    "with_check IS NOT NULL AS has_with_check "
                    "FROM pg_policies WHERE tablename = 'test_tenant_table'"
                )
            )
            policies = result.fetchall()

        assert len(policies) >= 1, "No RLS policy found on test_tenant_table"
        policy_map = {p[0]: p for p in policies}
        assert "tenant_isolation" in policy_map, (
            f"Expected 'tenant_isolation' policy, found: {list(policy_map.keys())}"
        )
        policy = policy_map["tenant_isolation"]
        assert policy[2] is True, "Policy must have USING clause"
        assert policy[3] is True, "Policy must have WITH CHECK clause"

    async def test_pgvector_extension_installed(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """pgvector extension must be installed for vector embedding support."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT extname FROM pg_extension WHERE extname = 'vector'"
                )
            )
            row = result.fetchone()
        assert row is not None, "pgvector extension not installed"


class TestRLSRowFiltering:
    """Verify row-level filtering by tenant at the database engine level."""

    async def test_cross_tenant_select_returns_zero_rows(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """When context is Tenant Alpha, rows owned by Tenant Beta are invisible."""
        row_id = str(uuid.uuid4())
        async with db_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO test_tenant_table (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": row_id, "tid": tenant_beta_id, "name": "beta-only"},
            )
            await session.commit()

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text("SELECT COUNT(*) FROM test_tenant_table WHERE id = :id"),
                {"id": row_id},
            )
            count = result.scalar()

        assert count == 0, f"RLS cross-tenant leak: count={count}"

    async def test_tenant_sees_own_rows_only(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
        tenant_gamma_id: str,
    ) -> None:
        """Each tenant sees exactly their own rows — no more, no less."""
        # Insert one row per tenant
        alpha_id = str(uuid.uuid4())
        beta_id = str(uuid.uuid4())
        gamma_id = str(uuid.uuid4())
        prefix = f"scope-test-{uuid.uuid4().hex[:6]}"

        async with db_session_factory() as session:
            for row_id, tenant_id in [
                (alpha_id, tenant_alpha_id),
                (beta_id, tenant_beta_id),
                (gamma_id, tenant_gamma_id),
            ]:
                await session.execute(
                    text(
                        "INSERT INTO test_tenant_table (id, tenant_id, name) "
                        "VALUES (:id, :tid, :name)"
                    ),
                    {"id": row_id, "tid": tenant_id, "name": f"{prefix}-{tenant_id[:8]}"},
                )
            await session.commit()

        for tenant_id, own_id in [
            (tenant_alpha_id, alpha_id),
            (tenant_beta_id, beta_id),
            (tenant_gamma_id, gamma_id),
        ]:
            async with db_session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                    {"tid": tenant_id},
                )
                result = await session.execute(
                    text(
                        "SELECT id FROM test_tenant_table "
                        "WHERE name LIKE :prefix"
                    ),
                    {"prefix": f"{prefix}%"},
                )
                visible_ids = {row[0] for row in result.fetchall()}

            assert own_id in visible_ids, (
                f"Tenant {tenant_id[:8]} cannot see its own row"
            )
            other_ids = {alpha_id, beta_id, gamma_id} - {own_id}
            assert visible_ids.isdisjoint(other_ids), (
                f"Tenant {tenant_id[:8]} sees foreign rows: {visible_ids & other_ids}"
            )

    async def test_delete_cannot_remove_foreign_tenant_row(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """DELETE with Tenant Alpha context cannot remove Tenant Beta's row."""
        row_id = str(uuid.uuid4())
        async with db_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO test_tenant_table (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": row_id, "tid": tenant_beta_id, "name": "beta-protected"},
            )
            await session.commit()

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text("DELETE FROM test_tenant_table WHERE id = :id"),
                {"id": row_id},
            )
            rows_deleted = result.rowcount
            await session.commit()

        assert rows_deleted == 0, (
            f"RLS violation: Tenant Alpha deleted Tenant Beta's row"
        )

    async def test_without_tenant_context_returns_empty(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """Queries without setting app.current_tenant return no rows (empty string context)."""
        row_id = str(uuid.uuid4())
        async with db_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO test_tenant_table (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": row_id, "tid": tenant_alpha_id, "name": "no-context-test"},
            )
            await session.commit()

        async with db_session_factory() as session:
            # Intentionally do NOT set app.current_tenant — RLS should return empty
            result = await session.execute(
                text("SELECT COUNT(*) FROM test_tenant_table WHERE id = :id"),
                {"id": row_id},
            )
            count = result.scalar()

        # With no tenant context, current_setting returns '' which won't match any tenant_id
        assert count == 0, (
            f"Query without tenant context returned rows (count={count})"
        )


class TestRLSInsertWithCheck:
    """Verify the WITH CHECK clause prevents cross-tenant inserts."""

    async def test_insert_wrong_tenant_id_rejected(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """INSERT with tenant_id != session context must be rejected by WITH CHECK."""
        from sqlalchemy.exc import DBAPIError

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO test_tenant_table (id, tenant_id, name) "
                        "VALUES (:id, :tid, :name)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tid": tenant_beta_id,
                        "name": "injection-attempt",
                    },
                )
                await session.commit()
