# =============================================================================
# HTML_MeetingProtokol — convenience Makefile
# =============================================================================
# Self-documenting: run `make help`
# =============================================================================

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

COMPOSE_DEV  := docker compose
COMPOSE_PROD := docker compose -f docker-compose.prod.yml --env-file .env.prod

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Meta
# -----------------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)

# -----------------------------------------------------------------------------
# Dev (single host, hot reload, optional ollama)
# -----------------------------------------------------------------------------
.PHONY: dev dev-up dev-down dev-logs dev-shell dev-migrate dev-test dev-rebuild
dev: dev-up ## Bring up the dev stack
dev-up:
	$(COMPOSE_DEV) up -d
dev-down:
	$(COMPOSE_DEV) down
dev-logs:
	$(COMPOSE_DEV) logs -f --tail=200
dev-shell:
	$(COMPOSE_DEV) exec backend /bin/bash
dev-migrate:
	$(COMPOSE_DEV) exec backend alembic upgrade head
dev-test:
	$(COMPOSE_DEV) exec backend pytest -q
dev-rebuild:
	$(COMPOSE_DEV) build --no-cache --pull

# -----------------------------------------------------------------------------
# Production
# -----------------------------------------------------------------------------
.PHONY: prod prod-up prod-down prod-logs prod-shell prod-deploy prod-restart
prod: prod-up ## Bring up the production stack
prod-up:
	@if [ ! -f .env.prod ]; then \
		echo "ERROR: .env.prod missing — copy from .env.prod.example and fill in secrets"; exit 1; \
	fi
	$(COMPOSE_PROD) up -d --remove-orphans
prod-down:
	$(COMPOSE_PROD) down
prod-logs:
	$(COMPOSE_PROD) logs -f --tail=200
prod-shell:
	$(COMPOSE_PROD) exec backend /bin/bash
prod-deploy: ## Run full deploy (prereqs check + migrate + health)
	./scripts/deploy.sh
prod-restart:
	$(COMPOSE_PROD) restart backend

# -----------------------------------------------------------------------------
# Migrations
# -----------------------------------------------------------------------------
.PHONY: migrate migrate-new migrate-down
migrate: ## Apply all pending migrations
	$(COMPOSE_PROD) exec backend alembic upgrade head
migrate-new: ## Create a new migration (usage: make migrate-new MSG="add foo")
	@if [ -z "$(MSG)" ]; then echo "Usage: make migrate-new MSG=\"description\""; exit 1; fi
	$(COMPOSE_PROD) exec backend alembic revision --autogenerate -m "$(MSG)"
migrate-down:
	$(COMPOSE_PROD) exec backend alembic downgrade -1

# -----------------------------------------------------------------------------
# Backups
# -----------------------------------------------------------------------------
.PHONY: backup backup-list restore
backup: ## Run backup script
	./scripts/backup.sh
backup-list: ## List recent local backups
	@ls -lh /backup/db/ 2>/dev/null | tail -20 || echo "no /backup/db yet"
restore: ## Restore (usage: make restore DB=/backup/db/2026-01-15.sql.gz)
	@if [ -z "$(DB)" ]; then echo "Usage: make restore DB=<dump.sql.gz> [FILES=<snapshot_dir>]"; exit 1; fi
	./scripts/restore.sh "$(DB)" $(FILES)

# -----------------------------------------------------------------------------
# Testing / linting
# -----------------------------------------------------------------------------
.PHONY: test lint format
test: ## Run tests
	$(COMPOSE_DEV) exec backend pytest -q
lint:
	$(COMPOSE_DEV) exec backend ruff check app tests
format:
	$(COMPOSE_DEV) exec backend ruff format app tests

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
.PHONY: ps volumes prune clean
ps: ## List running compose services
	$(COMPOSE_PROD) ps
volumes: ## List external + compose volumes
	docker volume ls | grep -E 'pgdata_prod|html_mp_prod|caddy'
prune: ## Remove dangling images + stopped containers
	docker image prune -f
	docker container prune -f
clean: ## DANGER: nuke stack + volumes
	@echo "This will delete the production stack AND volumes. Press Ctrl-C in 5s…"
	@sleep 5
	$(COMPOSE_PROD) down -v --remove-orphans
