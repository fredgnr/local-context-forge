SHELL := /bin/sh

.PHONY: help install doctor status uninstall bootstrap up down stop restart build ps logs smoke demo backup restore \
	qmd-status qmd-embed qmd-embed-native dev-native dev-api dev-mcp dev-web test handbook \
	ci-source ci-python-install ci-python ci-qmd-worker ci-ipc-source web-install ci-web pre1-work-plan-check \
	packaged-smoke-policy-check engineering-smoke-assemble \
	desktop-install desktop-test desktop-typecheck desktop-build desktop-ci \
	python-sidecar-source-verify python-sidecar-install-python \
	python-sidecar-build python-sidecar-audit python-sidecar-packaging-test \
	qmd-runtime-source-verify qmd-runtime-build qmd-runtime-audit \
	renderer-stage renderer-audit

UV ?= uv
NPM ?= npm
PYTHON ?= python3
PYTHON_SIDECAR_ARCHIVE ?=
PYTHON_SIDECAR_HASH_MANIFEST ?=
PYTHON_SIDECAR_INSTALL_ROOT ?= /Library/Frameworks/Python.framework/Versions/3.13
PYTHON_SIDECAR_FRAMEWORK_PYTHON ?= $(PYTHON_SIDECAR_INSTALL_ROOT)/bin/python3.13
NODE ?= node
QMD_NODE_ARCHIVE ?=
QMD_NODE_HASH_MANIFEST ?=
QMD_SOURCE_RESULT ?=

help:
	@printf '%s\n' \
	  'make install     LEGACY Docker/Web install; this is not the Electron installer' \
	  'make doctor      Read-only LEGACY deployment and provider diagnostics' \
	  'make status      Show LEGACY Compose and host runner status' \
	  'make uninstall   Remove LEGACY services; preserve data/imports/backups' \
	  'make bootstrap   Check/install LEGACY macOS prerequisites' \
	  'make up          Build and start LEGACY api/mcp/web' \
	  'make smoke       Run read-only smoke checks' \
	  'make demo        Seed and publish the deterministic demo' \
	  'make backup      Create a LEGACY data backup under ./backups' \
	  'make restore ARCHIVE=... TARGET=...  Restore the explicit LEGACY data path' \
	  'make qmd-embed   Build local hybrid-search embeddings' \
	  'make qmd-embed-native  Ask the current API to embed (first verify it is native)' \
	  'make dev-native  Start native api/mcp/web together' \
	  'make ci-source   Run declared Python/MCP/Host, QMD, Web and Electron source gates (guide-site excluded)' \
	  'make ci-python   Run frozen Python source tests and repository checks' \
	  'make ci-qmd-worker  Install safely and run QMD source tests with network/model traps' \
	  'make pre1-work-plan-check  Validate canonical W01-W16 governance mappings' \
	  'make packaged-smoke-policy-check  Validate isolated W02 engineering-smoke assembly policy' \
	  'make engineering-smoke-assemble  Assemble/audit macOS arm64 .app dir without launching it (staging required)' \
	  'make ci-ipc-source  Run the source-mode Python desktop IPC contract' \
	  'make ci-web      Install and run Web source tests, typecheck and build' \
	  'make desktop-ci  Install and run desktop tests, typecheck and build' \
	  'make python-sidecar-source-verify  Verify pinned Python archive/pkg bytes' \
	  'make python-sidecar-install-python  Verify the locked pkg and sealed Framework binding' \
	  'make python-sidecar-build  Build, smoke, audit and atomically stage sidecar' \
	  'make python-sidecar-audit  Re-audit the current Python sidecar staging' \
	  'make python-sidecar-packaging-test  Run portable packaging policy tests' \
	  'make qmd-runtime-source-verify  Verify pinned Node archive/hash bytes' \
	  'make qmd-runtime-build  Build, native-smoke, audit and stage Node/QMD' \
	  'make qmd-runtime-audit  Re-audit the current QMD runtime staging' \
	  'make renderer-stage  Stage audited web/dist for desktop packaging' \
	  'make renderer-audit  Re-audit the staged production renderer' \
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

ci-source: ci-python ci-qmd-worker ci-web desktop-ci

ci-python-install:
	cd backend && $(UV) sync --frozen --extra dev
	$(UV) pip install --python backend/.venv/bin/python --editable ./mcp

