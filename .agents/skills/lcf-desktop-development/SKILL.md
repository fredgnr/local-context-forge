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
5. Make the smallest behavior-preserving change that advances the active
   milestone. Keep legacy Docker paths until their documented retirement gate.
6. Run the applicable tests and preserve honest failure evidence. Do not treat
   source-mode tests as packaged-app proof.
7. Invoke `lcf-change-traceability` when behavior, a decision, a gate, or an
   iteration-owned path changes.

Stop and update or propose an ADR before contradicting an accepted decision.
