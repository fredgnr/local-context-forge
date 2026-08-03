---
name: lcf-desktop-development
description: Implement or review Local Context Forge macOS Electron desktop changes across the React renderer, Electron Main trust boundary, Python sidecar, Node/QMD worker, runtime paths, packaging, and desktop test gates. Use for desktop architecture or code work; do not use for traceability-only documentation updates.
---

# LCF Desktop Development

1. Read the repository `AGENTS.md`, the active iteration, and each relevant
   accepted ADR before editing.
2. Read [architecture.md](references/architecture.md) before work that crosses
   a process, IPC, runtime, data, CLI-provider, model, packaging, or update
   boundary.
3. Read [testing.md](references/testing.md) before selecting or running
   verification.
4. State the affected processes and trust boundaries. Keep privileged behavior
   in Electron Main and expose only typed, allowlisted renderer operations.
5. Keep the change scoped to the active milestone. For legacy retirement,
   follow ADR-0015, ADR-0016, the W01-W16 execution ranks, and the strict
   `remove` / `retain` / `split` manifest. Require all W01 exits and then the W02
   packaged smoke before a destructive slice. Require slice-local ownership and
   either an affected replacement or the narrowly allowed pure-legacy
   `no-replacement / unsupported` disposition, plus fresh before/after package
   smoke, absence, and protected-path presence evidence. Reserve the W13
   engineering cutover/absence for final cleaned bytes; formal Draft bytes must
   independently pass release continuity and cutover/absence. Pre-1.0 breaking
   changes need not preserve legacy behavior, but must never delete user data,
   history, or external assets.
6. Run the applicable tests and preserve honest failure evidence. Do not treat
   source-mode tests as packaged-app proof.
7. Invoke `lcf-change-traceability` when behavior, a decision, a gate, or an
   iteration-owned path changes.

Stop and update or propose an ADR before contradicting an accepted decision.
