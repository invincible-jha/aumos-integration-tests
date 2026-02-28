"""Consumer contract tests: services expecting aumos-auth-gateway API.

Defines what governance-engine (consumer) expects from auth-gateway (provider)
when checking user privilege levels.
"""
from __future__ import annotations

import os

import pytest

try:
    from pact import Consumer, Provider
    PACT_AVAILABLE = True
except ImportError:
    PACT_AVAILABLE = False


pytestmark = pytest.mark.contract

PACT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "pacts")


@pytest.mark.skipif(not PACT_AVAILABLE, reason="pact-python not installed — pip install pact-python")
class TestAuthGatewayConsumerContract:
    """Governance engine's contract expectations for the auth-gateway privilege check API."""

    def test_privilege_check_returns_operator_level(self) -> None:
        """Governance engine expects auth-gateway to return privilege level for a user.

        Consumer: aumos-governance-engine
        Provider: aumos-auth-gateway
        Interaction: GET /api/v1/auth/users/{user_id}/privilege
        """
        import httpx

        pact = Consumer("aumos-governance-engine").has_pact_with(
            Provider("aumos-auth-gateway"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        expected_response = {
            "user_id": "test-user-123",
            "privilege_level": 3,
            "roles": ["operator"],
            "tenant_id": "test-tenant-uuid",
        }

        (
            pact.given("user test-user-123 exists with operator privilege")
            .upon_receiving("a privilege check request for test-user-123")
            .with_request(
                method="GET",
                path="/api/v1/auth/users/test-user-123/privilege",
                headers={"Authorization": "Bearer valid-service-token"},
            )
            .will_respond_with(
                status=200,
                headers={"Content-Type": "application/json"},
                body=expected_response,
            )
        )

        with pact:
            response = httpx.get(
                f"{pact.uri}/api/v1/auth/users/test-user-123/privilege",
                headers={"Authorization": "Bearer valid-service-token"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["privilege_level"] == 3
            assert "operator" in body["roles"]

    def test_privilege_check_unknown_user_returns_404(self) -> None:
        """Governance engine expects auth-gateway to return 404 for unknown users.

        Consumer: aumos-governance-engine
        Provider: aumos-auth-gateway
        """
        import httpx

        pact = Consumer("aumos-governance-engine").has_pact_with(
            Provider("aumos-auth-gateway"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        (
            pact.given("user unknown-user-999 does not exist")
            .upon_receiving("a privilege check request for an unknown user")
            .with_request(
                method="GET",
                path="/api/v1/auth/users/unknown-user-999/privilege",
                headers={"Authorization": "Bearer valid-service-token"},
            )
            .will_respond_with(
                status=404,
                headers={"Content-Type": "application/json"},
                body={"detail": "User not found", "error_code": "USER_NOT_FOUND"},
            )
        )

        with pact:
            response = httpx.get(
                f"{pact.uri}/api/v1/auth/users/unknown-user-999/privilege",
                headers={"Authorization": "Bearer valid-service-token"},
            )
            assert response.status_code == 404
            assert response.json()["error_code"] == "USER_NOT_FOUND"

    def test_missing_auth_header_returns_401(self) -> None:
        """Auth gateway rejects unauthenticated requests with 401.

        Consumer: aumos-governance-engine
        Provider: aumos-auth-gateway
        """
        import httpx

        pact = Consumer("aumos-governance-engine").has_pact_with(
            Provider("aumos-auth-gateway"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        (
            pact.given("the request has no Authorization header")
            .upon_receiving("an unauthenticated privilege check request")
            .with_request(
                method="GET",
                path="/api/v1/auth/users/any-user/privilege",
            )
            .will_respond_with(
                status=401,
                headers={"Content-Type": "application/json"},
                body={"detail": "Authentication required"},
            )
        )

        with pact:
            response = httpx.get(
                f"{pact.uri}/api/v1/auth/users/any-user/privilege"
            )
            assert response.status_code == 401
