# Contributing

## Development setup

macOS:

```bash
./scripts/macos-bootstrap.sh --native
```

Start all native services together:

```bash
make dev-native
```

Or use Compose:

```bash
docker compose up -d --build
./scripts/demo-seed.sh
./scripts/smoke-test.sh
```

## Change rules

- Preserve immutable snapshot and proposal-before-publish boundaries.
- New generator claims require source references and schema validation.
- Do not add API keys, auth caches, private repositories or generated model
  caches to fixtures.
- MCP remains read-only; review/publish operations belong to the API/UI.
- Keep API changes reflected in OpenAPI, `docs/06-api-and-mcp.md`, examples and
  smoke tests.
- Pin new runtime dependencies and explain upgrade implications.

## Verification

Before a pull request:

```bash
make test
docker compose config --quiet
./scripts/smoke-test.sh
```

If shellcheck and PowerShell analyzers are available:

```bash
shellcheck scripts/*.sh
pwsh -NoProfile -Command "Invoke-ScriptAnalyzer scripts/windows-ollama-setup.ps1"
```

For documentation changes, verify all relative links and copy/paste every
changed command in a clean checkout.

## Commit and review

Keep commits scoped. Describe:

- user-visible behavior;
- data/schema or migration impact;
- security and privacy impact;
- tests run;
- whether QMD vectors must be rebuilt.

Generated Wiki content and model caches are runtime data, not source changes.
