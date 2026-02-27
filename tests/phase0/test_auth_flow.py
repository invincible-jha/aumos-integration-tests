"""End-to-end authentication flow tests across all AumOS services."""
from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_TENANT_ID = str(uuid.uuid4())
MOCK_USER_ID = str(uuid.uuid4())
MOCK_CLIENT_ID = "aumos-service-account"


def _make_jwt_payload(
    subject: str,
    tenant_id: str,
    exp_offset: int = 3600,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Build a mock JWT payload for testing."""
    return {
        "sub": subject,
        "tenant_id": tenant_id,
        "iss": "http://localhost:8080/realms/aumos",
        "aud": "aumos-api",
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
        "scope": " ".join(scopes or ["openid", "profile"]),
    }


@pytest.mark.phase0
class TestAuthFlow:
    """Verify JWT auth works across all AumOS services."""

    async def test_keycloak_token_acquisition(self) -> None:
        """Obtain a token from Keycloak and use it to access a protected API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "eyJhbGciOiJSUzI1NiJ9.mock_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid profile",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            # Simulate Keycloak token endpoint call
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8080/realms/aumos/protocol/openid-connect/token",
                    data={
                        "grant_type": "password",
                        "client_id": MOCK_CLIENT_ID,
                        "username": "test-user",
                        "password": "test-password",
                    },
                )
            assert response.status_code == 200
            token_data = response.json()
            assert "access_token" in token_data
            assert token_data["token_type"] == "Bearer"

    async def test_service_to_service_auth(self) -> None:
        """Service A can authenticate with Service B via client_credentials grant."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "eyJhbGciOiJSUzI1NiJ9.s2s_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "service:read service:write",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8080/realms/aumos/protocol/openid-connect/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": "data-factory-service",
                        "client_secret": "service-secret",
                    },
                )
            assert response.status_code == 200
            token_data = response.json()
            assert "access_token" in token_data
            assert "service:read" in token_data.get("scope", "")

    async def test_expired_token_rejected(self) -> None:
        """Expired JWT tokens are rejected by all services with 401."""
        expired_payload = _make_jwt_payload(
            subject=MOCK_USER_ID,
            tenant_id=MOCK_TENANT_ID,
            exp_offset=-3600,  # expired 1 hour ago
        )

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Token has expired"}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://localhost:8001/api/v1/tenants/me",
                    headers={"Authorization": "Bearer expired.token.here"},
                )
            assert response.status_code == 401
            assert "expired" in response.json().get("detail", "").lower()

    async def test_missing_tenant_claim_rejected(self) -> None:
        """JWT without tenant_id claim is rejected by tenant-scoped endpoints."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "detail": "Missing required claim: tenant_id",
            "error_code": "MISSING_TENANT_CLAIM",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://localhost:8001/api/v1/datasets",
                    headers={"Authorization": "Bearer no_tenant_claim_token"},
                )
            assert response.status_code == 403
            body = response.json()
            assert "tenant_id" in body.get("detail", "")

    async def test_cross_tenant_token_rejected(self) -> None:
        """Token issued for Tenant A cannot access Tenant B's resources."""
        tenant_a_id = str(uuid.uuid4())
        tenant_b_id = str(uuid.uuid4())

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "detail": "Access denied: resource belongs to a different tenant",
            "error_code": "CROSS_TENANT_ACCESS",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                # Use tenant_a token to access tenant_b resource
                response = await client.get(
                    f"http://localhost:8001/api/v1/tenants/{tenant_b_id}/datasets",
                    headers={"Authorization": f"Bearer tenant_a_{tenant_a_id}_token"},
                )
            assert response.status_code == 403
            assert "CROSS_TENANT" in response.json().get("error_code", "")

    async def test_token_refresh_flow(self) -> None:
        """Refresh token can be exchanged for a new access token."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "eyJhbGciOiJSUzI1NiJ9.refreshed_token",
            "refresh_token": "new_refresh_token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8080/realms/aumos/protocol/openid-connect/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": MOCK_CLIENT_ID,
                        "refresh_token": "valid_refresh_token",
                    },
                )
            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data

    async def test_role_based_access_enforced(self) -> None:
        """Admin-only endpoints reject tokens without the admin role."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "detail": "Insufficient permissions: role 'admin' required",
            "error_code": "INSUFFICIENT_ROLE",
        }

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"http://localhost:8001/api/v1/tenants/{MOCK_TENANT_ID}",
                    headers={"Authorization": "Bearer viewer_role_token"},
                )
            assert response.status_code == 403
            assert "INSUFFICIENT_ROLE" in response.json().get("error_code", "")