ci-python: ci-python-install
	backend/.venv/bin/python -m compileall -q mcp/mcp_server
	backend/.venv/bin/python -c "import mcp_server.client; import mcp_server.server"
	cd backend && .venv/bin/pytest
	backend/.venv/bin/python -m unittest discover -s host_runner/tests -t .
	cd examples/demo-python-sdk && ../../backend/.venv/bin/python -m pytest
	backend/.venv/bin/python tools/check_version_sync.py
	backend/.venv/bin/python tools/check_markdown_links.py
	backend/.venv/bin/python -B tools/check_ci_coverage.py
	backend/.venv/bin/python -B tools/check_w01_evidence.py
	backend/.venv/bin/python -B tools/check_pre1_work_plan.py
	backend/.venv/bin/python -B tools/check_packaged_smoke_policy.py
	backend/.venv/bin/python -B -m unittest discover -s tools/tests -p 'test_*.py'

ci-qmd-worker:
	cd desktop/workers/qmd && $(NPM) ci --ignore-scripts --omit=optional --no-audit --no-fund
	cd desktop/workers/qmd && $(NPM) test -- --node "$(NODE)" $(if $(strip $(QMD_SOURCE_RESULT)),--result "$(QMD_SOURCE_RESULT)")

pre1-work-plan-check:
	$(PYTHON) -B tools/check_ci_coverage.py
	$(PYTHON) -B tools/check_w01_evidence.py
	$(PYTHON) -B tools/check_pre1_work_plan.py
	$(PYTHON) -B tools/check_packaged_smoke_policy.py
	$(PYTHON) -B -m unittest discover -s tools/tests -p 'test_*.py'

packaged-smoke-policy-check:
	$(NODE) --test tools/tests/verify_reviewed_python_framework.test.cjs
	$(PYTHON) -S -B tools/check_packaged_smoke_policy.py
	$(PYTHON) -S -B -m unittest tools.tests.test_check_packaged_smoke_policy
	$(PYTHON) -S -B -m unittest tools.tests.test_check_exact_git_provenance

engineering-smoke-assemble:
	@test "$$(uname -s)" = Darwin || { printf '%s\n' 'Engineering-smoke assembly requires macOS'; exit 2; }
	@test "$$(uname -m)" = arm64 || { printf '%s\n' 'Engineering-smoke assembly requires native arm64'; exit 2; }
	cd desktop && $(NPM) run test:engineering-smoke
	cd desktop && $(NPM) run build:engineering-smoke
	cd desktop && $(NPM) run prepare:engineering-smoke
	cd desktop && $(NPM) run pack:engineering-smoke
	cd desktop && $(NPM) --silent run audit:engineering-smoke

ci-ipc-source: ci-python-install
	cd backend && .venv/bin/pytest ../tests/backend/test_desktop_transport.py

web-install:
	cd web && $(NPM) ci

ci-web: web-install
	cd web && $(NPM) test
	cd web && $(NPM) run typecheck
	cd web && $(NPM) run build

desktop-install:
	cd desktop && ELECTRON_SKIP_BINARY_DOWNLOAD=1 $(NPM) ci --ignore-scripts

desktop-test:
	cd desktop && $(NPM) test

desktop-typecheck:
	cd desktop && $(NPM) run typecheck

desktop-build:
	cd desktop && $(NPM) run build

desktop-ci: web-install desktop-install
	+$(MAKE) desktop-test
	+$(MAKE) desktop-typecheck
	+$(MAKE) desktop-build

python-sidecar-source-verify:
	@test -n "$(LCF_REVIEWED_SOURCE_ROOT)" || { printf '%s\n' 'LCF_REVIEWED_SOURCE_ROOT is required'; exit 2; }
	@test -n "$(LCF_REVIEWED_BUILD_PYTHON)" || { printf '%s\n' 'LCF_REVIEWED_BUILD_PYTHON is required'; exit 2; }
	@test "$(LCF_REVIEWED_BUILD_PYTHON)" = "$(PYTHON_SIDECAR_FRAMEWORK_PYTHON)" || { printf '%s\n' 'Reviewed build Python differs from the locked framework'; exit 2; }
	@test -n "$(PYTHON_SIDECAR_ARCHIVE)" || { printf '%s\n' 'PYTHON_SIDECAR_ARCHIVE is required'; exit 2; }
	@test -n "$(PYTHON_SIDECAR_HASH_MANIFEST)" || { printf '%s\n' 'PYTHON_SIDECAR_HASH_MANIFEST is required'; exit 2; }
	"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/build_python_sidecar.py" --verify-source-only \
		--archive "$(PYTHON_SIDECAR_ARCHIVE)" \
		--hash-manifest "$(PYTHON_SIDECAR_HASH_MANIFEST)"

