# Desktop validation guide

Use this reference to choose evidence appropriate to the changed layer. Start
with the narrowest applicable test and add every downstream gate affected by
the change.

## Evidence levels

| Level | Evidence | What it cannot prove |
| --- | --- | --- |
| L1 | Unit or static test for one package | Cross-process wiring or packaged resources |
| L2 | Main/renderer or sidecar contract integration test | Installed DMG behavior |
| L3 | Unpacked/packaged engineering app smoke test on arm64 | Complete engineering matrix, clean-machine install, signing, release, or update |
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
- Runtime paths/data: test fresh/current layout, current-format backup/restore,
  interrupted staging, corrupt input, insufficient disk, rollback, and
  unknown/legacy-layout fail-closed. Do not require or claim a legacy importer.
- Legacy retirement: first pass all W01 exits, then `VAL-PACKAGED-SMOKE-001`.
  For each independent slice, record exact ownership/split and either affected
  replacement or the constrained pure-legacy `no-replacement / unsupported`
  disposition, fresh before/after package smoke, focused/aggregate source
  regression, slice absence, protected
  renderer/private-UDS/QMD/desktop-MCP/release-safety presence, and no user or
  external-data effect. Build the full engineering package only from the
  cleaned tree; reserve `VAL-ELECTRON-CUTOVER-001` and aggregate absence for
  final engineering bytes. Formal Draft bytes independently require continuity
  and complete cutover/absence. Source evidence alone never authorizes deletion.
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
