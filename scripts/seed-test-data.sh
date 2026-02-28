#!/usr/bin/env bash
# seed-test-data.sh — Seed AumOS integration test data (idempotent)
#
# Creates 3 test tenants, 15 users (5 privilege levels per tenant),
# Kafka topics, and MinIO buckets using the Python seeding module.
#
# Usage:
#   ./scripts/seed-test-data.sh
#   POSTGRES_HOST=db ./scripts/seed-test-data.sh
set -euo pipefail

echo "Seeding AumOS integration test data..."

# ---------------------------------------------------------------------------
# Environment variable defaults
# ---------------------------------------------------------------------------
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-aumos}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-aumos_dev}"
POSTGRES_DB="${POSTGRES_DB:-aumos}"

KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"

DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

# ---------------------------------------------------------------------------
# Python seed module (primary path — uses SQLAlchemy async, idempotent)
# ---------------------------------------------------------------------------
echo "  Running Python seed module..."
python -m src.seeding.seed \
    --database-url "${DATABASE_URL}" \
    --kafka-bootstrap-servers "${KAFKA_BOOTSTRAP_SERVERS}" \
    --minio-endpoint "${MINIO_ENDPOINT}"

# ---------------------------------------------------------------------------
# MinIO bucket creation (direct mc CLI fallback if boto3 not available)
# ---------------------------------------------------------------------------
if command -v mc &>/dev/null; then
    echo "  Creating MinIO buckets via mc CLI..."
    mc alias set local "${MINIO_ENDPOINT}" minioadmin minioadmin 2>/dev/null || true
    mc mb --ignore-existing local/aumos-00000000-0000-0000-0000-000000000001 2>/dev/null || true
    mc mb --ignore-existing local/aumos-00000000-0000-0000-0000-000000000002 2>/dev/null || true
    mc mb --ignore-existing local/aumos-00000000-0000-0000-0000-000000000003 2>/dev/null || true
    echo "  MinIO buckets ready"
fi

# ---------------------------------------------------------------------------
# Keycloak realm seeding (via fixture files in fixtures/keycloak/)
# ---------------------------------------------------------------------------
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
if curl -sf "${KEYCLOAK_URL}/health/ready" > /dev/null 2>&1; then
    echo "  Keycloak is running — realm import is handled by docker-compose volume mount"
    echo "  (fixtures/keycloak/*.json are imported on Keycloak startup)"
fi

echo "Test data seeding complete."
echo ""
echo "Test tenants:"
echo "  Tenant Alpha:  00000000-0000-0000-0000-000000000001  (test-tenant-alpha)"
echo "  Tenant Beta:   00000000-0000-0000-0000-000000000002  (test-tenant-beta)"
echo "  Tenant Gamma:  00000000-0000-0000-0000-000000000003  (test-tenant-gamma)"
echo ""
echo "Users per tenant: READ_ONLY(1), READ_WRITE(2), OPERATOR(3), ADMIN(4), SUPER_ADMIN(5)"
