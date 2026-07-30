# Desktop validation guide

Use this reference to choose evidence appropriate to the changed layer. Start
with the narrowest applicable test and add every downstream gate affected by
the change.

## Evidence levels

| Level | Evidence | What it cannot prove |
| --- | --- | --- |
| L1 | Unit or static test for one package | Cross-process wiring or packaged resources |
| L2 | Main/renderer or sidecar contract integration test | Installed DMG behavior |
| L3 | Unpacked/packaged app smoke test on arm64 | Clean-machine install or update |
| L4 | DMG install test on a clean macOS user | Upgrade safety across versions |
| L5 | Physical 0.0.1 → 0.0.2 update rehearsal | Future releases without repeating the gate |

Never substitute a lower level for a required higher level.

## Change-to-gate routing

- Renderer/preload IPC: validate schema rejection, channel allowlisting,
  context isolation, sandboxing, and absence of Node globals.
- Main/sidecar lifecycle: validate unique launch token, UDS permissions,
  readiness timeout, crash handling, restart, shutdown, and stale-socket
  cleanup.
- Python packaging: run domain regression tests from the bundled PyInstaller
  `onedir`, inspect collected resources, and launch on a machine without system
  Python.
- Node/QMD packaging: run worker contract and index lifecycle tests with the
  bundled Node 22 runtime on a machine without system Node or QMD.
- CLI providers: cover Codex success, preflight-only Cursor selection, no
  post-start fallback, missing CLI, logged-out CLI, timeout, and cancellation.
- MCP: replay the Context7-compatible contract suite and confirm privileged
  review/publish operations are not added accidentally.
- Runtime paths/migration: test fresh install, repeat migration, interrupted
  copy, corrupt legacy data, insufficient disk, rollback, and concurrent-writer
  refusal.
- Model download: test consent, digest/signature mismatch, partial resume,
  atomic activation, offline behavior, and cache cleanup without data loss.
- Release/update: inspect the DMG and code identity, install as a clean user,
  preserve data, then perform the physical 0.0.1 → 0.0.2 gate. Exercise the
  verified DMG-download-and-open fallback when automatic update fails.

## Recording a result

Record each result in the active iteration with:

1. validation ID from `docs/development/traceability.md`;
2. exact command or manual procedure;
3. date, commit, macOS version, architecture, and clean-user/host details;
4. `pass`, `fail`, or `not-run`;
5. artifact or sanitized log path;
6. known limitation and follow-up owner.

Do not include tokens, signing material, private repository content, full user
paths, or model payloads in evidence.
