"""Consumer contract tests: services expecting aumos-model-registry API.

Defines what mlops-lifecycle (consumer) expects from model-registry (provider)
when registering and retrieving model artifacts.
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
class TestModelRegistryConsumerContract:
    """MLOps lifecycle's contract expectations for the model-registry API."""

    def test_model_registration_returns_created(self) -> None:
        """MLOps lifecycle expects model-registry to accept model registration.

        Consumer: aumos-mlops-lifecycle
        Provider: aumos-model-registry
        Interaction: POST /api/v1/models
        """
        import httpx

        pact = Consumer("aumos-mlops-lifecycle").has_pact_with(
            Provider("aumos-model-registry"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        request_body = {
            "model_name": "fraud-detector-v2",
            "version": "2.1.0",
            "artifact_uri": "s3://aumos-models/fraud-detector/v2.1.0/model.pkl",
            "framework": "scikit-learn",
            "tenant_id": "test-tenant-uuid",
        }

        expected_response = {
            "model_id": "mdl-001",
            "model_name": "fraud-detector-v2",
            "version": "2.1.0",
            "status": "registered",
            "created_at": "2026-02-26T10:00:00Z",
        }

        (
            pact.given("the model registry accepts new model registrations")
            .upon_receiving("a model registration request for fraud-detector-v2")
            .with_request(
                method="POST",
                path="/api/v1/models",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
                body=request_body,
            )
            .will_respond_with(
                status=201,
                headers={"Content-Type": "application/json"},
                body=expected_response,
            )
        )

        with pact:
            response = httpx.post(
                f"{pact.uri}/api/v1/models",
                json=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
            )
            assert response.status_code == 201
            body = response.json()
            assert body["model_name"] == "fraud-detector-v2"
            assert body["status"] == "registered"

    def test_get_model_by_id_returns_details(self) -> None:
        """MLOps lifecycle expects model-registry to return model details by ID.

        Consumer: aumos-mlops-lifecycle
        Provider: aumos-model-registry
        Interaction: GET /api/v1/models/{model_id}
        """
        import httpx

        pact = Consumer("aumos-mlops-lifecycle").has_pact_with(
            Provider("aumos-model-registry"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        (
            pact.given("model mdl-001 exists in the registry")
            .upon_receiving("a get model request for mdl-001")
            .with_request(
                method="GET",
                path="/api/v1/models/mdl-001",
                headers={"Authorization": "Bearer valid-service-token"},
            )
            .will_respond_with(
                status=200,
                headers={"Content-Type": "application/json"},
                body={
                    "model_id": "mdl-001",
                    "model_name": "fraud-detector-v2",
                    "version": "2.1.0",
                    "artifact_uri": "s3://aumos-models/fraud-detector/v2.1.0/model.pkl",
                    "status": "registered",
                },
            )
        )

        with pact:
            response = httpx.get(
                f"{pact.uri}/api/v1/models/mdl-001",
                headers={"Authorization": "Bearer valid-service-token"},
            )
            assert response.status_code == 200
            assert response.json()["model_id"] == "mdl-001"
