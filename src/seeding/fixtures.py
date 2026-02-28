"""Canonical test data fixtures — stable IDs across all integration test runs.

All integration tests that need tenant or user context MUST import from here
rather than generating random UUIDs. Stable IDs ensure:
- Test failures are reproducible (same data, same IDs)
- Seeded database state matches what tests expect
- CI runs are deterministic across different machines

Privilege level mapping (AumOS 5-level system):
    READ_ONLY   = 1
    READ_WRITE  = 2
    OPERATOR    = 3
    ADMIN       = 4
    SUPER_ADMIN = 5
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Test tenant UUIDs — stable across all runs
# ---------------------------------------------------------------------------

TENANT_ALPHA_ID: str = "00000000-0000-0000-0000-000000000001"
TENANT_BETA_ID: str  = "00000000-0000-0000-0000-000000000002"
TENANT_GAMMA_ID: str = "00000000-0000-0000-0000-000000000003"

TENANT_ALPHA_NAME: str = "Integration Test Tenant Alpha"
TENANT_BETA_NAME: str  = "Integration Test Tenant Beta"
TENANT_GAMMA_NAME: str = "Integration Test Tenant Gamma"

TENANT_ALPHA_SLUG: str = "test-tenant-alpha"
TENANT_BETA_SLUG: str  = "test-tenant-beta"
TENANT_GAMMA_SLUG: str = "test-tenant-gamma"

ALL_TENANT_IDS: list[str] = [TENANT_ALPHA_ID, TENANT_BETA_ID, TENANT_GAMMA_ID]

# ---------------------------------------------------------------------------
# Test user UUIDs — one per privilege level per tenant
# ---------------------------------------------------------------------------

# Tenant Alpha users
ALPHA_READ_ONLY_USER_ID: str   = "00000000-0001-0000-0000-000000000001"
ALPHA_READ_WRITE_USER_ID: str  = "00000000-0001-0000-0000-000000000002"
ALPHA_OPERATOR_USER_ID: str    = "00000000-0001-0000-0000-000000000003"
ALPHA_ADMIN_USER_ID: str       = "00000000-0001-0000-0000-000000000004"
ALPHA_SUPER_ADMIN_USER_ID: str = "00000000-0001-0000-0000-000000000005"

# Tenant Beta users
BETA_READ_ONLY_USER_ID: str   = "00000000-0002-0000-0000-000000000001"
BETA_READ_WRITE_USER_ID: str  = "00000000-0002-0000-0000-000000000002"
BETA_OPERATOR_USER_ID: str    = "00000000-0002-0000-0000-000000000003"
BETA_ADMIN_USER_ID: str       = "00000000-0002-0000-0000-000000000004"
BETA_SUPER_ADMIN_USER_ID: str = "00000000-0002-0000-0000-000000000005"

# Tenant Gamma users
GAMMA_READ_ONLY_USER_ID: str   = "00000000-0003-0000-0000-000000000001"
GAMMA_READ_WRITE_USER_ID: str  = "00000000-0003-0000-0000-000000000002"
GAMMA_OPERATOR_USER_ID: str    = "00000000-0003-0000-0000-000000000003"
GAMMA_ADMIN_USER_ID: str       = "00000000-0003-0000-0000-000000000004"
GAMMA_SUPER_ADMIN_USER_ID: str = "00000000-0003-0000-0000-000000000005"

# ---------------------------------------------------------------------------
# Structured seed data (tenant metadata + user records)
# ---------------------------------------------------------------------------

SEED_TENANTS: list[dict[str, str]] = [
    {"id": TENANT_ALPHA_ID, "name": TENANT_ALPHA_NAME, "slug": TENANT_ALPHA_SLUG},
    {"id": TENANT_BETA_ID,  "name": TENANT_BETA_NAME,  "slug": TENANT_BETA_SLUG},
    {"id": TENANT_GAMMA_ID, "name": TENANT_GAMMA_NAME, "slug": TENANT_GAMMA_SLUG},
]

SEED_USERS: list[dict[str, object]] = [
    # Tenant Alpha
    {"id": ALPHA_READ_ONLY_USER_ID,   "tenant_id": TENANT_ALPHA_ID, "username": "alpha-read",   "privilege_level": 1, "email": "read@alpha.test"},
    {"id": ALPHA_READ_WRITE_USER_ID,  "tenant_id": TENANT_ALPHA_ID, "username": "alpha-write",  "privilege_level": 2, "email": "write@alpha.test"},
    {"id": ALPHA_OPERATOR_USER_ID,    "tenant_id": TENANT_ALPHA_ID, "username": "alpha-op",     "privilege_level": 3, "email": "op@alpha.test"},
    {"id": ALPHA_ADMIN_USER_ID,       "tenant_id": TENANT_ALPHA_ID, "username": "alpha-admin",  "privilege_level": 4, "email": "admin@alpha.test"},
    {"id": ALPHA_SUPER_ADMIN_USER_ID, "tenant_id": TENANT_ALPHA_ID, "username": "alpha-super",  "privilege_level": 5, "email": "super@alpha.test"},
    # Tenant Beta
    {"id": BETA_READ_ONLY_USER_ID,    "tenant_id": TENANT_BETA_ID,  "username": "beta-read",    "privilege_level": 1, "email": "read@beta.test"},
    {"id": BETA_READ_WRITE_USER_ID,   "tenant_id": TENANT_BETA_ID,  "username": "beta-write",   "privilege_level": 2, "email": "write@beta.test"},
    {"id": BETA_OPERATOR_USER_ID,     "tenant_id": TENANT_BETA_ID,  "username": "beta-op",      "privilege_level": 3, "email": "op@beta.test"},
    {"id": BETA_ADMIN_USER_ID,        "tenant_id": TENANT_BETA_ID,  "username": "beta-admin",   "privilege_level": 4, "email": "admin@beta.test"},
    {"id": BETA_SUPER_ADMIN_USER_ID,  "tenant_id": TENANT_BETA_ID,  "username": "beta-super",   "privilege_level": 5, "email": "super@beta.test"},
    # Tenant Gamma
    {"id": GAMMA_READ_ONLY_USER_ID,   "tenant_id": TENANT_GAMMA_ID, "username": "gamma-read",   "privilege_level": 1, "email": "read@gamma.test"},
    {"id": GAMMA_READ_WRITE_USER_ID,  "tenant_id": TENANT_GAMMA_ID, "username": "gamma-write",  "privilege_level": 2, "email": "write@gamma.test"},
    {"id": GAMMA_OPERATOR_USER_ID,    "tenant_id": TENANT_GAMMA_ID, "username": "gamma-op",     "privilege_level": 3, "email": "op@gamma.test"},
    {"id": GAMMA_ADMIN_USER_ID,       "tenant_id": TENANT_GAMMA_ID, "username": "gamma-admin",  "privilege_level": 4, "email": "admin@gamma.test"},
    {"id": GAMMA_SUPER_ADMIN_USER_ID, "tenant_id": TENANT_GAMMA_ID, "username": "gamma-super",  "privilege_level": 5, "email": "super@gamma.test"},
]

# ---------------------------------------------------------------------------
# Kafka test topics (seeded before integration test runs)
# ---------------------------------------------------------------------------

SEED_KAFKA_TOPICS: list[dict[str, object]] = [
    {"name": "aumos.audit.events",        "partitions": 3, "replication_factor": 1},
    {"name": "aumos.governance.events",   "partitions": 3, "replication_factor": 1},
    {"name": "aumos.model.lifecycle",     "partitions": 3, "replication_factor": 1},
    {"name": "aumos.data.pipeline",       "partitions": 3, "replication_factor": 1},
    {"name": "aumos.alerts",              "partitions": 1, "replication_factor": 1},
    {"name": "aumos.audit.events.dlq",    "partitions": 1, "replication_factor": 1},
    {"name": "aumos.governance.events.dlq", "partitions": 1, "replication_factor": 1},
]
