#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for infrastructure services..."

# PostgreSQL
until pg_isready -h localhost -p 5432 -U aumos 2>/dev/null; do
    echo "  Waiting for PostgreSQL..."
    sleep 2
done
echo "  PostgreSQL: ready"

# Redis
until redis-cli -h localhost -p 6379 ping 2>/dev/null | grep -q PONG; do
    echo "  Waiting for Redis..."
    sleep 2
done
echo "  Redis: ready"

# Kafka
until kafka-topics --bootstrap-server localhost:9092 --list 2>/dev/null; do
    echo "  Waiting for Kafka..."
    sleep 2
done
echo "  Kafka: ready"

# Keycloak
until curl -sf http://localhost:8080/health/ready 2>/dev/null; do
    echo "  Waiting for Keycloak..."
    sleep 2
done
echo "  Keycloak: ready"

# MinIO
until curl -sf http://localhost:9000/minio/health/ready 2>/dev/null; do
    echo "  Waiting for MinIO..."
    sleep 2
done
echo "  MinIO: ready"

echo "All infrastructure services are ready!"
