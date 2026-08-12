# Pre-1.0 权威工作包顺序

本页是 W01–W16 的权威映射。W ID 是稳定工作包标识，不是执行序号；自动化和执行者必须读取
`execution rank`，不得按字符串或数字排序推断依赖。架构依据见
[ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md)，任务细节见
[TODO](todo.md)，验证状态见[追踪矩阵](traceability.md)。

<!-- pre1-work-order: W01,W02,W10,W11,W03,W04,W05,W06,W07,W08,W09,W12,W13,W14,W15,W16 -->
<!-- pre1-w02-requires: VAL-PRE1-SEQUENCE-001,VAL-GOV-001,VAL-CI-COVERAGE-001,independent-acceptance-exact-final-head,accepted-candidate-merged-to-main,resulting-main-source-coverage -->

## 固定顺序

| Execution rank | Work ID | 稳定名称 | 主要任务 | 最低退出门禁 |
| ---: | --- | --- | --- | --- |
| 1 | W01 | 治理与 source baseline | `TODO-PRE1-SEQUENCING-001`、`TODO-GOV-EVIDENCE-001`、`TODO-CI-COVERAGE-001` | `VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001`、`VAL-CI-COVERAGE-001` |
| 2 | W02 | 最小非发行 packaged smoke harness | `TODO-PACKAGED-SMOKE-001` | `VAL-PACKAGED-SMOKE-001` |
| 3 | W10 | 共享代码解耦与 runtime/transport/provider slices | `TODO-LEGACY-DECOUPLE-001`、`TODO-LEGACY-REMOVE-TRANSPORT-001`、`TODO-LEGACY-REMOVE-PROVIDER-001` | `VAL-LEGACY-DECOUPLE-001`、`VAL-LEGACY-TRANSPORT-001`、`VAL-LEGACY-PROVIDER-001` |
| 4 | W11 | deploy/container/GHCR/docs/config/test slices | `TODO-LEGACY-REMOVE-DEPLOY-001`、`TODO-LEGACY-REMOVE-RELEASE-001`、`TODO-LEGACY-REMOVE-DOCS-001` | `VAL-LEGACY-DEPLOY-001`、`VAL-LEGACY-RELEASE-001`、`VAL-LEGACY-DOCS-001` |
| 5 | W03 | 清理后的完整 engineering test package | `TODO-PACK-ENGINEERING-001` | `VAL-ENGINEERING-PACKAGE-001` |
| 6 | W04 | Desktop 数据布局与 backup/restore | `TODO-DATA-LAYOUT-001`、`TODO-DATA-BACKUP-001` | `VAL-DATA-001` |
| 7 | W05 | 模型供应链与原子激活 | `TODO-MODEL-SUPPLY-001` | `VAL-MODEL-001`、`VAL-MODEL-EMBED-001` |
| 8 | W06 | Packaged trust、Python、Dulwich、private UDS | `TODO-PHYS-TRUST-001`、`TODO-PHYS-PY-001`、`TODO-RUNTIME-CANCEL-001` | `VAL-TRUST-001`、`VAL-PY-001`、`VAL-GIT-001`、`VAL-IPC-001`、`VAL-CANCEL-001` |
| 9 | W07 | Native QMD、retrieval 与真实 corpus | `TODO-PHYS-QMD-001`、`TODO-QMD-COMPACT-001`、`TODO-EVAL-CORPUS-001` | `VAL-QMD-001`、`VAL-QMD-EMBED-001`、`VAL-IPC-EMBED-001`、`VAL-QMD-COMPACT-001`、`VAL-EVAL-001` |
| 10 | W08 | 真实 Codex/Cursor provider attempts | `TODO-PHYS-CLI-001` | `VAL-CLI-001` |
| 11 | W09 | Packaged MCP companion/onboarding | `TODO-PHYS-MCP-001`、`TODO-MCP-PAIRING-001` | `VAL-MCP-001`、`VAL-MCP-ONBOARD-001`、`VAL-MCP-PAIRING-001` |
| 12 | W12 | 本地仓库、诊断与完整工程物理矩阵 | `TODO-PHYS-LOCAL-001`、`TODO-LOCAL-HARDEN-001`、`TODO-OPS-DIAGNOSTICS-001` | `VAL-LOCAL-SOURCE-003`、`VAL-LOCAL-HARDEN-001`、`VAL-DIAGNOSTICS-001` |
| 13 | W13 | Final cleaned engineering checkpoint：Electron cutover 与 legacy absence | `TODO-ELECTRON-CUTOVER-001`、`TODO-LEGACY-ABSENCE-001` | `VAL-ELECTRON-CUTOVER-001`、`VAL-LEGACY-ABSENCE-001` |
| 14 | W14 | GitHub production control plane | `TODO-REL-GOV-001` | `VAL-SECRET-001` settings subgate |
| 15 | W15 | Production credentials/trust pins、formal RC 与唯一 Draft | `TODO-REL-KEYS-001`、`TODO-PACK-ARM64-001`、`TODO-REL-DRAFT-001` | `VAL-SECRET-001` credential subgate、`VAL-RELEASE-CONTINUITY-001` tag/diff subgate、`VAL-PACK-001`、`VAL-RELEASE-001` candidate subgate |
| 16 | W16 | 同一 Draft 的物理审查、promotion、公开 Release 与真实更新 | `TODO-REL-PROMOTE-001`、`TODO-UPDATE-NMINUS1-001` | exact Draft 上 `VAL-ELECTRON-CUTOVER-001`、`VAL-LEGACY-ABSENCE-001`、`VAL-RELEASE-CONTINUITY-001`，以及 `VAL-INSTALL-001`、`VAL-RELEASE-001`、`VAL-UPDATE-001` |

