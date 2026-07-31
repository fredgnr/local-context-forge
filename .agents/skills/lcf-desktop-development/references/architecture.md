# Desktop architecture guardrails

Use this reference when planning, implementing, or reviewing a change that
crosses a desktop process or distribution boundary.

## Process ownership

| Process | Owns | Must not own |
| --- | --- | --- |
| React renderer | Presentation, local UI state, typed user intent | Node access, secrets, raw paths, child processes, updater control |
| Preload bridge | Small typed IPC facade and payload validation | General RPC, arbitrary channels, business orchestration |
| Electron Main | Windows, permissions, filesystem mediation, process lifecycle, updater, protocol routing | Rendering untrusted Markdown with privilege |
| Python 3.13.14 sidecar | Existing LCF domain/API behavior packaged as PyInstaller `onedir` | Renderer communication, system-Python assumptions |
| Node 22 QMD worker | QMD/index operations in its bundled runtime | Electron lifecycle, user-installed Node assumptions |

Electron Main launches and supervises the sidecars. Use a private Unix domain
socket and a per-launch token; never expose a loopback TCP service merely for
renderer convenience. The renderer receives neither the token nor the socket
path.

## Fixed product constraints

- Target macOS Apple Silicon and ship a DMG as the default artifact.
- Bundle every required runtime. Do not require Docker, Homebrew, Python,
  Node.js, Git, or ctags on the target machine.
- Keep model weights outside the application bundle and download them only
  after explicit feature demand. Verify integrity before activation.
- Select Codex CLI by default during preflight. Select Cursor CLI only as a
  preflight fallback; never switch provider after a job starts.
- Keep the MCP surface compatible with the documented Context7-style tools.
- Treat legacy Docker/browser/public-HTTP/Host-Runner/container surfaces as
  deprecated and scheduled for removal under ADR-0015. Before the packaged
  cutover gate passes, only split Electron dependencies and add evidence; do
  not delete a legacy capability. Never infer removal from a top-level name:
  `web/src` is the renderer and `backend/app` contains the private UDS sidecar.
- Keep self-signing, lack of notarization, and lack of hardened runtime visible
  as release limitations; do not imply Apple trust or notarization.

## Review questions

- Can untrusted renderer or repository content choose a command, executable,
  endpoint, socket, update URL, or unrestricted filesystem path?
- Does every IPC message have a typed schema, size bound, timeout, and explicit
  error shape?
- Are child-process arguments constructed from allowlisted values without a
  shell?
- Does a crash, stale socket, partial download, or interrupted current-format
  backup/restore fail closed and leave recoverable state?
- Does the change work without user-installed runtimes and without network
  access except for an explicitly requested model/update download?
- Does it preserve data ownership, reject unknown/legacy layouts without
  guessing, and avoid automatically deleting data, volumes, backups, packages,
  or releases?

## Decision sources

- [Process boundary ADR](../../../../docs/adr/0001-electron-python-sidecar-boundary.md)
- [UDS and startup-token ADR](../../../../docs/adr/0002-uds-startup-token-protocol.md)
- [Release and update ADR](../../../../docs/adr/0003-macos-release-signing-update-policy.md)
- [Runtime paths and historical migration ADR](../../../../docs/adr/0004-runtime-paths-legacy-data-migration.md)
- [CLI provider attempt ADR](../../../../docs/adr/0005-provider-attempt-execution-boundary.md)
- [Product Git boundary ADR](../../../../docs/adr/0006-dulwich-product-git-boundary.md)
- [QMD broker ADR](../../../../docs/adr/0007-qmd-retrieval-broker-runtime.md)
- [MCP companion ADR](../../../../docs/adr/0008-mcp-companion-main-bridge.md)
- [Bundled runtime provenance ADR](../../../../docs/adr/0009-bundled-runtime-provenance.md)
- [Electron-only legacy retirement ADR](../../../../docs/adr/0015-electron-only-legacy-retirement.md)
- [Strict retirement manifest](../../../../docs/development/legacy-retirement.md)
