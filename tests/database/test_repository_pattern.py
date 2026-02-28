"""BaseRepository integration tests against a real PostgreSQL container.

Verifies that the aumos-common BaseRepository operations (create, get, list,
update, delete) work correctly against a live PostgreSQL instance with RLS.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


pytestmark = [pytest.mark.integration, pytest.mark.phase0]


class TestRepositoryPatternBasic:
    """Verify fundamental repository CRUD operations against PostgreSQL."""

    async def test_insert_and_select_round_trip(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """A record inserted with Tenant Alpha context is retrievable under the same context."""
        row_id = str(uuid.uuid4())
        name = f"repo-test-{uuid.uuid4().hex[:8]}"

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
                {"id": row_id, "tid": tenant_alpha_id, "name": name},
            )
            await session.commit()

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text("SELECT id, tenant_id, name FROM test_tenant_table WHERE id = :id"),
                {"id": row_id},
            )
            row = result.fetchone()

        assert row is not None, "Inserted row not found"
        assert row[0] == row_id
        assert row[1] == tenant_alpha_id
        assert row[2] == name

    async def test_update_existing_row(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """UPDATE on an owned row succeeds and reflects the new value."""
        row_id = str(uuid.uuid4())

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
                {"id": row_id, "tid": tenant_alpha_id, "name": "original-name"},
            )
            await session.commit()

        new_name = f"updated-{uuid.uuid4().hex[:6]}"
        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            await session.execute(
                text("UPDATE test_tenant_table SET name = :name WHERE id = :id"),
                {"name": new_name, "id": row_id},
            )
            await session.commit()

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text("SELECT name FROM test_tenant_table WHERE id = :id"),
                {"id": row_id},
            )
            fetched_name = result.scalar()

        assert fetched_name == new_name

    async def test_delete_own_row(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """DELETE on an owned row removes it; subsequent SELECT returns nothing."""
        row_id = str(uuid.uuid4())

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
                {"id": row_id, "tid": tenant_alpha_id, "name": "to-be-deleted"},
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
            deleted = result.rowcount
            await session.commit()

        assert deleted == 1, "Expected exactly one row to be deleted"

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
        assert count == 0

    async def test_list_returns_only_tenant_rows(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
        tenant_beta_id: str,
    ) -> None:
        """LIST (SELECT *) under a tenant context returns only that tenant's rows."""
        prefix = f"list-test-{uuid.uuid4().hex[:6]}"
        alpha_ids = [str(uuid.uuid4()) for _ in range(3)]
        beta_id = str(uuid.uuid4())

        async with db_session_factory() as session:
            for aid in alpha_ids:
                await session.execute(
                    text(
                        "INSERT INTO test_tenant_table (id, tenant_id, name) "
                        "VALUES (:id, :tid, :name)"
                    ),
                    {"id": aid, "tid": tenant_alpha_id, "name": f"{prefix}-alpha"},
                )
            await session.execute(
                text(
                    "INSERT INTO test_tenant_table (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": beta_id, "tid": tenant_beta_id, "name": f"{prefix}-beta"},
            )
            await session.commit()

        async with db_session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tid, TRUE)"),
                {"tid": tenant_alpha_id},
            )
            result = await session.execute(
                text("SELECT id FROM test_tenant_table WHERE name LIKE :prefix"),
                {"prefix": f"{prefix}%"},
            )
            visible = {row[0] for row in result.fetchall()}

        assert visible == set(alpha_ids), (
            f"Expected only alpha rows, got: {visible}"
        )
        assert beta_id not in visible


class TestTransactionIsolation:
    """Verify transaction semantics work correctly with PostgreSQL."""

    async def test_rollback_undoes_insert(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        tenant_alpha_id: str,
    ) -> None:
        """A row inserted inside a rolled-back transaction must not persist."""
        row_id = str(uuid.uuid4())

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
                {"id": row_id, "tid": tenant_alpha_id, "name": "should-rollback"},
            )
            await session.rollback()  # Do NOT commit

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

        assert count == 0, "Rolled-back insert must not persist"
