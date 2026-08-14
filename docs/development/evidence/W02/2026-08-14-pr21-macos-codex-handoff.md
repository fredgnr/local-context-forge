# PR #21 macOS Codex 迭代交接

本文是 Draft PR #21 的一次 **documentation-only handoff**。它把当前失败事实、下一轮
macOS Apple Silicon 调查入口、安全边界和完成条件交给本地 Codex；本文本身不修复代码，
也不把任何失败或 `not-run` 门禁提升为 `pass`。

本文件所在提交就是交接提交。提交不能在自身内容中嵌入自己的 commit SHA，因此本地 Codex
启动时必须用 `git rev-parse HEAD` 与 `git rev-parse HEAD^{tree}` 记录实际 handoff 坐标；下表中的
head/tree 是创建本交接提交之前的 exact technical candidate，用于绑定已观察到的失败。

## 1. 交接坐标与当前结论

| 字段 | 值 |
| --- | --- |
| canonical repository | `fredgnr/local-context-forge` |
| PR | [Draft #21](https://github.com/fredgnr/local-context-forge/pull/21) |
| branch | `agent/w02a-engineering-smoke-boundary` |
| base | `main@1786255b55dd1a78659ed92235893876175a0722` |
| pre-handoff exact head | `70b1823259590725d6f579b97fa294d3d9dcf728` |
| pre-handoff exact tree | `a706817f28b170bab1fe9fe6c3a6e8b673e5dc81` |
| pre-handoff parent | `6eec41125b431a9fd99d8b1821362573de1b5b8a` |
| Desktop source CI | run [`31580628860`](https://github.com/fredgnr/local-context-forge/actions/runs/31580628860): `success` |
| Engineering smoke | run [`31580628877`](https://github.com/fredgnr/local-context-forge/actions/runs/31580628877), job `94062603909`: `failure` |
| Containers | run [`31580628857`](https://github.com/fredgnr/local-context-forge/actions/runs/31580628857): `success`, PR path no publish |
| engineering product artifacts | `[]` |
| technical disposition | **fail / superseded by the handoff head only for coordination, not fixed** |
| independent acceptance | `pending`; the latest binding independent verdict remains `NO-GO` |
| canonical activation | `blocked` |
| W02 | `in-progress` |
| `VAL-PACKAGED-SMOKE-001` | `not-run` |
| W10/W11 | `locked` |
| packaged App launch | `not-run` |
| public release | `NO-GO` |

The handoff commit changes the exact PR head and therefore invalidates inheritance of the three pre-handoff
workflow results. Fresh workflows on the handoff head may reproduce the same Engineering failure; that is
expected because this commit contains no technical fix. Source or Containers success must never compensate
for an Engineering failure.

## 2. 最新失败事实

The pre-handoff Engineering run completed exact archive, hash-manifest, signed outer package,
`Python_Framework.pkg`, no-op postinstall, installer and reviewed framework preparation checks. The primary
failure occurred in `Seal reviewed build Python framework` after the interpreter and framework binary digests
had passed:

```text
VerificationError: Reviewed Python framework core fingerprint changed
```

The current repository hard-codes the intended installed/sealed framework fingerprint as:

```text
ba58cfb559f29c34beb962cb5d88587e9104f5610c255a58494c2945c1e863ec
```

That value is present in both:

- `tools/verify_reviewed_python_framework.cjs`;
- `backend/packaging/python-sidecar-toolchain.lock.json`.

The previous diagnosis established that the locked archive contains symlinks with mode `0775` while macOS
Installer materializes those symlinks as `0777`. Mapping the previously observed 33 symlink modes produced
`ba58…` offline, but the fresh exact-head macOS run still disagreed. Therefore the model "only those 33
symlink modes change" is incomplete. Do **not** fix this by guessing another opaque digest.

Because the seal failed:

- source provenance binding after the framework seal was skipped;
- frozen sidecar build/audit was skipped;
- renderer and Desktop profile staging were skipped;
- `.app` directory assembly, bundle inventory and bundle audit were skipped;
- the packaged App was not launched;
- no engineering product artifact was uploaded.

The existing `Validate Python scratch cleanup` result only covers its declared runner-temp, reviewed-source
and repository scratch scopes. It is not independent proof that a failed `/Library/Frameworks` transaction
restored or removed the exact system framework state.

## 3. 本轮唯一技术目标

Continue the same stable work package and existing PR:

```text
Work: W02
Task: TODO-PACKAGED-SMOKE-001
Requirement: REQ-PACKAGED-SMOKE-001
ADR: ADR-0016
Iteration: ITER-0008/I01
Validation: VAL-PACKAGED-SMOKE-001
```

Do not create a new W number, Requirement, TODO, Validation ID, replacement branch or second PR. The immediate
objective is to make the reviewed framework contract explainable and stable on real macOS Installer output,
then obtain one new exact-head technical candidate whose Source, Engineering and Containers workflows are all
fresh and green. PR #21 must remain Draft; no merge is authorized by this handoff.

## 4. 必须先读的文件

Read the repository state at the actual handoff head, then at minimum read:

- [`AGENTS.md`](../../../../AGENTS.md);
- [desktop development skill](../../../../.agents/skills/lcf-desktop-development/SKILL.md);
- [change traceability skill](../../../../.agents/skills/lcf-change-traceability/SKILL.md);
- [ADR-0016](../../../adr/0016-pre1-incremental-retirement-engineering-package.md);
- [ITER-0008](../../iterations/0008-incremental-retirement-engineering-package.md);
- [evidence rules](../README.md);
- [append-only PR #21 remediation history](2026-08-07-pr21-remediation.md);
- `.github/workflows/packaged-smoke.yml`;
- `.github/workflows/desktop-release.yml`;
- `tools/verify_reviewed_python_framework.cjs`;
- `tools/tests/verify_reviewed_python_framework.test.cjs`;
- `backend/packaging/python-sidecar-toolchain.lock.json`;
- `desktop/scripts/beforePack.cjs`;
- `tools/check_packaged_smoke_policy.py`;
- `tools/tests/test_check_packaged_smoke_policy.py`;
- `tests/backend/test_python_sidecar_packaging.py`;
- `tests/backend/test_desktop_release_workflow_policy.py`.

The PR body is currently stale and still describes an older candidate. Treat live GitHub metadata, the actual
checkout and this handoff as the current entry point; update the PR body only after a new exact technical
candidate has stable evidence.

## 5. 推荐调查与实现顺序

### 5.1 建立安全的本地基线

Run and record, without modifying the worktree first:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git log --oneline --decorate -15
uname -m
sw_vers
node --version
npm --version
python3 --version
```

The expected branch is `agent/w02a-engineering-smoke-boundary`. Do not reset, clean, stash, overwrite or delete
unrelated user work. Do not use `git add .`, `git add -A` or `git add --all`; stage reviewed paths explicitly.

### 5.2 在真实 macOS 上复现，但先保护系统 framework

The workflow mutates `/Library/Frameworks/Python.framework/Versions/3.13`. Before any privileged local
reproduction:

1. inspect whether that exact path already exists;
2. record its `dev:ino`, owner, mode and whether it is a real directory;
3. use the existing exact-parent, exact-suffix and identity-bound quarantine/rollback design;
4. do not delete or traverse unrelated versions, user data or other framework roots;
5. prefer a disposable/recoverable Apple Silicon environment when possible;
6. stop if the previous framework cannot be restored exactly after a failed experiment.

Never use a broad wildcard or recursive privileged cleanup against an unbound pathname. Never treat runner or
machine teardown as proof of product cleanup.

### 5.3 让 fingerprint 失败可诊断

Extend the verifier or its reviewed loader so one physical/no-follow traversal produces a bounded canonical
observed inventory and comparison result. On mismatch, print only sanitized information such as:

```text
expected_digest=<64-hex>
observed_digest=<64-hex>
expected_entries=<count>
observed_entries=<count>
difference_counts: missing/extra/type/mode/target/size/content
first_differences: <bounded relative-path records>
truncated=true|false
```

Requirements:

- use framework-relative paths only;
- never print file contents, absolute user paths, environment dumps, nonce/token or Secret-like values;
- sort diagnostics deterministically and cap the number of reported differences;
- derive digest and diagnostics from the same held traversal, not from a second raceable scan;
- preserve `O_NOFOLLOW`, held descriptor identity, bounded entry/file/total-byte limits and final revalidation;
- keep exact path, type, symlink target, regular-file bytes and non-symlink mode checks fail closed.

### 5.4 建立 expected sealed inventory，而不是继续试摘要

Derive the expected inventory from the exact locked `Python_Framework.pkg` Payload, then apply one explicit
Installer/seal transformation contract. A permitted transformation must be path-level and narrowly defined.
For example, if real evidence proves a specific symlink set is materialized from `0775` to `0777`, record the
exact relative paths and exact from/to modes while continuing to require identical path, type and target.

Do not:

- accept multiple complete opaque digest values;
- ignore all symlink modes;
- remove mode from the inventory;
- skip content, path, type or target checks;
- learn and automatically accept the current observed tree;
- change a mismatch into a warning or `continue-on-error`.

If the observed differences include file content, path set, type or symlink target changes, stop and determine
whether the component flatten/install/seal path is altering reviewed bytes. Do not add such differences to an
allowlist without a separate root-cause proof.

Run the same reproduction at least twice from clean/disposable runner state. A final installed-state contract
must be deterministic across fresh runs.

### 5.5 加固 system-root transaction postcondition

Retain the `pending → committed → complete` transaction, identity-bound candidate root and quarantine. Add or
strengthen an independent `if: always()` postcondition for `/Library/Frameworks` so failure evidence proves one
of these exact states:

- previous framework existed: the original identity is restored at the canonical root, quarantine is absent,
  and the failed new candidate identity is absent;
- previous framework did not exist: canonical root and quarantine are both absent;
- seal succeeded: the committed installed identity remains at the canonical root, quarantine is absent, and
  the sealed fingerprint verifies.

If cleanup fails, the final classification must expose the cleanup failure rather than allowing the original
fingerprint error to hide it. Signal cleanup may cover `INT`, `TERM` and `HUP`; do not claim recovery from
`SIGKILL`, host crash or VM disappearance.

### 5.6 保持 smoke 与 formal release 同源安全边界

Any framework-contract change must update both `.github/workflows/packaged-smoke.yml` and
`.github/workflows/desktop-release.yml` consistently, while preserving their different product boundaries.
The policy checker must fail on drift, old digests, bypasses, weak cleanup, multi-digest acceptance,
`continue-on-error`, tag/upload/Secret additions to smoke, or use of the smoke target from formal release.

Do not use an unchecked repository script before the exact-source trust boundary merely to reduce duplicated
workflow text. Keep the reviewed inline loader and pinned verifier/lock identity semantics or replace them only
with an equally strong, explicitly reviewed boundary.

## 6. 最低测试与 mutation 矩阵

Add focused fixtures covering at least:

- exact expected inventory passes;
- exact allowlisted Installer metadata transformation passes;
- non-allowlisted mode change fails;
- symlink target/path/type change fails;
- regular file content/size/mode change fails;
- extra or missing path fails;
- special file, escaping symlink, new broken symlink or cache residue fails;
- expected-inventory input symlink, hardlink, replacement or identity drift fails;
- diagnostics never contain absolute paths or Secret-like values;
- diagnostics truncate safely at their bound;
- smoke/formal workflows cannot drift;
- system-root rollback succeeds for pre-existing and initially absent framework states;
- replacement/identity drift causes fail-closed preservation rather than deletion.

Run the repository's exact final commands, including at least:

```bash
PYTHONDONTWRITEBYTECODE=1 make packaged-smoke-policy-check
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' \
  make python-sidecar-packaging-test
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' \
  backend/.venv/bin/python -m pytest -q \
  tests/backend/test_desktop_release_workflow_policy.py
npm --prefix desktop run test:engineering-smoke
npm --prefix desktop run typecheck
npm --prefix desktop run build
python3 -B tools/check_pre1_work_plan.py
python3 -B -m unittest tools.tests.test_check_pre1_work_plan
python3 -B tools/check_markdown_links.py
python3 -B tools/check_version_sync.py
git diff --check
```

Also parse both workflow YAML files and run `/bin/bash -n` against every modified `run` block. Record exact
versions, command exit codes, pass/skip counts and limitations; do not claim commands that were not executed.

## 7. GitHub candidate 与证据流程

After local focused and aggregate validation:

1. inspect the exact staged diff and stage only reviewed paths;
2. create an implementation commit on this same branch;
3. push without force;
4. wait for fresh exact-head Desktop source CI, Engineering smoke and Containers;
5. treat any changed head as invalidating older workflow evidence;
6. append the new attempt to `2026-08-07-pr21-remediation.md`; never rewrite or erase prior failures;
7. update status/todo/traceability/iteration and the PR body only to the exact facts proven by that head;
8. keep engineering product artifacts empty and do not launch the packaged App in W02-A;
9. after a final exact-head technical candidate is fully green, obtain a new independent read-only acceptance;
10. do not mark ready or merge without later explicit user authorization.

The final technical candidate requires, on the **same exact head**:

- Desktop source CI: `success`;
- Engineering smoke: complete sidecar, renderer, Desktop profile, `.app` directory assembly, inventory and
  bundle audit: `success`;
- Containers: `success`, PR path no publish;
- system-root framework transaction postcondition: `success`;
- no App launch, DMG/ZIP, tag, Release, production credential, Environment, Secret or artifact upload.

Even after that technical candidate is independently accepted:

```text
VAL-PACKAGED-SMOKE-001 = not-run
W02 = in-progress
W10/W11 = locked
Public desktop release = NO-GO
```

Those statuses remain because PR #21 is the no-App-launch W02-A packaging boundary, not the later packaged
runtime smoke, install, signing or release gate.

## 8. 明确禁止事项

- no second PR or replacement branch;
- no force-push, history rewrite or deletion of prior evidence;
- no Ready-for-review or merge in this local iteration without explicit user authorization;
- no tag, Draft Release, public Release, GHCR publication or product artifact upload;
- no GitHub Environment/ruleset/Secret/credential/trust-pin mutation;
- no production signing, notarization or updater path;
- no weakening of formal release audits to make engineering smoke pass;
- no automatic migration/deletion of user data, Application Support, Caches, Logs, Keychain, Docker assets,
  GHCR packages or Releases;
- no broad privileged deletion or cleanup of an identity-unbound framework path;
- no claim that source CI, Containers, mock tests or an old successful head proves the new exact candidate.

## 9. 本地 Codex 完成时的交付

Return an exact-coordinate report containing:

- actual starting handoff commit/tree;
- final implementation head/tree and parent;
- changed paths and commit list;
- local macOS/arm64 environment and every validation result;
- expected and observed framework inventory digests plus sanitized difference classification;
- the explicit Installer/seal transformation contract and why it is minimal;
- rollback/postcondition evidence;
- fresh Source/Engineering/Containers run and job URLs;
- product artifact list, expected to remain `[]`;
- updated append-only evidence coordinates;
- independent acceptance status;
- all still-`not-run` gates and known limitations.

Do not report the work complete merely because local tests pass. Completion requires fresh exact-head GitHub
Actions and a later independent acceptance bound to the same final bytes.
