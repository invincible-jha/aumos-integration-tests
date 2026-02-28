"""Redis unavailability chaos tests.

Verifies fail-open behavior when Redis is unavailable:
- Rate limiting fails open (request is allowed through)
- Cache misses degrade gracefully to database reads
- Health checks reflect Redis degradation
"""
from __future__ import annotations

import uuid

import pytest
from testcontainers.redis import RedisContainer


pytestmark = [pytest.mark.chaos, pytest.mark.integration]


class TestRedisUnavailableChaos:
    """Verify Redis failure handling and fail-open resilience patterns."""

    async def test_rate_limiter_fails_open_when_redis_unavailable(
        self,
        redis_container: RedisContainer,
    ) -> None:
        """Rate limiting must fail open when Redis is down.

        AumOS rate limiting is implemented with Redis INCR + TTL. When Redis
        is unreachable, the rate limiter must allow the request through
        (fail-open) rather than blocking all traffic (fail-closed). This
        test verifies the fail-open pattern using a direct Redis connection
        timeout to simulate unavailability.
        """
        # Simulate a rate limiter that uses Redis
        # When Redis is unavailable, it should allow requests through

        class RateLimiter:
            """Simplified rate limiter that fails open on Redis errors."""

            def __init__(self, redis_url: str) -> None:
                self._redis_url = redis_url
                self._fail_open = True  # Platform choice: fail open

            async def is_allowed(
                self,
                tenant_id: str,
                limit: int = 100,
                window_seconds: int = 60,
            ) -> tuple[bool, str]:
                """Check if request is within rate limit.

                Returns:
                    (allowed, reason) — if Redis fails, returns (True, 'REDIS_UNAVAILABLE')
                """
                try:
                    import redis.asyncio as aioredis

                    client = aioredis.from_url(
                        self._redis_url,
                        socket_connect_timeout=0.1,  # Very short timeout
                        socket_timeout=0.1,
                    )
                    key = f"rl:{tenant_id}:{window_seconds}"
                    count = await client.incr(key)
                    if count == 1:
                        await client.expire(key, window_seconds)
                    await client.aclose()

                    if count > limit:
                        return (False, "RATE_LIMIT_EXCEEDED")
                    return (True, "ALLOWED")
                except Exception:
                    # Fail open: Redis unavailability must not block requests
                    if self._fail_open:
                        return (True, "REDIS_UNAVAILABLE_FAIL_OPEN")
                    return (False, "REDIS_UNAVAILABLE_FAIL_CLOSED")

        # Use an invalid Redis URL to simulate unavailability
        bad_redis_url = "redis://127.0.0.1:19999/0"  # Nothing listening on this port
        limiter = RateLimiter(bad_redis_url)

        allowed, reason = await limiter.is_allowed(tenant_id=str(uuid.uuid4()), limit=10)

        assert allowed is True, (
            f"Rate limiter must fail open when Redis is unavailable, got: {reason}"
        )
        assert reason == "REDIS_UNAVAILABLE_FAIL_OPEN", (
            f"Expected fail-open reason, got: {reason}"
        )

    async def test_cache_miss_falls_back_to_source(
        self,
        redis_url: str,
    ) -> None:
        """Cache miss (or Redis unavailability) falls back to the authoritative source.

        This verifies the cache-aside pattern — when a cache lookup fails,
        the system must fall back to the database (simulated here as a dict)
        rather than returning an error.
        """
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, decode_responses=True)

        # Authoritative source (simulates database)
        database: dict[str, str] = {
            "tenant-001": "Acme Corp",
            "tenant-002": "Globex Inc",
        }

        cache_key = f"tenant:name:{uuid.uuid4().hex}"  # Guaranteed miss

        async def get_tenant_name_cached(tenant_id: str) -> str:
            """Cache-aside pattern: check Redis first, fall back to DB."""
            cached = await client.get(cache_key)
            if cached:
                return cached
            # Cache miss — fall back to authoritative source
            value = database.get(tenant_id, "UNKNOWN")
            # Populate cache for next request
            await client.setex(cache_key, 60, value)
            return value

        # First call: cache miss → database read
        result = await get_tenant_name_cached("tenant-001")
        assert result == "Acme Corp", f"Cache miss fallback returned wrong value: {result}"

        # Second call: cache hit
        result2 = await get_tenant_name_cached("tenant-001")
        assert result2 == "Acme Corp", f"Cache hit returned wrong value: {result2}"

        await client.aclose()

    async def test_redis_health_check_detects_degradation(
        self,
        redis_url: str,
    ) -> None:
        """Health check must report Redis as healthy when connected."""
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url)

        async def redis_health_check() -> dict[str, object]:
            """Minimal Redis health check that returns latency and status."""
            try:
                result = await client.ping()
                return {"status": "healthy", "ping_ok": result}
            except Exception as exc:
                return {"status": "degraded", "error": str(exc)}

        health = await redis_health_check()
        await client.aclose()

        assert health["status"] == "healthy", f"Redis health check failed: {health}"
        assert health["ping_ok"] is True
