"""Consumer contract tests: services expecting aumos-privacy-engine API.

Defines what tabular-engine (consumer) expects from privacy-engine (provider)
when allocating differential privacy budget for synthesis jobs.
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
class TestPrivacyEngineConsumerContract:
    """Tabular engine's contract expectations for the privacy-engine budget API."""

    def test_budget_allocation_returns_epsilon(self) -> None:
        """Tabular engine expects privacy-engine to allocate epsilon budget for a job.

        Consumer: aumos-tabular-engine
        Provider: aumos-privacy-engine
        Interaction: POST /api/v1/privacy/budget/allocate
        """
        import httpx

        pact = Consumer("aumos-tabular-engine").has_pact_with(
            Provider("aumos-privacy-engine"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        request_body = {
            "job_id": "job-001",
            "tenant_id": "test-tenant-uuid",
            "requested_epsilon": 1.0,
            "dataset_id": "ds-001",
        }

        (
            pact.given("tenant test-tenant-uuid has sufficient epsilon budget")
            .upon_receiving("a budget allocation request for job-001")
            .with_request(
                method="POST",
                path="/api/v1/privacy/budget/allocate",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
                body=request_body,
            )
            .will_respond_with(
                status=200,
                headers={"Content-Type": "application/json"},
                body={
                    "allocation_id": "alloc-001",
                    "job_id": "job-001",
                    "allocated_epsilon": 1.0,
                    "remaining_budget": 4.0,
                    "status": "approved",
                },
            )
        )

        with pact:
            response = httpx.post(
                f"{pact.uri}/api/v1/privacy/budget/allocate",
                json=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["allocated_epsilon"] == 1.0
            assert body["status"] == "approved"

    def test_budget_allocation_rejected_when_exhausted(self) -> None:
        """Privacy engine rejects budget allocation when tenant epsilon is exhausted.

        Consumer: aumos-tabular-engine
        Provider: aumos-privacy-engine
        Interaction: POST /api/v1/privacy/budget/allocate → 402
        """
        import httpx

        pact = Consumer("aumos-tabular-engine").has_pact_with(
            Provider("aumos-privacy-engine"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        (
            pact.given("tenant exhausted-tenant has no remaining epsilon budget")
            .upon_receiving("a budget allocation request exceeding the limit")
            .with_request(
                method="POST",
                path="/api/v1/privacy/budget/allocate",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
                body={
                    "job_id": "job-overflow",
                    "tenant_id": "exhausted-tenant",
                    "requested_epsilon": 10.0,
                    "dataset_id": "ds-overflow",
                },
            )
            .will_respond_with(
                status=402,
                headers={"Content-Type": "application/json"},
                body={
                    "detail": "Insufficient epsilon budget",
                    "error_code": "BUDGET_EXHAUSTED",
                    "remaining_budget": 0.0,
                },
            )
        )

        with pact:
            response = httpx.post(
                f"{pact.uri}/api/v1/privacy/budget/allocate",
                json={
                    "job_id": "job-overflow",
                    "tenant_id": "exhausted-tenant",
                    "requested_epsilon": 10.0,
                    "dataset_id": "ds-overflow",
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
            )
            assert response.status_code == 402
            assert response.json()["error_code"] == "BUDGET_EXHAUSTED"
