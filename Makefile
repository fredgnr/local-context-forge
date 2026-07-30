SHELL := /bin/sh

.PHONY: help install doctor status uninstall bootstrap up down stop restart build ps logs smoke demo backup restore \
	qmd-status qmd-embed qmd-embed-native dev-native dev-api dev-mcp dev-web test handbook

help:
	@printf '%s\n' \
	  'make install     All-in-one macOS install, start, verify and open Web' \
	  'make doctor      Read-only deployment and provider diagnostics' \
	  'make status      Show Compose and host runner status' \
	  'make uninstall   Remove services but preserve data/imports/backups' \
	  'make bootstrap   Check/install macOS prerequisites' \
	  'make up          Build and start api/mcp/web' \
	  'make smoke       Run read-only smoke checks' \
	  'make demo        Seed and publish the deterministic demo' \
	  'make backup      Create a backup under ./backups' \
	  'make restore ARCHIVE=... TARGET=...  Restore to the configured data path' \
	  'make qmd-embed   Build local hybrid-search embeddings' \
	  'make qmd-embed-native  Ask the current API to embed (first verify it is native)' \
	  'make dev-native  Start native api/mcp/web together' \
	  'make handbook    Build the printable Chinese PDF handbook' \
	  'make logs        Follow service logs' \
	  'make down        Remove containers, keep ./data'

install:
	./install.sh

doctor:
	./scripts/lcf doctor

status:
	./scripts/lcf status

uninstall:
	./scripts/lcf uninstall

bootstrap:
	./scripts/macos-bootstrap.sh

build:
	docker compose build

up:
	./scripts/lcf start

stop:
	./scripts/lcf stop

down:
	./scripts/lcf down

restart:
	./scripts/lcf restart

ps:
	./scripts/lcf status

logs:
	./scripts/lcf logs

smoke:
	./scripts/smoke-test.sh

demo:
	./scripts/demo-seed.sh

backup:
	./scripts/backup.sh

restore:
	@test -n "$(ARCHIVE)" || { printf '%s\n' 'ARCHIVE is required'; exit 2; }
	@test -n "$(TARGET)" || { printf '%s\n' 'TARGET is required and must match LOCAL_DATA_DIR'; exit 2; }
	./scripts/restore.sh --archive "$(ARCHIVE)" --target "$(TARGET)"

qmd-status:
	docker compose exec api qmd status

qmd-embed:
	./scripts/reindex.sh --embed

qmd-embed-native:
	./scripts/reindex.sh --embed

dev-native:
	./scripts/dev-native.sh

dev-api:
	cd backend && LCF_DATA_DIR="$(CURDIR)/data" LCF_LOCAL_SOURCE_ROOTS="$(CURDIR)/examples:$(CURDIR)/imports" LCF_CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173 ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

dev-mcp:
	cd mcp && BACKEND_URL=http://127.0.0.1:8000 MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=8001 ../.venv/bin/python -m mcp_server.server

dev-web:
	cd web && npm run dev -- --host 127.0.0.1

test:
	cd backend && ../.venv/bin/pytest
	cd web && npm test
	cd web && npm run typecheck
	cd web && npm run build

handbook:
	python3 tools/build_handbook.py
