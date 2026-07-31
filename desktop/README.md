# Local Context Forge desktop

This directory contains the Electron Main/preload application. It establishes
the desktop trust boundary, a static `lcf://app/` renderer origin, a versioned
typed IPC facade, a bounded UDS API proxy, and explicit Python sidecar
supervision.

Project-wide status and boundaries are maintained in
[`docs/development/status.md`](../docs/development/status.md) and
[`docs/17-system-design.md`](../docs/17-system-design.md). The desktop source
foundation is merged, but the public trust pins, protected release, packaged
DMG, clean-user install, physical M4 runtime, and `N-1 → N` update gates remain
`not-run`. Do not present a source launch or CI build as an installable release.

Current status:

- Electron Main owns windows, permissions, IPC validation, the sidecar token,
  the private socket, and the exact child lifecycle.
- The sandboxed renderer receives only `window.localContextForge` version 1.0,
  including bounded API/runtime methods, MCP onboarding, update actions,
  `sources.selectRepository()`, and `app.version()`.
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

`electron-builder.yml` consumes all of the following audited inputs:

- `resources/renderer/` for the staged static renderer;
- `generated/sidecar/` for the Python sidecar;
- `generated/companion/` for the Node stdio MCP companion;
- `generated/qmd/` for bundled Node/QMD;
- `resources/update/update-metadata-ed25519-public.pem` and the matching public
  lock under `../runtime/`.

Release preparation must populate and audit every required input before
packaging. `resources/sidecar/README.txt` is only a source-tree marker and is
not packaged; companion notices are copied separately from `companion/`.

The base `electron-builder.yml` produces arm64 DMG/ZIP artifacts with
`identity: "-"` and the `-UNOFFICIAL` suffix. This is the local ad-hoc path, not
the formal self-signed release. `electron-builder.release.yml` extends the base,
forces code signing, and fixes the identity to
`Local Context Forge Self Signed`. Both configurations use ASAR and hardened
Electron fuses while deliberately keeping `hardenedRuntime: false` and
notarization disabled. Current `unprovisioned` trust locks make the formal
before-pack audit fail closed.

Source-mode tests and CI builds are not evidence that a DMG,
signing/notarization flow, packaged sidecar, clean-machine install, update
path, or local-source workflow has passed on physical Apple Silicon hardware.
Those physical gates remain `not-run`.

The complete developer test matrix is in
[`docs/development/contributor-handbook.md`](../docs/development/contributor-handbook.md);
the release procedure is in
[`docs/development/desktop-release.md`](../docs/development/desktop-release.md).

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

## Codex MCP onboarding

Main computes a domain-separated SHA-256 scope from normalized `CODEX_HOME`
(or `$HOME/.codex`) and stores a mode-`0600`
`mcp-target-ownership-<scope>.json` ledger in the exact mode-`0700`
Application Support data directory. The ledger carries an app-generated
256-bit `lcf-mcp-v1-<64 lowercase hex>` marker and exact bundled
command/argument paths. A move transaction may retain only the old and new
targets; after confirmation it contracts to the current target.

The Codex entry is considered app-owned only when the marker is its sole
environment key and marker, scoped ledger, command, and argument all match.
Missing, damaged, legacy, mismatched, extra-environment, or path-lookalike
state fails closed. The marker is not a secret or bridge capability, never
enters renderer/bridge messages, and is deleted from the companion process
environment before bridge discovery.

Configuration mutation additionally requires a packaged app in
`/Applications`. The `.app/Contents/Resources` chain, every intermediate
directory, bundled Node, and companion must be canonical non-symlinks, owned
by root or the effective UID, with no group/world write or
setuid/setgid/sticky bits. Source/debug mode, a different app location, or an
invalid bundle does not add, replace, or remove a target.

The service serializes its own operations and rechecks the target before
`codex mcp add/remove`, but Codex CLI provides no CAS or shared configuration
lock. A concurrent writer can still win the small interval between the final
list and mutation. A hostile same-UID process can read/write the Codex config
and ledger and can exploit check-use windows; this is a single-user,
non-adversarial-same-UID boundary, not an OS sandbox.

## Update recovery

Signed update check/download remains fail closed for source or unprovisioned
builds and for validation or network errors. A distinct no-payload IPC action
can, only after explicit user input, ask Main to open the compiled-in canonical
GitHub Releases page. Renderer code cannot choose or observe the URL, and an
external-open failure does not replace the signed updater's candidate/error
state. This escape does not download an unverified artifact and is not
automatic apply.

## Local and private repositories

Private remote repositories must be cloned first with the operator's existing
Git/SSH tooling. The desktop app does not request, store, proxy, or import
GitHub tokens, SSH keys, cookies, Keychain credentials, or credential-bearing
URLs.

The local-source flow keeps the absolute path in Main:

1. `sources.selectRepository()` invokes a typed, no-argument IPC method. Main
   verifies the exact renderer frame and opens Electron's native single-folder
   picker.
2. Main validates the selected directory and returns only
   `{ grantId, displayName }`. The opaque grant has the form
   `lcf-local:<64 lowercase hex characters>`; no path, parent, device, or inode
   enters the renderer.
3. The renderer submits the grant as the create-library `source`. After the
   proxy admits `POST /api/libraries`, Main consumes the grant and rewrites it
   to the absolute path only for the private UDS sidecar request. The request
   schema does not accept arbitrary local paths from the renderer.

Each grant has 256 bits of randomness, is held only in Main memory, expires
after five minutes using a monotonic clock, and is deleted before its single
consumption is checked. A successful new selection revokes older grants.
Application shutdown clears every grant and also closes the race where
selection finishes during shutdown.

Main checks the path both when issuing and consuming a grant. It must be an
absolute canonical non-symlink directory owned by the current effective UID,
and its device/inode identity must remain unchanged. It must be a strict
descendant of the user's home or below an individual volume under `/Volumes`.
Filesystem, home, `/Volumes`, individual volume, and selected mount roots are
rejected. The private desktop data root, product cache, known sensitive roots
(`.aws`, `.azure`, `.codex`, `.gcp`, `.kube`, `.secrets`, `.ssh`, and
`secrets`), and any canonical absolute `CODEX_HOME` are excluded using lexical
and resolved paths.

Main supplies the sidecar only the reviewed home and `/Volumes` roots as fixed
launch arguments; the desktop sidecar does not inherit
`LCF_LOCAL_SOURCE_ROOTS`. The sidecar can retain a library source in the
mode-`0700` desktop data root so it remains usable after restart. Every new
snapshot revalidates that the path exists, is canonical and non-symlinked,
stays within the fixed roots and outside data/sensitive roots, and still
belongs to the current UID. Moved, deleted, replaced, or re-owned sources fail
closed.

Responses cross a separate disclosure filter: local absolute library sources
are dropped, repository `path`/`file` fields must be safe relative paths, and
sidecar failures are normalized before reaching the renderer. This boundary
does not stop a malicious process running as the same macOS UID from swapping
a directory after validation but before snapshot I/O. Closing that TOCTOU
window requires security-scoped bookmarks, descriptor-based snapshotting, or
an OS sandbox.

The packaged macOS arm64 physical gates for home and external-volume sources,
private repositories, restart and move/delete behavior, and absolute-path
redaction remain `not-run`.
