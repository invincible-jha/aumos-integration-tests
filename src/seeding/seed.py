"""Async seed data creation for AumOS integration tests.

Idempotent: running seed_all() twice produces the same state (upserts, not inserts).

Usage:
    # Standalone:
    python -m src.seeding.seed --database-url postgresql+asyncpg://aumos:aumos_dev@localhost/aumos

    # Programmatic (from conftest.py):
    from src.seeding.seed import seed_all
    await seed_all(engine)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.seeding.fixtures import SEED_KAFKA_TOPICS, SEED_TENANTS, SEED_USERS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tenant seeding
# ---------------------------------------------------------------------------


async def seed_tenants(engine: AsyncEngine) -> int:
    """Upsert all 3 test tenants.

    Returns:
        Number of tenants upserted.
    """
    async with engine.begin() as conn:
        # Ensure tenants table exists (created by conftest.py or migration)
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        )

        for tenant in SEED_TENANTS:
            await conn.execute(
                text("""
                    INSERT INTO tenants (id, name, slug)
                    VALUES (:id, :name, :slug)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        slug = EXCLUDED.slug
                """),
                {"id": tenant["id"], "name": tenant["name"], "slug": tenant["slug"]},
            )

    logger.info("Seeded %d tenants", len(SEED_TENANTS))
    return len(SEED_TENANTS)


# ---------------------------------------------------------------------------
# User seeding
# ---------------------------------------------------------------------------


async def seed_users(engine: AsyncEngine) -> int:
    """Upsert all 15 test users (5 per tenant, one per privilege level).

    Returns:
        Number of users upserted.
    """
    async with engine.begin() as conn:
        # Ensure users table exists
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS test_users (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    privilege_level INTEGER NOT NULL CHECK (privilege_level BETWEEN 1 AND 5),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        )

        for user in SEED_USERS:
            await conn.execute(
                text("""
                    INSERT INTO test_users (id, tenant_id, username, email, privilege_level)
                    VALUES (:id, :tenant_id, :username, :email, :privilege_level)
                    ON CONFLICT (id) DO UPDATE SET
                        username = EXCLUDED.username,
                        email = EXCLUDED.email,
                        privilege_level = EXCLUDED.privilege_level
                """),
                {
                    "id": user["id"],
                    "tenant_id": user["tenant_id"],
                    "username": user["username"],
                    "email": user["email"],
                    "privilege_level": user["privilege_level"],
                },
            )

    logger.info("Seeded %d test users", len(SEED_USERS))
    return len(SEED_USERS)


# ---------------------------------------------------------------------------
# Kafka topic seeding
# ---------------------------------------------------------------------------


async def seed_kafka_topics(bootstrap_servers: str) -> int:
    """Create all standard AumOS Kafka topics (idempotent).

    Returns:
        Number of topics created (0 if all already existed).
    """
    try:
        from confluent_kafka.admin import AdminClient, NewTopic
    except ImportError:
        logger.warning("confluent-kafka not installed — skipping Kafka topic seeding")
        return 0

    admin = AdminClient({"bootstrap.servers": bootstrap_servers})

    new_topics = [
        NewTopic(
            topic["name"],  # type: ignore[arg-type]
            num_partitions=topic["partitions"],  # type: ignore[arg-type]
            replication_factor=topic["replication_factor"],  # type: ignore[arg-type]
        )
        for topic in SEED_KAFKA_TOPICS
    ]

    futures = admin.create_topics(new_topics)
    created = 0
    for topic_name, future in futures.items():
        try:
            future.result()
            created += 1
            logger.debug("Created Kafka topic: %s", topic_name)
        except Exception as exc:
            # TOPIC_ALREADY_EXISTS is expected — not an error
            error_str = str(exc)
            if "TOPIC_ALREADY_EXISTS" not in error_str and "already exists" not in error_str:
                logger.warning("Failed to create topic %s: %s", topic_name, exc)

    logger.info("Kafka topic seeding complete (%d new, %d total)", created, len(SEED_KAFKA_TOPICS))
    return created


# ---------------------------------------------------------------------------
# MinIO bucket seeding
# ---------------------------------------------------------------------------


async def seed_minio_buckets(
    endpoint: str = "http://localhost:9000",
    access_key: str = "minioadmin",
    secret_key: str = "minioadmin",
) -> int:
    """Create per-tenant MinIO buckets (idempotent).

    Returns:
        Number of buckets created.
    """
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        logger.warning("boto3 not installed — skipping MinIO bucket seeding")
        return 0

    from src.seeding.fixtures import ALL_TENANT_IDS

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )

    created = 0
    for tenant_id in ALL_TENANT_IDS:
        bucket_name = f"aumos-{tenant_id}"
        try:
            client.create_bucket(Bucket=bucket_name)
            created += 1
            logger.debug("Created MinIO bucket: %s", bucket_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
                pass
            else:
                logger.warning("Failed to create bucket %s: %s", bucket_name, exc)

    logger.info("MinIO bucket seeding complete (%d new)", created)
    return created


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


async def seed_all(
    engine: AsyncEngine,
    kafka_bootstrap_servers: str | None = None,
    minio_endpoint: str | None = None,
) -> dict[str, int]:
    """Run all seed operations idempotently.

    Args:
        engine: SQLAlchemy async engine connected to the test database.
        kafka_bootstrap_servers: Bootstrap server string for Kafka seeding.
            If None, Kafka seeding is skipped.
        minio_endpoint: MinIO endpoint URL for bucket seeding.
            If None, MinIO seeding is skipped.

    Returns:
        Dict of seeding results: {resource_type: count_seeded}.
    """
    results: dict[str, int] = {}

    tenant_count = await seed_tenants(engine)
    results["tenants"] = tenant_count

    user_count = await seed_users(engine)
    results["users"] = user_count

    if kafka_bootstrap_servers:
        topic_count = await seed_kafka_topics(kafka_bootstrap_servers)
        results["kafka_topics"] = topic_count

    if minio_endpoint:
        bucket_count = await seed_minio_buckets(endpoint=minio_endpoint)
        results["minio_buckets"] = bucket_count

    logger.info("Seed complete: %s", results)
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for standalone seed execution."""
    parser = argparse.ArgumentParser(
        description="Seed AumOS integration test data (idempotent)"
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv(
            "AUMOS_DATABASE__URL",
            "postgresql+asyncpg://aumos:aumos_dev@localhost:5432/aumos",
        ),
        help="SQLAlchemy async database URL",
    )
    parser.add_argument(
        "--kafka-bootstrap-servers",
        default=os.getenv("AUMOS_KAFKA__BOOTSTRAP_SERVERS", ""),
        help="Kafka bootstrap servers (comma-separated). Empty to skip.",
    )
    parser.add_argument(
        "--minio-endpoint",
        default=os.getenv("AUMOS_MINIO__ENDPOINT", ""),
        help="MinIO endpoint URL. Empty to skip.",
    )
    return parser.parse_args()


async def _main() -> None:
    """Async main for CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()

    engine = create_async_engine(args.database_url, echo=False)
    try:
        results = await seed_all(
            engine,
            kafka_bootstrap_servers=args.kafka_bootstrap_servers or None,
            minio_endpoint=args.minio_endpoint or None,
        )
        print(f"Seeding complete: {results}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
