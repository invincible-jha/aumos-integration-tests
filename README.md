# aumos-integration-tests

Cross-repo E2E test suite for verifying integration between AumOS Enterprise platform services.

## Overview

This repository contains integration tests that verify the correct behavior of AumOS services
working together. Tests are organized by development phase and run against a full infrastructure
stack managed by Docker Compose.

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- `pg_isready`, `redis-cli`, `kafka-topics` available on PATH (or via Docker)

## Quick Start

```bash
# Start all infrastructure services
docker compose -f docker-compose.integration.yml up -d

# Wait for services to be healthy
./scripts/wait-for-services.sh

# Run smoke tests
pytest tests/ -v -m smoke

# Run Phase 0 integration tests
pytest tests/ -v -m phase0

# Run all tests
pytest tests/ -v
```

## Test Organization

| Directory         | Marker   | Description                                      |
|-------------------|----------|--------------------------------------------------|
| `tests/smoke/`    | `smoke`  | Quick health checks for all services             |
| `tests/phase0/`   | `phase0` | Foundation: tenant isolation, auth, events, RLS  |
| `tests/phase1/`   | `phase1` | Data Factory: synthesis pipeline                 |
| `tests/phase2/`   | `phase2` | DevOps + Trust: governance flow                  |

## Infrastructure Stack

| Service    | Image                          | Port(s)      |
|------------|--------------------------------|--------------|
| PostgreSQL | pgvector/pgvector:pg16         | 5432         |
| Redis      | redis:7.2-alpine               | 6379         |
| Kafka      | confluentinc/cp-kafka:7.6.0    | 9092         |
| Keycloak   | quay.io/keycloak/keycloak:24.0 | 8080         |
| MinIO      | minio/minio:latest             | 9000, 9001   |

## License

Apache 2.0 — see [LICENSE](LICENSE).
