# ============================================================
# OPSYN MAKEFILE
# Powered by SlimTech
#
# WSL2 USERS: If you see "docker command not found", run:
#   make wsl-setup
# Then close and reopen your terminal, then run:
#   make dev
# ============================================================

.PHONY: dev stop restart build prod-up prod-down prod-migrate test test-unit test-int test-e2e \
        migrate migration seed lint typecheck logs logs-beat shell clean \
        wsl-setup help

# ── Detect Docker command (docker compose v2 vs legacy) ───────
DOCKER_COMPOSE := $(shell \
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then \
    echo "docker compose"; \
  elif command -v docker-compose >/dev/null 2>&1; then \
    echo "docker-compose"; \
  else \
    echo "DOCKER_NOT_FOUND"; \
  fi)

# ── Guard: print helpful message if Docker not found ──────────
check-docker:
	@if [ "$(DOCKER_COMPOSE)" = "DOCKER_NOT_FOUND" ]; then \
		echo ""; \
		echo "  ╔══════════════════════════════════════════════════╗"; \
		echo "  ║  Docker not found. Choose one of these options:  ║"; \
		echo "  ╠══════════════════════════════════════════════════╣"; \
		echo "  ║  WSL2: run  make wsl-setup  then restart WSL     ║"; \
		echo "  ║  Windows: run commands in PowerShell (not WSL)   ║"; \
		echo "  ║  Install: https://docs.docker.com/desktop/       ║"; \
		echo "  ╚══════════════════════════════════════════════════╝"; \
		echo ""; \
		exit 1; \
	fi

# ── WSL2 Docker integration fix ───────────────────────────────
wsl-setup:
	@echo ""
	@echo "  Fixing Docker Desktop WSL2 integration..."
	@echo ""
	@echo "  Step 1: Open Docker Desktop on Windows"
	@echo "  Step 2: Go to Settings → Resources → WSL Integration"
	@echo "  Step 3: Enable integration for your distro (e.g. Ubuntu)"
	@echo "  Step 4: Click 'Apply & Restart'"
	@echo "  Step 5: Close this terminal, open a new one"
	@echo "  Step 6: Run: make dev"
	@echo ""
	@echo "  Alternative — run directly in PowerShell (no WSL needed):"
	@echo "    cd to the opsyn folder in PowerShell, then:"
	@echo "    docker compose up --build"
	@echo ""
	@if grep -qi microsoft /proc/version 2>/dev/null; then \
		echo "  Detected WSL2. Adding Docker to PATH from Windows host..."; \
		echo 'export PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin"' >> ~/.bashrc 2>/dev/null || true; \
		echo "  Added Docker path to ~/.bashrc. Run: source ~/.bashrc"; \
	fi

# ── Environment ───────────────────────────────────────────────
dev: check-docker
	@echo "🚀 Starting Opsyn development stack..."
	$(DOCKER_COMPOSE) up --build

prod-up: check-docker
	@echo "🚀 Starting Opsyn production stack..."
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml up -d

prod-down: check-docker
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml down

prod-migrate: check-docker
	@echo "⬆️  Running production migrations..."
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml exec backend alembic upgrade head

stop: check-docker
	$(DOCKER_COMPOSE) down

restart: check-docker
	$(DOCKER_COMPOSE) restart backend

logs: check-docker
	$(DOCKER_COMPOSE) logs --follow

logs-beat: check-docker
	$(DOCKER_COMPOSE) logs celery-beat --follow

shell: check-docker
	$(DOCKER_COMPOSE) exec backend bash

# ── Database ──────────────────────────────────────────────────
migrate: check-docker
	@echo "⬆️  Running Alembic migrations..."
	$(DOCKER_COMPOSE) exec backend alembic upgrade head

migration: check-docker
	@echo "📝 Creating migration: $(MSG)"
	$(DOCKER_COMPOSE) exec backend alembic revision --autogenerate -m "$(MSG)"

seed: check-docker
	@echo "🌱 Seeding database..."
	$(DOCKER_COMPOSE) exec backend python -m scripts.seed

# ── Testing ───────────────────────────────────────────────────
test: check-docker
	@echo "🧪 Running full test suite..."
	$(DOCKER_COMPOSE) exec backend pytest tests/ -v --tb=short
	cd frontend && npm run test

test-unit: check-docker
	$(DOCKER_COMPOSE) exec backend pytest tests/unit/ -v

test-int: check-docker
	$(DOCKER_COMPOSE) exec backend pytest tests/integration/ -v

test-e2e: check-docker
	$(DOCKER_COMPOSE) exec backend pytest tests/e2e/ -v

# ── Code quality ──────────────────────────────────────────────
lint: check-docker
	$(DOCKER_COMPOSE) exec backend ruff check app/ --fix
	cd frontend && npm run lint

typecheck: check-docker
	$(DOCKER_COMPOSE) exec backend mypy app/ --ignore-missing-imports
	cd frontend && npm run typecheck

# ── Build ─────────────────────────────────────────────────────
build: check-docker
	@echo "🏗️  Building production images..."
	docker build -t opsyn-backend:latest  -f infrastructure/docker/Dockerfile.backend  backend/
	docker build -t opsyn-frontend:latest -f infrastructure/docker/Dockerfile.frontend frontend/

# ── Cleanup ───────────────────────────────────────────────────
clean: check-docker
	$(DOCKER_COMPOSE) down -v --remove-orphans
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

# ── Help ──────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Opsyn — Operational Intelligence Platform"
	@echo "  Powered by SlimTech"
	@echo ""
	@echo "  FIRST TIME:"
	@echo "    make dev          Start all 5 Docker services (first run builds images)"
	@echo "    make migrate      Create all database tables"
	@echo "    make seed         Create admin user + departments"
	@echo ""
	@echo "  DAILY USE:"
	@echo "    make dev          Start services"
	@echo "    make stop         Stop services"
	@echo "    make logs         Follow container logs"
	@echo "    make restart      Restart backend only"
	@echo "    make shell        Open bash in backend container"
	@echo ""
	@echo "  DATABASE:"
	@echo "    make migrate                  Apply pending migrations"
	@echo "    make migration MSG='add xyz'  Create a new migration"
	@echo "    make seed                     Re-run seed script"
	@echo ""
	@echo "  TESTING:"
	@echo "    make test         All tests (backend + frontend)"
	@echo "    make test-unit    Backend unit tests only (fast)"
	@echo "    make test-int     Integration tests"
	@echo ""
	@echo "  PRODUCTION:"
	@echo "    make prod-up          Start production stack (with Nginx)"
	@echo "    make prod-down        Stop production stack"
	@echo "    make prod-migrate     Run migrations in production"
	@echo ""
	@echo "  TROUBLESHOOTING:"
	@echo "    make wsl-setup    Fix 'docker not found' in WSL2"
	@echo "    make clean        Remove all containers and volumes"
	@echo ""
