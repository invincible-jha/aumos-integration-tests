"""Root conftest — project-wide pytest configuration and shared fixtures."""
from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to suppress PytestUnknownMarkWarning."""
    config.addinivalue_line("markers", "phase0: Foundation integration tests")
    config.addinivalue_line("markers", "phase1: Data Factory integration tests")
    config.addinivalue_line("markers", "phase2: DevOps + Trust integration tests")
    config.addinivalue_line("markers", "smoke: Quick smoke tests")


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip tests that require services not yet running unless explicitly requested."""
    skip_no_services = pytest.mark.skip(reason="Services not available — start docker compose first")
    services_required = os.getenv("AUMOS_SERVICES_RUNNING", "false").lower() == "true"

    if not services_required:
        for item in items:
            if any(
                mark in item.keywords
                for mark in ("smoke", "phase0", "phase1", "phase2")
            ):
                item.add_marker(skip_no_services)
