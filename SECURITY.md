# Security policy

## Supported versions

This repository is a reference implementation. Security fixes are applied to
the latest revision; no long-term support branches are promised yet.

## Reporting a vulnerability

Do not open a public issue with an exploit, private source, credentials, tokens,
internal hostnames, or backup archives.

Report privately to the repository owner/security contact configured for the
deployment. Include:

- affected commit/image digest and component;
- minimal reproduction using synthetic data;
- impact and required attacker access;
- whether credentials or private repositories may be exposed;
- suggested mitigation, if known.

If this project is published on a forge with private security advisories, use
that mechanism. Deployment owners should define a monitored security address
before exposing the service beyond localhost.

## Immediate response

If a Git/OpenAI/OIDC/backup secret may have leaked:

1. revoke or rotate it first;
2. stop the exposed endpoint or narrow the firewall;
3. preserve sanitized logs and IDs;
4. inspect Wiki, proposals, backups and clients for propagation;
5. restore from a verified backup if integrity is uncertain.

## Deployment assumptions

The safe default is one trusted user on localhost. Authentication, TLS and
multi-tenant authorization are required before a shared deployment.

Repository contents, LLM output, Markdown and MCP input are untrusted. Do not
run analyzed repositories on the host. Keep Codex credentials outside all
containers and project data.

## Desktop local/private repository boundary

Private remote repositories must be cloned first with the operator's existing
Git/SSH tooling. The desktop app does not request, store, proxy, or import a
GitHub token, SSH key, cookie, Keychain credential, or credential-bearing URL.

The sandboxed renderer can only invoke the typed, no-argument repository
selection IPC. Electron Main opens the native directory picker and returns only
an opaque `lcf-local:<64 lowercase hex characters>` grant plus a safe display
name; the selected path, parent path, device, and inode never cross into the
renderer. Grants contain 256 bits of randomness, live only in Main memory,
expire after five minutes on a monotonic clock, and are deleted before their
single consumption is validated. Issuing a new selection revokes prior grants,
and shutdown, including a selection racing shutdown, clears them all.

Main validates both grant issue and consumption. A selection must be an
absolute canonical non-symlink directory owned by the current effective UID,
with the same device/inode identity at consumption. It must be a strict
descendant of the user's home or of a mounted volume under `/Volumes`; the
filesystem root, home root, `/Volumes`, individual volume roots, and a selected
mount root are rejected. The desktop data directory, product cache, known
sensitive configuration roots (`.aws`, `.azure`, `.codex`, `.gcp`, `.kube`,
`.secrets`, `.ssh`, and `secrets`), and any canonical absolute `CODEX_HOME` are
excluded using both lexical and resolved paths.

Only after the API proxy admits `POST /api/libraries` does Main consume the
grant and rewrite it to the absolute path for the private sidecar request. The
renderer cannot submit an arbitrary local path. Main passes the sidecar its
reviewed local roots as fixed launch arguments rather than inheriting
`LCF_LOCAL_SOURCE_ROOTS`. The sidecar may persist the path inside the private
desktop data root so a library can work after restart, but every new snapshot
revalidates canonical location, symlink status, root/data/sensitive-directory
boundaries, and current UID ownership.

Desktop response filtering removes local absolute library sources, accepts only
safe repository-relative `path`/`file` fields, and normalizes sidecar failures.
This is a disclosure boundary, not an operating-system sandbox. A malicious
process running as the same macOS UID can still swap a directory after a check
and before snapshot I/O; closing that TOCTOU window requires a stronger design
such as security-scoped bookmarks, descriptor-based snapshotting, or App
Sandbox enforcement.

The packaged macOS arm64 physical gates for home and external-volume selection,
private repositories, restart and moved/deleted sources, and absolute-path
redaction remain `not-run`.

## Desktop MCP onboarding and update boundary

