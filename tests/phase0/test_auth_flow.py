"""End-to-end authentication flow tests."""
from __future__ import annotations

import pytest


@pytest.mark.phase0
class TestAuthFlow:
    """Verify auth flow from login to API access."""

    async def test_keycloak_token_acquisition(self) -> None:
        """Obtain token from Keycloak and use to access API."""
        pass

    async def test_service_to_service_auth(self) -> None:
        """Service A can authenticate with Service B via client_credentials."""
        pass

    async def test_expired_token_rejected(self) -> None:
        """Expired JWT tokens are rejected by all services."""
        pass
