# 验证证据记录规范

本目录定义 Local Context Forge 的验证证据格式。后续可以按
`<VAL-ID>/<YYYY-MM-DD>-<short-commit>.md` 或外部受控 artifact 链接增加记录。当前目录只存
规范，不存私有源码、用户数据、证书、密钥、模型或大型构建产物。

## 当前记录

| Gate | Source commit | 结果 | 记录 |
| --- | --- | --- | --- |
| `VAL-DOC-HANDOFF-001` | `625db7647d47fb6ff8f23c3136c4f45ded80384f` | `pass`（文档 source checkpoint） | [2026-07-31-625db76](VAL-DOC-HANDOFF-001/2026-07-31-625db76.md) |
| `VAL-LEGACY-SCOPE-001` | `64ec3c232d08f1e843d81dc7c4972dc5ebf96c9b` | `pass`（planning/documentation scope） | [2026-07-31-64ec3c2](VAL-LEGACY-SCOPE-001/2026-07-31-64ec3c2.md) |
| W01 旧 candidate | final `2b7629468c711d0db5107f7001aa90c0271079ae` / tree `ad1b76febd1adcaf1ada96ed7dd43fbe1e5a3adf` | technical `pass`；independent `fail`；activation `not-eligible` | [schema v2 history](W01/2026-08-04.json)；[Actions 30929070329](https://github.com/fredgnr/local-context-forge/actions/runs/30929070329)；旧 artifact `8900365901` |
| W01 remediation candidate | Checkpoint A `f4074a31bde50710bb40e1e8509dfdcd232835c4` / tree `f059ad8bd3cfc6accac707745d5d8727bfb532bd` | PR/source `pass`；independent `pending`；canonical-main `not-run`；activation `blocked` | [schema v2 lifecycle record](W01/2026-08-04.json)；[Actions 30980342634](https://github.com/fredgnr/local-context-forge/actions/runs/30980342634)；payload `8919891304`；provenance `8919891597`；[closed schema](W01/schema-v2.json) |

旧 W01 technical execution 是真实历史，但独立 NO-GO 使其不具 canonical eligibility。修复记录
必须与 exact final head 上的新 payload/provenance 一起读取；仓库记录不能自行声明 independent
acceptance 或 canonical activation。以上记录均不代表 packaged、physical、GitHub settings、
legacy absence 或 release gate 已通过。

## 1. 证据原则

一条可支撑 `pass` 的记录必须同时回答：

- 测了哪一组精确 bytes；
- 在什么最低环境运行；
- 运行了什么；
- 预期与实际是什么；
- 产物和输入如何绑定；
- 谁执行、谁独立复核；
- 失败路径和回滚是否验证；
- 哪些敏感信息已删除；
- 哪些内容仍未运行。

以下都不能单独支撑比自身层级更高的 packaged/physical/formal `pass`：

- “当前工作树”；
- 单元 mock/fake store；
- source mode；
- ad-hoc DMG（只能在显式 W02/W03 engineering gate 的定义范围内作为证据）；
- 同版本重装；
- UI 截图外观；
- CI 成功但没有真实 secret/签名/模型/CLI；
- 省略 skip、failure injection 或 rollback。

## 2. 文件命名

推荐：

```text
docs/development/evidence/
└── VAL-EXAMPLE-001/
    └── 2026-08-01-abcdef1.md
```

若证据包含大型日志、截图或 Release assets：

- 仓库只提交小型脱敏摘要；
- 记录受控 artifact/Actions/Release URL；
- 记录每个 artifact SHA-256；
- 不依赖短期链接作为唯一证据；
- 不把 Draft asset 当 immutable storage。

## 3. 最小模板

```yaml
gate_id: VAL-EXAMPLE-001
status: pass | fail | not-run
recorded_at: 2026-08-01T12:00:00Z

repository: fredgnr/local-context-forge
branch: main
source_commit: <40-hex>
tag: <vX.Y.Z-or-null>
workflow_file_commit: <40-hex-or-null>
actions_run_url: <url-or-null>
release_id: <integer-or-null>

product_version: <version>
database_schema: <integer>
architecture: arm64
machine_model: <redacted-model>
macos_build: <build>
runtime_versions:
  python: <version-or-null>
  node: <version-or-null>
  qmd: <version-or-null>

candidate_manifest_sha256: <64-hex-or-null>
credential_generation_id: <32-hex-or-null>
certificate_sha256: <64-hex-or-null>
update_public_key_sha256: <64-hex-or-null>
asset_sha256s: {}

executor: <role-or-handle>
independent_reviewer: <role-or-handle>
started_at: <rfc3339>
completed_at: <rfc3339>

preconditions: []
commands: []
expected_results: []
actual_results: []
failure_injections: []
data_before_counts: {}
data_after_counts: {}
rollback_result: <pass-fail-not-run>

sanitized_artifacts: []
known_limitations: []
redactions_confirmed: []
not_run_reason: <required-when-not-run>
```

Markdown 记录可在 YAML 后补：

```markdown
## Summary

## Environment

## Procedure

## Expected versus actual

## Failure injection

## Data and rollback

## Artifact verification

## Redaction review

## Reviewer conclusion
```

## 4. Source 证据

至少记录：

- exact commit；
- clean/dirty 状态；
- OS/architecture；
- Python/Node/npm/uv 版本；
- lockfile digest 或 checkout；
- exact command；
- pass/fail/skip count；
- Actions run/job URL；
- 所有未覆盖组件。

### 4.1 历史 record 与当前 exact head 分离

`W01/schema-v2.json` 与 `tools/check_w01_evidence.py` 验证固定历史 source/tree/run/artifact/digest、
旧拒绝状态、remediation checkpoint 和 lifecycle cross-field consistency。historical checker：

- 不读取当前 Git history；
- 不要求旧 PR/checkpoint commit 是当前 `HEAD` 的 ancestor；
- 不动态计算历史 checkpoint→任意未来 `HEAD` 的 path diff；
- 不用 future allowlist 限制 W02/W10/W11 或 main movement；
- 不根据仓库内的 `pass` 提升 independent acceptance 或 canonical activation。

因此 future product descendant、merge commit、squash-equivalent、rebase-equivalent 与 merge 前
main movement 都不会破坏合法历史证据。当前 bytes 的 source correctness 始终由当前 exact-head
checkout、required jobs 和 runtime artifact 证明。

### 4.2 Payload + provenance，不递归自哈希

提交不能在自身 bytes 中写入自己的 SHA 或尚未产生的 Actions run。runtime payload 同样不能
嵌入自身 ZIP digest/artifact ID。W01 schema v2 使用两个 artifact：

1. renderer 生成 source payload 并先上传；
2. upload step 返回 payload artifact ID/URL/archive SHA-256；
3. provenance renderer 计算 payload JSON SHA-256，并绑定 payload source/tree/run、artifact
   ID/name/archive digest/inner digest；
4. provenance 作为第二个 artifact 上传，但不嵌入自己的 ID 或 digest；
5. 后续 committed closeout record 可以记录已经存在的 checkpoint payload/provenance 两组坐标。

closeout 中的 canonical record digest 用来捕获局部字段改写；权威锚点仍是 GitHub Actions
服务中已存在的 exact run、payload/provenance artifact ID 与两层完整 digest，以及独立验收所钉住
的 exact PR head。若后续提交协调替换全部坐标并重算 record digest，那是一个新的 candidate，
必须重新运行 exact-head CI 并重新接受独立验收，不能继承旧 candidate 的 technical 或 acceptance
结论。仓库内容本身始终不能把 `independent_acceptance` 从 `pending` 提升为 `pass`。

PR 与 non-main branch payload 使用 `pull-request-candidate` / `branch-candidate`，只输出 technical
candidate results，canonical activation 必须为 `blocked`。只有 `push` to `refs/heads/main` 可输出
`canonical-main-source` results；workflow 无法观察 ChatGPT independent acceptance，因此即使 main
source 成功，activation 仍是 `requires-external-conditions`，除非存在可验证的外部 acceptance
reference。

任一 required job 为 failed/missing/skipped/cancelled 时 summary 必须失败；payload/provenance 仍
上传供诊断，不能由 summary job 洗绿。W02 必须同时等待 exact final head 独立验收、被验收
candidate 合入 canonical `main` 和 resulting exact main commit 的成功 source run；PR head、
synthetic merge SHA 与 resulting main SHA 不得静默视为相同 bytes。

示例结论：

> Desktop source checks passed on commit `<sha>`. This does not run bundled
> Python/QMD, signing, Gatekeeper, a real model, a logged-in CLI, or update
> promotion; those gates remain `not-run`.

## 5. Engineering package 与 slice 证据

### W02 packaged smoke

至少记录 `distribution_class=engineering-smoke`、`publishable=false`、exact commit、App/package
digest、architecture、有限 inventory、launch、renderer/preload、private UDS health/domain request、
quit/no orphan、process/socket observation、exercised path 的 system Python/Node/Git PATH trap、
updater unavailable/no-network。`tag`、`release_id`、
credential generation 和 production pin 必须为 null/absent。

### W10/W11 slice

每个 slice 单独记录：

- baseline commit/package digest 与 W02 smoke；
- owner/caller inventory、`remove` / `retain` / `split`，以及 affected replacement；纯 legacy-only
  capability 使用受限 `no-replacement / unsupported` 时还要记录无 Electron caller/data/external
  side effect 的证明；
- exact changed paths、focused/aggregate source results；
- after-slice commit 与 fresh package digest、相同 smoke；
- slice absence 与 protected-path presence；
- 用户 data/volume/container/image/Application Support/Keychain、历史 evidence、远端 GHCR package、GitHub
  settings/tag/Draft/Release 未修改；
- 独立回退点。

### W03 engineering test package

记录 `distribution_class=engineering-test`、`publishable=false`、cleaned commit/digest、完整
renderer/Python/QMD/companion inventory、SBOM/notices、测试入口和 production trust absence。
该证据只支撑 `VAL-ENGINEERING-PACKAGE-001` 与后续 W04–W12，不支撑 formal gate。

## 6. GitHub settings 证据

本类证据属于 W14 及以后。W02/W03 和 legacy slice 不应包含 GitHub settings mutation。

应包含：

- repository visibility/name；
- Environment name、reviewer、prevent self review、deployment pattern；
- UI admin-bypass-disabled 截图；
- Environment secret **名称集合**，不含 value；
- ruleset target、include/exclude、rule types、bypass actor；
- Immutable Releases 状态；
- API 获取时间和复核人；
- bootstrap verify 结果。

禁止：

- secret value；
- credential bundle；
- PAT/GitHub token；
- private key/P12/password；
- 完整 auth header 或未脱敏 API dump。

源码 policy test 只能记作 source sub-gate。真实设置必须从 canonical repository 读取。

## 7. Release 候选证据

本节只适用于 W15/W16 formal candidate。Engineering artifact 永远不能复用为 Draft/Release
evidence。

记录：

- tag、peeled commit、main ancestry；
- W13 checkpoint commit/package digest、formal tag commit，以及二者之间只含 production public
  pins/release metadata/version 的 reviewed allowlisted diff；
- formal tag 上重跑的 source/aggregate absence 结果；
- Actions run 和两个 Environment approval；
- fixed Release ID 和 Draft/published pre-state；
- candidate `release-manifest.json` SHA-256；
- 完整 asset name/size/digest；
- credential generation、certificate/public key digest；
- DMG/App/nested Mach-O architecture/signing identity；
- SBOM/notices/runtime manifest；
- release notes 的 self-signed/not notarized/not hardened/automatic apply disabled；
- Draft 未被人工修改的复核；
- exact Draft digest 上重新运行的完整 `VAL-ELECTRON-CUTOVER-001`、
  `VAL-LEGACY-ABSENCE-001` 结果，以及 `VAL-RELEASE-CONTINUITY-001` 结论；不得引用 W13
  engineering package 结果代替。

Promotion 记录还需要：

- `workflow_dispatch --ref main`；
- verifier 的 `GITHUB_SHA` 与 fresh main head；
- detached tag worktree/fresh peel；
- `PATCH` 前 fresh `origin/main` comparison；
- fixed ID PATCH；
- `gh release verify`；
- `immutable=true`；
- post-publish 完整资产集合。

缺少 checkpoint/tag allowlisted diff、tag source/absence 或 exact Draft cutover/absence 中任一项，
continuity gate 必须保持 `not-run`/`fail`，不得 promotion。

若 pre-state 已 published 或资产漂移，状态应为 `fail`/安全事件，不得通过重跑改成 `pass`。

## 8. 物理 Mac 证据

最低记录：

- Mac model/architecture、macOS build；
- clean test user 的前置条件；
- 系统外部 runtime absence；
- DMG digest、App path、Gatekeeper 路径；
- Python/QMD/MCP/CLI/local-source/update 的实际步骤；
- crash、cancel、offline、ENOSPC、tamper、move/delete 等故障注入；
- data/page/job/source-ref/revision counts；
- backup/restore/rollback；
- App quit 后 child/MCP 行为；
- 独立 reviewer。

脱敏：

- 用户名用 `<USER>`；
- home 用 `<HOME>`；
- private repo 用 `<PRIVATE_REPO>`；
- 不保存源文件、prompt/result、CLI auth、完整 stderr；
- 截图裁掉菜单栏账号、路径、通知和其他应用；
- 日志经过自动和人工二次检查。

## 8. `not-run`

`not-run` 是诚实状态，不是失败。必须给出：

- 缺少的环境/权限/资产；
- 为什么 source/mock 不足；
- 解除条件；
- owning component；
- 对发布的影响。

示例：

```yaml
gate_id: VAL-QMD-EMBED-001
status: not-run
not_run_reason: >-
  No protected arm64 candidate and no physical M4 model download run exist.
  Source fake-store tests cannot verify native better-sqlite3 or model bytes.
```

## 9. Evidence review checklist

- [ ] SHA/URL 指向精确 commit/run/asset；
- [ ] 测试环境满足 gate 的最低要求；
- [ ] command 可复制；
- [ ] pass/fail/skip 完整；
- [ ] expected/actual 分开；
- [ ] failure injection 已运行；
- [ ] rollback 已运行；
- [ ] counts/digests 可复核；
- [ ] reviewer 独立；
- [ ] secrets/private source/path 已脱敏；
- [ ] `not-run` 未被 source 结果覆盖；
- [ ] iteration、traceability、status 已同步。
