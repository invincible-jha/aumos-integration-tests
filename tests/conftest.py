"""Shared fixtures for AumOS integration tests."""
from __future__ import annotations

import os
import uuid
from typing import Any, AsyncGenerator

import httpx
import pytest
import pytest_asyncio


SERVICES_BASE_URL = os.getenv("AUMOS_SERVICES_URL", "http://localhost")

PLATFORM_CORE_PORT = int(os.getenv("PLATFORM_CORE_PORT", "8001"))
DATA_FACTORY_PORT = int(os.getenv("DATA_FACTORY_PORT", "8002"))
GOVERNANCE_PORT = int(os.getenv("GOVERNANCE_PORT", "8003"))
SECURITY_PORT = int(os.getenv("SECURITY_PORT", "8004"))
KEYCLOAK_PORT = int(os.getenv("KEYCLOAK_PORT", "8080"))
KAFKA_PORT = int(os.getenv("KAFKA_PORT", "9092"))


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for AumOS services."""
    return SERVICES_BASE_URL


@pytest.fixture(scope="session")
def service_urls() -> dict[str, str]:
    """Per-service base URLs."""
    return {
        "platform_core": f"{SERVICES_BASE_URL}:{PLATFORM_CORE_PORT}",
        "data_factory": f"{SERVICES_BASE_URL}:{DATA_FACTORY_PORT}",
        "governance": f"{SERVICES_BASE_URL}:{GOVERNANCE_PORT}",
        "security": f"{SERVICES_BASE_URL}:{SECURITY_PORT}",
        "keycloak": f"{SERVICES_BASE_URL}:{KEYCLOAK_PORT}",
    }


@pytest_asyncio.fixture(scope="session")
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Shared HTTP client for integration tests."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client


@pytest.fixture
def tenant_a_id() -> str:
    """Unique tenant ID for Tenant A in isolation tests."""
    return str(uuid.uuid4())


@pytest.fixture
def tenant_b_id() -> str:
    """Unique tenant ID for Tenant B in isolation tests."""
    return str(uuid.uuid4())


@pytest.fixture
def mock_tenant_id() -> str:
    """Generic tenant ID for single-tenant tests."""
    return str(uuid.uuid4())


@pytest.fixture
def mock_correlation_id() -> str:
    """Correlation ID for tracing tests."""
    return str(uuid.uuid4())


@pytest.fixture
def mock_bearer_token(mock_tenant_id: str) -> str:
    """Mock Authorization header value for a tenant."""
    return f"Bearer mock_token_{mock_tenant_id}"


@pytest.fixture
def sample_schema_definition(mock_tenant_id: str) -> dict[str, Any]:
    """A valid Data Factory schema definition for testing."""
    return {
        "schema_id": str(uuid.uuid4()),
        "tenant_id": mock_tenant_id,
        "row_count": 100,
        "output_format": "parquet",
        "columns": [
            {"name": "id", "type": "uuid", "nullable": False},
            {"name": "amount", "type": "float", "min": 0.0, "max": 1000.0},
            {"name": "label", "type": "categorical", "categories": ["A", "B", "C"]},
        ],
    }
