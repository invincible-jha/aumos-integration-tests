"""Shared fixtures for AumOS integration tests."""
from __future__ import annotations

import os
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio


SERVICES_BASE_URL = os.getenv("AUMOS_SERVICES_URL", "http://localhost")


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for AumOS services."""
    return SERVICES_BASE_URL


@pytest_asyncio.fixture(scope="session")
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Shared HTTP client for integration tests."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client