Codex MCP onboarding is scoped to the normalized effective `CODEX_HOME`
(`CODEX_HOME` when set, otherwise `$HOME/.codex`). Main hashes that path with a
domain-separated SHA-256 input and keeps a per-scope
`mcp-target-ownership-<64 lowercase hex>.json` ledger in the mode-`0700`
Application Support directory. The regular, single-link ledger must be owned
by the effective UID and have exact mode `0600`, including no setuid, setgid, or
sticky bits. It contains an app-generated
`lcf-mcp-v1-<64 lowercase hex>` marker and one exact bundled command/argument
target, or at most the old and new targets while an app move is being
reconciled.

The marker is the only environment key in an app-owned Codex target. Main
requires the marker, the matching per-scope ledger, and the exact command and
argument before it may reconnect or clear a target. Missing, malformed,
legacy/unscoped, mismatched, extra-environment, or lookalike state fails closed.
The marker is ownership metadata, not a secret or bridge capability; it never
crosses the renderer or bridge protocol, and the companion deletes it from its
environment before discovering the bridge.

Automatic mutation is also gated on a packaged app in `/Applications`. Every
component from `Local Context Forge.app` through `Contents`, `Resources`, the
intermediate directories, bundled Node, and companion must be canonical and
non-symlinked, owned by root or the effective UID, free of group/world write
bits, and free of setuid/setgid/sticky bits. Source/debug mode, another app
location, or an invalid bundle may inspect status but cannot add, replace, or
remove a Codex target.

These checks reduce accidental ownership confusion; they are not an
operating-system sandbox. Codex CLI exposes no compare-and-swap operation or
lock shared with the app, so another writer can still change the target between
the final `mcp list --json` recheck and `mcp add`/`mcp remove`. A malicious
same-UID process can read or alter both Codex configuration and the ledger, and
bundle/state validation also has check-use windows. The supported model is a
single trusted user without an adversarial process under the same UID.

Update check and download remain Main-owned and fail closed when the app is
source/unpackaged, the trust anchor is unprovisioned, or metadata, signature,
network, cache, or DMG validation fails. A separate typed, no-payload action may
open only the compiled-in canonical GitHub Releases page after explicit user
input. The renderer neither supplies nor receives a URL, and a failure to open
that page does not overwrite signed-updater candidate/error state. This manual
escape is not a verified download, automatic apply, or proof that a Release
exists.

Release publication is fail-closed across two runs. A tag push may use the
only repository secret in the tag-only `macos-signing` Environment to create
and remotely verify a Draft; the Draft job has no Environment or secret.
Publishing requires `workflow_dispatch --ref main` after physical testing.
The `release_tag` is data, not the verifier checkout ref. The promotion job
uses the branch-only, secret-free `macos-release` Environment, re-downloads the
Draft, binds the tested `release-manifest.json` SHA-256, verifies policy from
trusted `main` against an isolated tag worktree, fresh-peels the tag, and
publishes only a previously fixed Release ID. Immediately before the PATCH,
promotion order and `make_latest` are recomputed against a freshly fetched
`origin/main` comparison ref; the workflow-start HEAD is not trusted for this
ordering decision because another tag may have been promoted concurrently.

Both Environments require independent reviewers, self-review prevention, and
administrator bypass disabled in the GitHub UI. Protected-main pull-request
rules, owner-only release-tag creation, immutable release-tag update/deletion
rules, and GitHub Immutable Releases are also mandatory. Promotion rejects any
already-published pre-state as a release security incident; it does not turn a
rerun green as an idempotent success. After the single REST publication PATCH,
it runs `gh release verify` and verifies the immutable published Release and
the full asset set again.

Repository owners, settings administrators, and contents writers able to
change trusted `main` or the workflow remain roots of trust. GitHub Drafts
provide no asset compare-and-swap operation, so a mutation between final
verification and the fixed-ID PATCH can only be detected by post-publication
verification. Immutable Releases protect the published state, not that Draft
window.

The real packaged `/Applications`/official-Codex gate, protected signed
release settings, clean-user DMG test, and physical 0.0.1 to 0.0.2 update gate
remain `not-run`. The current decision is **source merge GO / release NO-GO**.

See [the detailed threat model](docs/10-security.md) and
[the desktop boundary notes](desktop/README.md).
