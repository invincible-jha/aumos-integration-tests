"""Consumer contract tests: services expecting aumos-llm-serving API.

Defines what agent-framework (consumer) expects from llm-serving (provider)
when submitting inference requests.
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
class TestLLMServingConsumerContract:
    """Agent framework's contract expectations for the llm-serving inference API."""

    def test_inference_request_returns_completion(self) -> None:
        """Agent framework expects llm-serving to return a text completion.

        Consumer: aumos-agent-framework
        Provider: aumos-llm-serving
        Interaction: POST /api/v1/inference/complete
        """
        import httpx

        pact = Consumer("aumos-agent-framework").has_pact_with(
            Provider("aumos-llm-serving"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        request_body = {
            "model": "aumos-llm-v1",
            "prompt": "Summarize the following data quality report:",
            "max_tokens": 256,
            "temperature": 0.1,
            "tenant_id": "test-tenant-uuid",
        }

        (
            pact.given("the LLM serving endpoint is available and the model is loaded")
            .upon_receiving("an inference completion request")
            .with_request(
                method="POST",
                path="/api/v1/inference/complete",
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
                    "completion_id": "cmpl-001",
                    "text": "The data quality report shows 98.5% completeness...",
                    "model": "aumos-llm-v1",
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 48,
                        "total_tokens": 60,
                    },
                    "finish_reason": "stop",
                },
            )
        )

        with pact:
            response = httpx.post(
                f"{pact.uri}/api/v1/inference/complete",
                json=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert "text" in body
            assert body["finish_reason"] == "stop"
            assert "usage" in body

    def test_inference_model_not_found_returns_404(self) -> None:
        """LLM serving returns 404 when the requested model is not registered.

        Consumer: aumos-agent-framework
        Provider: aumos-llm-serving
        """
        import httpx

        pact = Consumer("aumos-agent-framework").has_pact_with(
            Provider("aumos-llm-serving"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        (
            pact.given("model nonexistent-model-v99 is not registered")
            .upon_receiving("an inference request for a nonexistent model")
            .with_request(
                method="POST",
                path="/api/v1/inference/complete",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
                body={
                    "model": "nonexistent-model-v99",
                    "prompt": "Hello",
                    "max_tokens": 10,
                    "tenant_id": "test-tenant-uuid",
                },
            )
            .will_respond_with(
                status=404,
                headers={"Content-Type": "application/json"},
                body={
                    "detail": "Model not found: nonexistent-model-v99",
                    "error_code": "MODEL_NOT_FOUND",
                },
            )
        )

        with pact:
            response = httpx.post(
                f"{pact.uri}/api/v1/inference/complete",
                json={
                    "model": "nonexistent-model-v99",
                    "prompt": "Hello",
                    "max_tokens": 10,
                    "tenant_id": "test-tenant-uuid",
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer valid-service-token",
                },
            )
            assert response.status_code == 404
            assert response.json()["error_code"] == "MODEL_NOT_FOUND"

    def test_inference_rate_limited_returns_429(self) -> None:
        """LLM serving returns 429 when tenant inference quota is exceeded.

        Consumer: aumos-agent-framework
        Provider: aumos-llm-serving
        """
        import httpx

        pact = Consumer("aumos-agent-framework").has_pact_with(
            Provider("aumos-llm-serving"),
            pact_dir=PACT_DIR,
            publish_to_broker=False,
        )

        (
            pact.given("tenant rate-limited-tenant has exceeded its inference quota")
            .upon_receiving("an inference request from a rate-limited tenant")
            .with_request(
                method="POST",
                path="/api/v1/inference/complete",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer rate-limited-token",
                },
                body={
                    "model": "aumos-llm-v1",
                    "prompt": "Test",
                    "max_tokens": 10,
                    "tenant_id": "rate-limited-tenant",
                },
            )
            .will_respond_with(
                status=429,
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": "60",
                },
                body={
                    "detail": "Rate limit exceeded",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "retry_after_seconds": 60,
                },
            )
        )

        with pact:
            response = httpx.post(
                f"{pact.uri}/api/v1/inference/complete",
                json={
                    "model": "aumos-llm-v1",
                    "prompt": "Test",
                    "max_tokens": 10,
                    "tenant_id": "rate-limited-tenant",
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer rate-limited-token",
                },
            )
            assert response.status_code == 429
            assert response.json()["error_code"] == "RATE_LIMIT_EXCEEDED"
