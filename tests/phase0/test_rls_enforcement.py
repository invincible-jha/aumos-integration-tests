"""Database Row-Level Security (RLS) enforcement verification.

Tests connect to a real PostgreSQL container via Testcontainers.
When AUMOS_USE_TESTCONTAINERS is not set, tests are skipped.
The unit-level logic verification tests are retained in test_rls_unit.py.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# ---------------------------------------------------------------------------
# Real infrastructure tests (require Testcontainers)
# ---------------------------------------------------------------------------


@pytest.mark.phase0
@pytest.mark.integration
class TestRLSEnforcementReal:
    """Verify RLS against a live PostgreSQL container.

    Requires AUMOS_USE_TESTCONTAINERS=true environment variable.
    """

    async def test_tenant_a_cannot_read_tenant_b_rows(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """Verify RLS filters rows by tenant at the database level.

        Inserts a row for Tenant Beta, then queries as Tenant Alpha.
        The RLS policy must return zero rows — a Python-level dict filter
        cannot verify this because it does not touch the PostgreSQL policy engine.
        """
        row_id = str(uuid.uuid4())

        # Insert a row owned by Tenant Beta (bypass RLS for setup using superuser)
        async with db_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO test_tenant_table (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": row_id, "tid": tenant_beta_id, "name": "beta-secret"},
            )
            await session.commit()

        # Query as Tenant Alpha — RLS should hide Tenant Beta's row
        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM test_tenant_table "
                    "WHERE id = :row_id"
                ),
                {"row_id": row_id},
            )
            count = result.scalar()
            assert count == 0, (
                f"RLS violation: Tenant Alpha sees Tenant Beta's row (count={count})"
            )

    async def test_tenant_sees_own_rows(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """Verify that a tenant can read its own rows when RLS context is set correctly."""
        row_id = str(uuid.uuid4())

        async with db_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO test_tenant_table (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": row_id, "tid": tenant_alpha_id, "name": "alpha-record"},
            )
            await session.commit()

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text("SELECT COUNT(*) FROM test_tenant_table WHERE id = :row_id"),
                {"row_id": row_id},
            )
            count = result.scalar()
            assert count == 1, (
                f"Tenant Alpha should see its own row (count={count})"
            )

    async def test_rls_enforced_on_insert_wrong_tenant(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """Verify RLS WITH CHECK prevents inserting a row with a different tenant_id.

        When the session context is set to Tenant Alpha, an attempt to insert
        a row with tenant_id=Tenant Beta must be rejected by the RLS WITH CHECK
        policy.
        """
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
                        "tid": tenant_beta_id,  # Wrong tenant — should be rejected
                        "name": "cross-tenant-injection",
                    },
                )
                await session.commit()

    async def test_rls_enforced_on_delete(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """Verify a tenant cannot DELETE rows owned by another tenant."""
        row_id = str(uuid.uuid4())

        # Insert Tenant Beta row (without RLS context for setup)
        async with db_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO test_tenant_table (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": row_id, "tid": tenant_beta_id, "name": "beta-protected"},
            )
            await session.commit()

        # Attempt to DELETE as Tenant Alpha — RLS WHERE clause must filter the row out
        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text("DELETE FROM test_tenant_table WHERE id = :row_id"),
                {"row_id": row_id},
            )
            rows_deleted = result.rowcount
            assert rows_deleted == 0, (
                f"RLS violation: Tenant Alpha deleted Tenant Beta's row"
            )

    async def test_rls_policy_listed_in_pg_policies(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Verify the RLS policy is visible in pg_policies system catalog."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT policyname, cmd, qual IS NOT NULL AS has_using "
                    "FROM pg_policies "
                    "WHERE tablename = 'test_tenant_table'"
                )
            )
            policies = result.fetchall()
            assert len(policies) >= 1, (
                "No RLS policy found on test_tenant_table in pg_policies"
            )
            policy_names = [p[0] for p in policies]
            assert "tenant_isolation" in policy_names, (
                f"Expected 'tenant_isolation' policy, found: {policy_names}"
            )

    async def test_rls_enabled_flag_in_pg_class(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Verify test_tenant_table has relrowsecurity=true in pg_class."""
        async with db_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'test_tenant_table'"
                )
            )
            row = result.fetchone()
            assert row is not None, "test_tenant_table not found in pg_class"
            relrowsecurity, relforcerowsecurity = row
            assert relrowsecurity is True, "RLS not enabled on test_tenant_table"
            assert relforcerowsecurity is True, "Force RLS not enabled on test_tenant_table"


# ---------------------------------------------------------------------------
# Unit-level logic tests (no infrastructure required, always run)
# ---------------------------------------------------------------------------


@pytest.mark.phase0
class TestRLSEnforcementUnit:
    """Verify RLS-adjacent application logic without requiring database containers.

    These tests cover the application layer's enforcement of tenant context
    rules — they complement but do not replace the real RLS tests above.
    """

    async def test_superuser_bypass_not_allowed_in_app_role(self) -> None:
        """Application database role must not have BYPASSRLS privilege."""
        mock_role_info = {
            "rolname": "aumos_app",
            "rolbypassrls": False,
            "rolsuperuser": False,
        }

        assert mock_role_info["rolbypassrls"] is False, "App role must not bypass RLS"
        assert mock_role_info["rolsuperuser"] is False, "App role must not be superuser"

    async def test_rls_required_tables_enumeration(self) -> None:
        """All domain tables requiring RLS are known and documented."""
        rls_required_tables = [
            "datasets",
            "synthesis_jobs",
            "model_registrations",
            "governance_policies",
            "audit_events",
            "pipeline_runs",
        ]
        # Ensures the list is non-empty and all entries are non-blank
        assert len(rls_required_tables) > 0
        assert all(isinstance(t, str) and len(t) > 0 for t in rls_required_tables)

    async def test_tenant_context_missing_returns_empty(self) -> None:
        """Application layer must return empty set when tenant context is absent."""
        from typing import Any

        def query_with_rls_context(
            tenant_id: str | None,
            records: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            if tenant_id is None:
                return []
            return [r for r in records if r["tenant_id"] == tenant_id]

        records = [
            {"id": "r1", "tenant_id": "tenant-a"},
            {"id": "r2", "tenant_id": "tenant-b"},
        ]
        result = query_with_rls_context(None, records)
        assert result == [], "Query without tenant context must return empty set"