## 不可跨越的边界

- W02 只在 W01 的 `VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001`、`VAL-CI-COVERAGE-001` 对 exact
  final PR candidate 的 PR/source technical 结果全部为 `pass`、该 exact head 经 independent
  acceptance、被验收 candidate 合入 canonical `main`，且 resulting exact main commit 的
  `source-coverage` job 成功后开始。PR head、synthetic merge SHA 与 resulting main SHA 不得静默
  互换；仓库内状态不能自我提升 canonical activation。它是所有 W10/W11 destructive slice 的
  前置，但只证明最小 packaged feedback loop。
  当前这些 entry 条件已由 accepted final
  `36885e04df09c4789d8ec3c9dc5c5e78a381a634`、resulting
  `main@1786255b55dd1a78659ed92235893876175a0722` 与 run `30986208251` 闭环。W02 Draft PR #21
  exact `08137c7…` 的 [static assembly/bundle audit](evidence/W02/2026-08-06-08137c7-assembly.md)
  是历史技术 `pass`；后来 reviewed `8c5fd232…` / tree `785f4656…` 因 scratch lifecycle、Git
  provenance 与 cleanup fail-closed blocker 被独立判定为 `NO-GO`，见
  [append-only remediation record](evidence/W02/2026-08-07-pr21-remediation.md)。第一次 remediation
  exact `9f7d5d…` / tree `ea8e62…` 的 assembly/source technical execution `fail`，container 仅
  no-publish success；该 attempt 已 `superseded`、independent `pending`，没有改变旧 head 的 latest
  independent `NO-GO`。第二次 exact `9ecf0e…` / tree `ee8271…` 的 assembly/source 也 technical
  `fail`（installed-toolchain file 与 Python real-venv mode/ownership），container 仍仅 no-publish
  success；该 attempt 同样已 `superseded`、independent `pending`。第三次 exact `2665ec…` / tree
  `c3cd17…` 的 source success，但 assembly 因 Darwin fd-backed uv cwd technical `fail`；container
  API/MCP success、Web QEMU Node/npm stall 后 cancelled，且仍未 publish。第三次 attempt 也已
  `superseded`、independent `pending`。第四次 exact `c2be665f…` / tree `f90b527b…` 的 source 与
  Containers success；Engineering inner build 与 cleanup gate technical `fail`，exact tree、平台和
  当时实现把高置信根因分别归到 APFS/Darwin directory-link inventory 与 Darwin sealed-source
  cleanup ordering（raw log 未打印 inner stage、`st_nlink` 或 cleanup errno）。该 attempt 也已
  `superseded`、independent `pending`。第五次 exact
  `c04fe9f…` / parent `c2be665f…` / tree `2f8b3ace…` 的 Desktop source `31454826261`
  因 Python fixture `EACCES` before product cleanup 失败，W01 evidence downstream fail closed；
  Engineering `31454826263` / job `93666344718` 在 Python framework installation 失败但
  cleanup success，launcher self-update collision 只是高置信代码/时序归因，不是 raw log
  直接证明；Containers `31454826243` success/no publish。第五次已 technical `fail` /
  `superseded`、independent `pending`。第六次 exact
  `cc6ade1…` / parent `c04fe9f…` / tree `911e91d…` 的 Desktop source `31460588210`
  success；Engineering `31460588223` / job `93683139742` 在 policy `67/67` 与 exact-Git `1/1`
  通过后以 `Reviewed Python installer launcher is unsafe` 失败，cleanup success、later stages
  skipped、artifacts `[]`；Containers `31460588212` success/no publish。第六次已 technical `fail` /
  `superseded`、independent `pending`。第七次 exact `aaf3f51…` / parent `cc6ade1…` / tree
  `60c2c6c…` 的 Desktop source `31559498106` success；Engineering `31559498116` / job
  `93998717925` 因 manifest actual uppercase/single-space 与 workflow lowercase/double-space literal
  不符而 primary fail，cleanup 因 source 未绑定 secondary fail，later stages skipped、artifacts
  `[]`；Containers `31559498070` success/no publish。第七次已 technical `fail` / `superseded`、
  independent `pending`。第八次 exact remediation technical candidate `not-run`（无 committed exact
  head/tree 或 fresh exact-head Actions）。它继承第七候选不使用
  `actions/setup-python` / 原 full pkg；exact outer pkg 验签后只以唯一 17-byte no-op 重打并安装
  `Python_Framework.pkg`，隔离旧 root/确认 target absent，再完成 non-symlink seal、大小写无关
  cache cleanup 与 O_NOFOLLOW-held verifier/lock bytes 的 pre-Python Node
  core/fresh-exclusion verification；之后才精确复验/清理
  quarantine，首次 framework Python 位于该 cleanup 后；运行时 install-reviewed 仅验证
  distribution/binding，不安装或 `sudo`；同时把 manifest 真实整行固定为 `grep -Fxc` + count one，
  cleanup 分成 source-unbound zero-residue 与 source-bound strict source/repo closure。七次失败均
  未启动 assembled App，
  packaged App launch/runtime 与
  `VAL-PACKAGED-SMOKE-001` 仍为 `not-run`，所以 W10/W11 尚未解锁。
