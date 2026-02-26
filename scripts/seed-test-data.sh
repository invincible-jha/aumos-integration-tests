#!/usr/bin/env bash
set -euo pipefail

echo "Seeding test tenants and data..."

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-aumos}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-aumos_dev}"
POSTGRES_DB="${POSTGRES_DB:-aumos}"

export PGPASSWORD="$POSTGRES_PASSWORD"

# Create test tenants
psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
-- Create test tenants (idempotent)
INSERT INTO tenants (id, name, slug, created_at)
VALUES
    ('test-tenant-001', 'Integration Test Tenant A', 'test-tenant-a', NOW()),
    ('test-tenant-002', 'Integration Test Tenant B', 'test-tenant-b', NOW())
ON CONFLICT (id) DO NOTHING;
SQL

echo "  Test tenants created: test-tenant-001, test-tenant-002"

# Create MinIO test buckets
if command -v mc &>/dev/null; then
    mc alias set local http://localhost:9000 minioadmin minioadmin 2>/dev/null || true
    mc mb --ignore-existing local/aumos-test-tenant-001 2>/dev/null || true
    mc mb --ignore-existing local/aumos-test-tenant-002 2>/dev/null || true
    echo "  MinIO buckets created"
fi

echo "Test data seeding complete."