python-sidecar-install-python: python-sidecar-source-verify
	"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py" \
		--install-reviewed-python \
		--archive "$(PYTHON_SIDECAR_ARCHIVE)" \
		--hash-manifest "$(PYTHON_SIDECAR_HASH_MANIFEST)"

python-sidecar-build: python-sidecar-install-python
	@test -n "$(LCF_REVIEWED_SOURCE_ROOT)" || { printf '%s\n' 'LCF_REVIEWED_SOURCE_ROOT is required'; exit 2; }
	@test -n "$(LCF_REVIEWED_BUILD_PYTHON)" || { printf '%s\n' 'LCF_REVIEWED_BUILD_PYTHON is required'; exit 2; }
	@test "$(LCF_REVIEWED_BUILD_PYTHON)" = "$(PYTHON_SIDECAR_FRAMEWORK_PYTHON)" || { printf '%s\n' 'Reviewed build Python differs from the locked framework'; exit 2; }
	LCF_PYTHON_DISTRIBUTION_ARCHIVE="$(PYTHON_SIDECAR_ARCHIVE)" \
	LCF_PYTHON_DISTRIBUTION_HASH_MANIFEST="$(PYTHON_SIDECAR_HASH_MANIFEST)" \
	LCF_PYTHON_INSTALL_ROOT="$(PYTHON_SIDECAR_INSTALL_ROOT)" \
	LCF_REVIEWED_BUILD_PYTHON="$(LCF_REVIEWED_BUILD_PYTHON)" \
	LCF_REVIEWED_SOURCE_ROOT="$(LCF_REVIEWED_SOURCE_ROOT)" \
	LCF_SOURCE_SHA="$(LCF_SOURCE_SHA)" \
	LCF_SOURCE_TREE="$(LCF_SOURCE_TREE)" \
	"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/bootstrap_python_sidecar.py"

python-sidecar-audit:
	@test -n "$(LCF_REVIEWED_SOURCE_ROOT)" || { printf '%s\n' 'LCF_REVIEWED_SOURCE_ROOT is required'; exit 2; }
	@test -n "$(LCF_REVIEWED_BUILD_PYTHON)" || { printf '%s\n' 'LCF_REVIEWED_BUILD_PYTHON is required'; exit 2; }
	"$(LCF_REVIEWED_BUILD_PYTHON)" -I -S "$(LCF_REVIEWED_SOURCE_ROOT)/tools/audit_python_sidecar.py" \
		--bundle "$(LCF_REVIEWED_SOURCE_ROOT)/desktop/generated/sidecar"

python-sidecar-packaging-test:
	cd backend && .venv/bin/pytest ../tests/backend/test_python_sidecar_packaging.py

qmd-runtime-source-verify:
	@test -n "$(QMD_NODE_ARCHIVE)" || { printf '%s\n' 'QMD_NODE_ARCHIVE is required'; exit 2; }
	@test -n "$(QMD_NODE_HASH_MANIFEST)" || { printf '%s\n' 'QMD_NODE_HASH_MANIFEST is required'; exit 2; }
	$(NODE) desktop/scripts/buildQmdRuntime.cjs --verify-source-only \
		--archive "$(QMD_NODE_ARCHIVE)" \
		--hash-manifest "$(QMD_NODE_HASH_MANIFEST)"

qmd-runtime-build: qmd-runtime-source-verify
	LCF_QMD_NODE_ARCHIVE="$(QMD_NODE_ARCHIVE)" \
	LCF_QMD_NODE_HASH_MANIFEST="$(QMD_NODE_HASH_MANIFEST)" \
	$(NODE) desktop/scripts/buildQmdRuntime.cjs

qmd-runtime-audit:
	$(NODE) desktop/scripts/auditQmdRuntime.cjs

renderer-stage:
	$(NODE) desktop/scripts/stageRenderer.cjs

renderer-audit:
	$(NODE) desktop/scripts/auditRenderer.cjs

handbook:
	python3 tools/build_handbook.py
