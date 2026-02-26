# CLAUDE.md — AumOS Integration Tests

## Project Context
Cross-repo E2E test suite for verifying integration between AumOS Enterprise services.
Tests are organized by phase and run against the full infrastructure stack.

## What This Repo Provides
- docker-compose.integration.yml: Full infrastructure stack (PostgreSQL, Kafka, Redis, Keycloak, MinIO)
- Phase 0 tests: Tenant isolation, auth flow, event propagation, RLS enforcement
- Phase 1 tests: Data Factory synthesis pipeline
- Phase 2 tests: Governance and approval workflows
- Smoke tests: Service health verification
- Fixtures: Test data, Keycloak realm config

## Running Tests
```bash
docker compose -f docker-compose.integration.yml up -d
./scripts/wait-for-services.sh
pytest tests/ -v -m smoke
pytest tests/ -v -m phase0
```

## Tech Stack
- pytest + pytest-asyncio
- httpx for API testing
- testcontainers for infrastructure
- Docker Compose for full stack
