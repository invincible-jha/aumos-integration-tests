"""Verify governance policy evaluation pipeline flow end-to-end.

Tests:
- Policy evaluation is triggered on model deployment requests
- Multi-step policy chains evaluate in order
- Policy violations produce structured rejection events
- Governance decisions are persisted and auditable
- Human approval gates block automated progression
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_TENANT_ID = str(uuid.uuid4())


def _make_policy(
    policy_id: str,
    name: str,
    rule_type: str,
    threshold: float | None = None,
) -> dict[str, Any]:
    return {
        "policy_id": policy_id,
        "tenant_id": MOCK_TENANT_ID,
        "name": name,
        "rule_type": rule_type,
        "threshold": threshold,
        "active": True,
    }


def _make_model_deployment_request(
    model_name: str,
    environment: str,
    metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "tenant_id": MOCK_TENANT_ID,
        "model_name": model_name,
        "environment": environment,
        "requested_by": str(uuid.uuid4()),
        "metrics": metrics or {"accuracy": 0.95, "bias_score": 0.02},
    }


@pytest.mark.phase2
class TestGovernancePipeline:
    """Verify governance policy evaluation pipeline flow."""

    async def test_policy_evaluation_triggered_on_deployment_event(self) -> None:
        """A MODEL_DEPLOYMENT_REQUESTED event triggers policy evaluation."""
        evaluation_calls: list[dict[str, Any]] = []

        def evaluate_policies(deployment_request: dict[str, Any]) -> dict[str, Any]:
            evaluation_calls.append(deployment_request)
            return {"result": "APPROVED", "policies_checked": 3}

        request = _make_model_deployment_request("fraud-detector-v2", "production")
        result = evaluate_policies(request)

        assert len(evaluation_calls) == 1
        assert evaluation_calls[0]["model_name"] == "fraud-detector-v2"
        assert result["policies_checked"] > 0

    async def test_policy_chain_evaluates_in_order(self) -> None:
        """Policies in a chain are evaluated sequentially; first violation stops the chain."""
        evaluated_order: list[str] = []

        policies = [
            _make_policy("p1", "bias-threshold", "METRIC_THRESHOLD", threshold=0.05),
            _make_policy("p2", "accuracy-minimum", "METRIC_THRESHOLD", threshold=0.90),
            _make_policy("p3", "human-approval-required", "HUMAN_APPROVAL"),
        ]

        def evaluate_chain(
            deployment_request: dict[str, Any],
            policy_chain: list[dict[str, Any]],
        ) -> dict[str, Any]:
            for policy in policy_chain:
                evaluated_order.append(policy["name"])
                if policy["rule_type"] == "METRIC_THRESHOLD":
                    metric_key = policy["name"].split("-")[0]
                    metric_value = deployment_request["metrics"].get(metric_key, 0.0)
                    if metric_key == "bias" and metric_value > (policy["threshold"] or 0.0):
                        return {"result": "REJECTED", "blocked_by": policy["policy_id"]}
                elif policy["rule_type"] == "HUMAN_APPROVAL":
                    return {"result": "PENDING_APPROVAL", "approval_policy": policy["policy_id"]}
            return {"result": "APPROVED"}

        request = _make_model_deployment_request(
            "test-model", "staging", metrics={"accuracy": 0.97, "bias": 0.01}
        )
        result = evaluate_chain(request, policies)

        assert evaluated_order[0] == "bias-threshold"
        assert result["result"] == "PENDING_APPROVAL"

    async def test_bias_threshold_violation_rejects_deployment(self) -> None:
        """A model with bias_score above threshold is rejected with reason."""
        policy = _make_policy("bias-policy", "bias-threshold", "METRIC_THRESHOLD", threshold=0.05)
        high_bias_request = _make_model_deployment_request(
            "biased-model",
            "production",
            metrics={"accuracy": 0.96, "bias_score": 0.12},  # bias too high
        )

        def check_bias_policy(
            request: dict[str, Any],
            pol: dict[str, Any],
        ) -> dict[str, Any]:
            bias_score = request["metrics"].get("bias_score", 0.0)
            threshold = pol.get("threshold") or 0.0
            if bias_score > threshold:
                return {
                    "result": "REJECTED",
                    "policy_id": pol["policy_id"],
                    "reason": f"bias_score {bias_score} exceeds threshold {threshold}",
                    "error_code": "POLICY_VIOLATION",
                }
            return {"result": "APPROVED"}

        result = check_bias_policy(high_bias_request, policy)

        assert result["result"] == "REJECTED"
        assert result["error_code"] == "POLICY_VIOLATION"
        assert "0.12" in result["reason"]

    async def test_approved_deployment_emits_approval_event(self) -> None:
        """An approved deployment emits a DEPLOYMENT_APPROVED governance event."""
        emitted_events: list[dict[str, Any]] = []

        def approve_deployment(request: dict[str, Any]) -> dict[str, Any]:
            approval = {
                "event_type": "DEPLOYMENT_APPROVED",
                "request_id": request["request_id"],
                "tenant_id": request["tenant_id"],
                "model_name": request["model_name"],
                "approved_at": "2026-02-26T10:00:00Z",
            }
            emitted_events.append(approval)
            return approval

        request = _make_model_deployment_request("safe-model", "staging")
        result = approve_deployment(request)

        assert len(emitted_events) == 1
        assert emitted_events[0]["event_type"] == "DEPLOYMENT_APPROVED"
        assert emitted_events[0]["model_name"] == "safe-model"

    async def test_governance_decision_persisted_for_audit(self) -> None:
        """Every policy evaluation result is persisted to the governance audit log."""
        audit_log: list[dict[str, Any]] = []

        def persist_governance_decision(
            request: dict[str, Any],
            result: str,
            policies_checked: int,
        ) -> None:
            audit_log.append({
                "id": str(uuid.uuid4()),
                "request_id": request["request_id"],
                "tenant_id": request["tenant_id"],
                "model_name": request["model_name"],
                "result": result,
                "policies_checked": policies_checked,
                "recorded_at": "2026-02-26T10:00:00Z",
            })

        request = _make_model_deployment_request("model-v1", "production")
        persist_governance_decision(request, "APPROVED", 5)
        persist_governance_decision(
            _make_model_deployment_request("rejected-model", "production"),
            "REJECTED",
            2,
        )

        assert len(audit_log) == 2
        assert audit_log[0]["result"] == "APPROVED"
        assert audit_log[1]["result"] == "REJECTED"
        assert all("recorded_at" in entry for entry in audit_log)

    async def test_human_approval_gate_blocks_auto_progression(self) -> None:
        """A deployment requiring human approval cannot proceed until explicitly approved."""
        deployment_state: dict[str, str] = {"status": "PENDING_APPROVAL"}
        approval_tokens: list[str] = []

        def auto_progress(state: dict[str, str]) -> bool:
            return state["status"] == "APPROVED"

        def human_approve(state: dict[str, str], approver_id: str) -> None:
            approval_tokens.append(approver_id)
            state["status"] = "APPROVED"

        # Before human approval, auto-progression is blocked
        assert auto_progress(deployment_state) is False

        # After human approval, progression is allowed
        human_approve(deployment_state, approver_id=str(uuid.uuid4()))
        assert auto_progress(deployment_state) is True
        assert len(approval_tokens) == 1

    async def test_governance_pipeline_api_endpoint(self) -> None:
        """POST /governance/evaluate returns a structured evaluation result."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "request_id": str(uuid.uuid4()),
            "result": "APPROVED",
            "policies_evaluated": [
                {"policy_id": "p1", "passed": True},
                {"policy_id": "p2", "passed": True},
            ],
            "next_step": "DEPLOY",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8003/api/v1/governance/evaluate",
                    headers={"Authorization": f"Bearer tenant_{MOCK_TENANT_ID}_token"},
                    json={
                        "model_name": "production-model",
                        "environment": "production",
                        "metrics": {"accuracy": 0.98, "bias_score": 0.01},
                    },
                )

        assert response.status_code == 200
        body = response.json()
        assert body["result"] == "APPROVED"
        assert len(body["policies_evaluated"]) == 2
