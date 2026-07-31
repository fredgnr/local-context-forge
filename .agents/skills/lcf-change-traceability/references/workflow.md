# Change traceability workflow

Use this workflow for every migration change, including documentation-only
changes that alter scope or governance.

## 1. Establish coordinates

Record the upstream baseline, working branch, active iteration, affected
requirement IDs, and accepted ADRs. Compare against the active iteration before
expanding scope. Put unrelated work in a later iteration.

## 2. Decide whether an ADR is required

Create an ADR before implementation when the change affects:

- process ownership or a trust boundary;
- IPC/authentication or an externally consumed protocol;
- persistent data, runtime paths, migration, backup, or rollback;
- bundled runtimes, platform support, artifact format, signing, or updates;
- provider fallback, MCP compatibility, security posture, or legacy retirement.

Use `Proposed` while review is open, `Accepted` after the choice is approved,
`Rejected` for a declined proposal, and `Superseded by ADR-NNNN` when replaced.
Do not use implementation completion as the ADR status.

Every ADR must contain status, date, context, decision, consequences,
alternatives, and validation gates. Describe limitations explicitly.

## 3. Maintain the iteration

Keep one active iteration record with:

- status and fixed scope;
- linked requirements and ADRs;
- tasks with owners or owning component;
- measurable acceptance criteria;
- validation log;
- risks, mitigations, and rollback point;
- changed-file list with purpose.

Check a task only when its stated artifact exists. Keep status `in-progress`
while a required gate is failed, blocked, or `not-run`.

## 4. Maintain the mapping

For each behavior change, update one row in the traceability matrix:

```text
requirement -> ADR -> iteration/task -> owned paths -> validation ID -> evidence
```

Use stable IDs:

- `REQ-<AREA>-NNN` for requirements;
- `ADR-NNNN` for decisions;
- `ITER-0001/TNN` for tasks;
- `VAL-<AREA>-NNN` for validation gates.

Never recycle an ID. Link to the authoritative record instead of duplicating
its full content.

## 5. Record evidence

For automated checks, record the exact command, environment, result, and
sanitized artifact path. For physical/manual gates, record the procedure,
machine architecture, macOS version, source and target versions, observed
result, and reviewer.

Use only:

- `pass`: the specified gate ran and met its assertion;
- `fail`: it ran and did not meet its assertion;
- `not-run`: it did not run, with a reason and unblock condition.

Source-mode, mocked, or CI results cannot stand in for clean-user, packaged
DMG, physical device, signing-secret, or updater evidence.

## 6. Close or hand off

Before claiming completion:

1. inspect the diff for unmapped owned paths;
2. resolve all relative links;
3. confirm required ADRs are accepted;
4. confirm every acceptance criterion points to passing evidence;
5. document known limitations and legacy behavior;
6. move unfinished work to a named later iteration.

Report facts at their actual state. Use “planned” or “not yet validated” for
capabilities without implementation or evidence.
