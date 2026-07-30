# Local Context Forge desktop foundation

This directory contains the P1 Electron Main/preload foundation. It establishes
the desktop trust boundary, a static `lcf://app/` renderer origin, a versioned
typed IPC facade, a bounded UDS API proxy, and explicit Python sidecar
supervision.

Current status:

- Electron Main owns windows, permissions, IPC validation, the sidecar token,
  the private socket, and the exact child lifecycle.
- The sandboxed renderer receives only `window.localContextForge` version 1.0:
  `api.request({ method, path, body?, timeoutMs })`, `runtime.get/retry/subscribe`,
  and `app.version()`.
- API methods, paths, queries, request schemas, payload sizes, timeouts, and
  concurrency are allowlisted in Main. `/api/admin/*` is not reachable.
- `lcf://app/` serves only staged static files, with symlink/traversal checks,
  explicit MIME types, and an HTML CSP whose `connect-src` is `none`.
- Development sidecar launch requires an explicit absolute
  `LCF_SIDECAR_BIN`; packaged launch uses only
  `resources/sidecar/lcf-service`.
- The Main-owned fd3 control pipe carries the framed one-launch token and then
  remains open as parent-liveness. Its EOF is the P1 authorized shutdown
  signal; Main allows the sidecar graceful window before signalling only that
  exact child with `SIGTERM` and, if still required, `SIGKILL`.

## Local validation

```sh
npm install
npm run typecheck
npm test
npm run build
```

`resources/renderer/` and `resources/sidecar/` are staging directories. A
release build must replace their marker files with the built renderer and
signed PyInstaller `onedir` sidecar. `electron-builder.yml` targets arm64 DMG
and ZIP, uses ASAR and hardened Electron fuses, and deliberately keeps
`hardenedRuntime: false`, no notarization, and the fixed self-signing identity.

This P1 source-mode work does not add an updater or Playwright and is not
evidence that a DMG, signing/notarization flow, packaged sidecar, clean-machine
install, or update path has passed. Those gates remain not run.

For a source-mode launch, first build `../web` and use its absolute `dist`
directory as `LCF_RENDERER_DIR`. Install the backend development environment so
that the absolute executable `../backend/.venv/bin/lcf-service` exists and is
executable, then set that absolute path as `LCF_SIDECAR_BIN`:

```sh
LCF_RENDERER_DIR=/absolute/path/to/web/dist \
LCF_SIDECAR_BIN=/absolute/path/to/backend/.venv/bin/lcf-service \
npm run start:source
```

The source launcher never searches `PATH` for the sidecar. A successful source
launch is still only source-mode evidence; it does not establish that staged
resources, self-signing, DMG installation, or a clean Apple Silicon host work.

P1 accepts new library sources only in the form
`https://github.com/<owner>/<repository>[.git]` with no credentials, query, or
fragment and only the default HTTPS port. Local paths, `file:`/SSH sources, and
other hosts fail closed. A later milestone must add a Main-owned file picker
and scoped grant before the renderer can request a local source.
