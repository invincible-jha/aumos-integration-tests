"""Pact consumer contract tests for AumOS cross-service interactions.

These tests define consumer-driven contracts — the consumer (calling service)
specifies exactly what it expects from the provider (called service) API.
Provider services run verification against these contracts in their own CI.

Top 10 cross-service interactions covered:
1. aumos-governance-engine  → aumos-auth-gateway       (privilege check)
2. aumos-tabular-engine     → aumos-privacy-engine      (budget allocation)
3. aumos-approval-workflow  → notification-service      (alert sending)
4. aumos-mlops-lifecycle    → aumos-model-registry      (model registration)
5. aumos-agent-framework    → aumos-llm-serving         (inference)
6. aumos-security-runtime   → aumos-event-bus           (alert publishing)
7. aumos-maturity-assessment→ aumos-governance-engine   (policy evaluation)
8. aumos-data-pipeline      → aumos-tabular-engine      (synthesis job submission)
9. aumos-ai-finops          → aumos-observability       (metrics query)
10. aumos-sdk               → multiple services         (API client validation)
"""