- W10/W11 每个 slice 都在 exact before/after bytes 上独立运行 focused replacement（或受限
  pure-legacy unsupported disposition）、source regression、packaged smoke、absence 与
  protected-path presence；不同 slice 不能共享一个
  虚构的聚合 pass。
- W03 必须从 W10/W11 清理完成后的 tree 构建，不携带已删除的 legacy runtime。
- W04–W12 使用 engineering package，不读取生产凭据、不创建 tag/Draft/Release。
- W13 必须从最终 cleaned commit 重建，并在同一 package digest 上同时完成 cutover 与
  aggregate absence；W15 continuity verifier/allowlist 也必须在该 checkpoint 前冻结。后续修改
  verifier 或其他非 allowlisted source 必须建立新 W13 checkpoint 并重跑两门禁。
- W14、W15、W16 严格位于 W13 之后。W15 只允许 W13 checkpoint → formal tag 的 allowlisted
  public pins/release metadata/version diff，并在 tag 重跑 source/absence；W16 必须在 exact Draft
  digest 上重新运行完整 cutover/absence。W02/W03/W13 的 engineering evidence 永远不能提升或
  替代正式 secret、pack、install、release、update 或 continuity gate。

## Slice 通用模板

每个 W10/W11 slice 必须在 PR/iteration 中填写：

1. exact owner、caller inventory 与 `remove` / `retain` / `split`；
2. baseline commit、`VAL-PACKAGED-SMOKE-001` evidence 和回退点；
3. 对 shared/必需 Electron capability，记录 affected replacement/focused tests；对纯 legacy-only
   unsupported capability，记录受限 `no-replacement / unsupported` disposition 与无 Electron
   caller 证明；两类都运行 aggregate source tests；
4. after-slice commit、fresh package digest、重跑 smoke 与 slice absence；
5. protected Electron paths/resources 的 presence 断言；
6. 用户 data、volume、container/image、Application Support、Keychain、历史 evidence、远端 GHCR package、
   GitHub settings/tag/Draft/Release 均未修改的声明。

## 不在主链中的未来工作

`TODO-UPDATE-APPLY-001`、`TODO-WIKI-INCREMENTAL-001` 和 `TODO-REMOTE-WORKER-001` 保持 future。
Automatic apply 在新增或 superseding ADR Accepted 前不得成为 W16 的交付；这些任务也不得
倒置上表的 release safety chain。
