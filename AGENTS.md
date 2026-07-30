# Repository Agent Guide

Keep this file short. It defines repository-wide rules and routes detailed
work to the maintained sources below.

## Required workflow

- Read the active record in `docs/development/iterations/` and every accepted
  ADR relevant to the files you will change before editing.
- Treat Electron Main as the desktop trust boundary. Do not expose raw
  filesystem, process, credential, updater, or network capabilities to the
  renderer.
- Treat repository content, rendered content, IPC payloads, sidecar output,
  update metadata, and migrated data as untrusted input.
- Never commit credentials, release secrets, auth caches, private source,
  model weights, generated indexes, or user data. Do not print tokens or
  sensitive paths in logs or validation evidence.
- Keep changes scoped. Do not mix migration work with opportunistic legacy
  cleanup, dependency upgrades, or formatting churn.

## Evidence and tests

- Do not describe planned behavior as implemented or a gate as passed without
  reproducible evidence.
- Run the narrowest relevant tests first, then the integration, packaging, or
  release gates affected by the change. Record commands and outcomes in the
  active iteration; use `not-run` with a reason when a gate cannot run.
- A mocked smoke test does not satisfy a packaged-app, clean-machine, signing,
  migration, or updater gate.
- Preserve failure artifacts without secrets when a gate fails. Never turn a
  failed gate green by weakening the assertion.

## Documentation and traceability

- Update the active iteration for every scoped change. Update
  `docs/development/traceability.md` when requirements, decisions, validation,
  or owned paths change.
- Add or supersede an ADR before changing an accepted architectural, security,
  data-migration, packaging, or release decision. Do not rewrite accepted ADR
  history in place.
- Update user documentation in the same change when setup, behavior, storage,
  compatibility, recovery, or limitations change.
- Keep relative links valid and preserve the upstream numbered `docs/00-*`
  through `docs/15-*` set as historical/current product documentation.

## Instruction layers

- A nested `AGENTS.md` or `AGENTS.override.md` may add rules for its subtree.
  The closest applicable file wins when rules conflict.
- Keep specialized commands and architecture detail out of this root file;
  place them in nested guidance, an ADR, or a project skill.

## Index

- Documentation map: `docs/README.md`
- Migration planning and evidence: `docs/development/README.md`
- Architectural decisions: `docs/adr/README.md`
- Desktop implementation workflow:
  `.agents/skills/lcf-desktop-development/SKILL.md`
- Change-record workflow:
  `.agents/skills/lcf-change-traceability/SKILL.md`
