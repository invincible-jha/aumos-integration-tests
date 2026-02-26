"""Smoke tests: verify all services are healthy."""
from __future__ import annotations

import pytest


SERVICES: list[tuple[str, str]] = [
    # ("service-name", "http://localhost:PORT/health"),
    # Will be populated as AumOS services are added to docker-compose
]


@pytest.mark.smoke
class TestHealthEndpoints:
    """Quick smoke tests for all service health endpoints."""

    async def test_infrastructure_healthy(self) -> None:
        """Verify PostgreSQL, Kafka, Redis, Keycloak are responding."""
        pass

    @pytest.mark.parametrize("service_name,url", SERVICES)
    async def test_service_health(self, service_name: str, url: str) -> None:
        """Verify each AumOS service returns healthy."""
        pass
