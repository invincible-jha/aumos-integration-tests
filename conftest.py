"""Root conftest — real infrastructure fixtures using Testcontainers.

Provides session-scoped PostgreSQL, Kafka, and Redis containers so integration
tests connect to genuine infrastructure rather than mocks.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to suppress PytestUnknownMarkWarning."""
    config.addinivalue_line("markers", "phase0: Foundation integration tests")
    config.addinivalue_line("markers", "phase1: Data Factory integration tests")
    config.addinivalue_line("markers", "phase2: DevOps + Trust integration tests")
    config.addinivalue_line("markers", "smoke: Quick smoke tests")
    config.addinivalue_line("markers", "integration: Requires real infrastructure containers")
    config.addinivalue_line("markers", "contract: Pact consumer contract tests")
    config.addinivalue_line("markers", "chaos: Chaos and fault-injection tests")
    config.addinivalue_line("markers", "performance: Performance baseline tests")


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip tests that require services unless real infrastructure is available."""
    skip_no_services = pytest.mark.skip(reason="Services not available — start docker compose first")
    skip_no_containers = pytest.mark.skip(reason="Testcontainers disabled — set AUMOS_USE_TESTCONTAINERS=true")

    services_required = os.getenv("AUMOS_SERVICES_RUNNING", "false").lower() == "true"
    use_testcontainers = os.getenv("AUMOS_USE_TESTCONTAINERS", "false").lower() == "true"

    for item in items:
        # smoke/phase tests require either services or testcontainers
        if any(mark in item.keywords for mark in ("smoke", "phase0", "phase1", "phase2")):
            if not services_required and not use_testcontainers:
                item.add_marker(skip_no_services)
        # integration/chaos/performance require testcontainers
        if any(mark in item.keywords for mark in ("integration", "chaos", "performance")):
            if not use_testcontainers:
                item.add_marker(skip_no_containers)


# ---------------------------------------------------------------------------
# Container fixtures (session-scoped — start once, share across all tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Start a real PostgreSQL container for the entire test session.

    Uses pgvector/pgvector:pg16 to match production configuration.
    Container is started once and shared across all tests for speed.
    """
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def kafka_container() -> Generator[KafkaContainer, None, None]:
    """Start a real Kafka container for the entire test session.

    Uses confluentinc/cp-kafka:7.6.0 to match docker-compose.integration.yml.
    """
    with KafkaContainer("confluentinc/cp-kafka:7.6.0") as kafka:
        yield kafka


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    """Start a real Redis container for the entire test session.

    Uses redis:7.2-alpine to match production configuration.
    """
    with RedisContainer("redis:7.2-alpine") as redis_tc:
        yield redis_tc


# ---------------------------------------------------------------------------
# Database engine + session fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def db_engine(postgres_container: PostgresContainer) -> AsyncGenerator[object, None]:
    """Create async SQLAlchemy engine connected to the test PostgreSQL container.

    Applies the AumOS base schema including the tenant context function and
    a minimal test_tenant_table with RLS enabled.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    engine: AsyncEngine = create_async_engine(url, echo=False, pool_pre_ping=True)

    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Create tenant context function used by RLS policies
        await conn.execute(
            text("""
                CREATE OR REPLACE FUNCTION set_tenant_context(tenant_id TEXT) RETURNS VOID AS $$
                BEGIN
                    PERFORM set_config('app.current_tenant', tenant_id, TRUE);
                END;
                $$ LANGUAGE plpgsql;
            """)
        )

        # Create a minimal tenant-scoped table for RLS verification tests
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS test_tenant_table (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        )

        # Enable RLS on the test table
        await conn.execute(
            text("ALTER TABLE test_tenant_table ENABLE ROW LEVEL SECURITY")
        )
        await conn.execute(
            text("ALTER TABLE test_tenant_table FORCE ROW LEVEL SECURITY")
        )

        # Create RLS policy: rows visible only to the current tenant
        await conn.execute(
            text("""
                DROP POLICY IF EXISTS tenant_isolation ON test_tenant_table;
                CREATE POLICY tenant_isolation ON test_tenant_table
                    USING (tenant_id = current_setting('app.current_tenant', TRUE))
                    WITH CHECK (tenant_id = current_setting('app.current_tenant', TRUE));
            """)
        )

        # Create test tenant seed data table
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        )

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def db_session_factory(db_engine: object) -> object:
    """Return an async sessionmaker bound to the test engine.

    Each test should open its own session via `async with db_session_factory() as session`.
    Use transaction rollback (not table truncation) for test isolation.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, AsyncEngine

    engine: AsyncEngine = db_engine  # type: ignore[assignment]
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory


# ---------------------------------------------------------------------------
# Convenience fixtures for test data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def tenant_alpha_id() -> str:
    """Stable UUID for Tenant Alpha across all test runs."""
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="session")
def tenant_beta_id() -> str:
    """Stable UUID for Tenant Beta across all test runs."""
    return "00000000-0000-0000-0000-000000000002"


@pytest.fixture(scope="session")
def tenant_gamma_id() -> str:
    """Stable UUID for Tenant Gamma across all test runs."""
    return "00000000-0000-0000-0000-000000000003"


# ---------------------------------------------------------------------------
# Kafka connection URL fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def kafka_bootstrap_servers(kafka_container: KafkaContainer) -> str:
    """Return the bootstrap server URL for the test Kafka container."""
    return kafka_container.get_bootstrap_server()


# ---------------------------------------------------------------------------
# Redis connection URL fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def redis_url(redis_container: RedisContainer) -> str:
    """Return the Redis connection URL for the test Redis container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"
