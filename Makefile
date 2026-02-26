.PHONY: help up down wait test-smoke test-phase0 test-phase1 test-phase2 test-all logs clean

COMPOSE_FILE := docker-compose.integration.yml

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

up:  ## Start all infrastructure services
	docker compose -f $(COMPOSE_FILE) up -d

down:  ## Stop and remove all infrastructure services
	docker compose -f $(COMPOSE_FILE) down -v

wait:  ## Wait for all services to be healthy
	./scripts/wait-for-services.sh

seed:  ## Seed test tenants and sample data
	./scripts/seed-test-data.sh

test-smoke: wait  ## Run quick smoke tests
	pytest tests/ -v -m smoke

test-phase0: wait  ## Run Phase 0 foundation integration tests
	pytest tests/ -v -m phase0

test-phase1: wait  ## Run Phase 1 Data Factory integration tests
	pytest tests/ -v -m phase1

test-phase2: wait  ## Run Phase 2 DevOps + Trust integration tests
	pytest tests/ -v -m phase2

test-all: wait  ## Run the full integration test suite
	pytest tests/ -v

logs:  ## Tail logs from all infrastructure containers
	docker compose -f $(COMPOSE_FILE) logs -f

clean:  ## Remove all containers, volumes, and cached test artifacts
	docker compose -f $(COMPOSE_FILE) down -v --remove-orphans
	rm -rf .pytest_cache __pycache__ tests/**/__pycache__
