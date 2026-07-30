---
name: lcf-change-traceability
description: Plan and record Local Context Forge changes by maintaining ADRs, iteration scope, requirement-to-validation mappings, evidence, risks, and changed-file ownership. Use for change planning, architectural decisions, validation records, release handoffs, or status claims; do not use as the desktop implementation guide.
---

# LCF Change Traceability

1. Read `AGENTS.md`, `docs/development/traceability.md`, and the active
   iteration before changing records.
2. Read [workflow.md](references/workflow.md) and classify the change as a
   requirement, decision, implementation task, validation result, or
   documentation-only correction.
3. Add or supersede an ADR before implementation when the change alters an
   accepted architecture, trust boundary, protocol, persistent path, migration,
   packaging, signing, update, or compatibility decision.
4. Give each requirement and validation a stable ID. Map it to the ADR,
   iteration, owned paths, gate, and current evidence without inventing results.
5. Update the active iteration's scope, tasks, risks, acceptance criteria,
   validation log, and changed-file list in the same change.
6. Mark a gate `pass` only from reproducible evidence. Record unavailable
   checks as `not-run` with the blocker; keep the iteration open.
7. Check every changed relative link and report any remaining unmapped file,
   requirement, decision, or failed gate.

Never rewrite accepted decision history; supersede it with a new ADR.
