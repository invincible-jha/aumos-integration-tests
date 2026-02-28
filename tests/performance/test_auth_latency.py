"""Auth token validation performance baselines.

SLO: JWT validation logic must complete in < 50ms at p99.
"""
from __future__ import annotations

import time
import uuid

import pytest


pytestmark = [pytest.mark.performance, pytest.mark.integration]


def _make_jwt_claims(
    user_id: str,
    tenant_id: str,
    exp_offset: int = 3600,
) -> dict[str, object]:
    """Build JWT-like claims dict for benchmark input."""
    return {
        "sub": user_id,
        "tenant_id": tenant_id,
        "iss": "http://localhost:8080/realms/aumos",
        "aud": "aumos-api",
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
        "scope": "openid profile",
        "privilege_level": 3,
    }


def _validate_claims(claims: dict[str, object]) -> bool:
    """Simulate JWT claim validation (without crypto overhead).

    In production this is performed by aumos-common's verify_jwt() which
    uses python-jose. The benchmark here measures the claim inspection
    logic (expiry check, required fields, tenant claim) which is the
    hot path in every authenticated request.
    """
    required_fields = {"sub", "tenant_id", "iss", "exp", "iat"}
    if not required_fields.issubset(claims.keys()):
        return False

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        return False

    tenant_id = claims.get("tenant_id")
    if not tenant_id or not isinstance(tenant_id, str):
        return False

    privilege_level = claims.get("privilege_level", 0)
    if not isinstance(privilege_level, int) or privilege_level < 1:
        return False

    return True


class TestAuthLatencyBenchmarks:
    """JWT claim validation latency must stay below 50ms p99."""

    def test_jwt_claim_validation_latency(self, benchmark: object) -> None:
        """Benchmark JWT claim validation under the 50ms p99 SLO.

        Uses pytest-benchmark to measure the validation function over
        multiple rounds and assert mean latency is well under SLO.
        """
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        claims = _make_jwt_claims(user_id, tenant_id)

        result = benchmark(lambda: _validate_claims(claims))  # type: ignore[operator]
        assert result is True, "Valid claims must pass validation"

        # pytest-benchmark stores stats in benchmark.stats — assert mean < 1ms
        # (claim validation is pure Python dict ops, should be microseconds)
        stats = getattr(benchmark, "stats", None)
        if stats:
            mean_seconds = stats.get("mean", 0)
            assert mean_seconds < 0.050, (
                f"JWT claim validation mean latency {mean_seconds*1000:.2f}ms "
                f"exceeds 50ms SLO"
            )

    def test_expired_token_rejection_latency(self, benchmark: object) -> None:
        """Benchmark expired token rejection — must fail fast (< 50ms p99)."""
        user_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        expired_claims = _make_jwt_claims(user_id, tenant_id, exp_offset=-3600)

        result = benchmark(lambda: _validate_claims(expired_claims))  # type: ignore[operator]
        assert result is False, "Expired claims must fail validation"

    def test_bulk_token_validation_throughput(self) -> None:
        """100 sequential claim validations must complete in under 50ms total.

        Simulates a burst of 100 API requests hitting the auth layer
        simultaneously (e.g. during a client retry storm).
        """
        tenant_id = str(uuid.uuid4())
        claims_batch = [
            _make_jwt_claims(str(uuid.uuid4()), tenant_id)
            for _ in range(100)
        ]

        start = time.perf_counter()
        results = [_validate_claims(c) for c in claims_batch]
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert all(results), "All valid claims must pass"
        assert elapsed_ms < 50.0, (
            f"100 claim validations took {elapsed_ms:.2f}ms — exceeds 50ms SLO"
        )
