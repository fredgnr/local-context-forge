# ITER-0002/R13：Pre-1.0 增量式 retirement 治理

- 状态：`in-progress`（继承 ITER-0002；待最终 PR head 证据）
- 日期：2026-08-03；W01 closure 续作 2026-08-04
- 上游基线：`main@3eff97d97b2de4484d568bab5ac96d63830c79ee`
- 当前分支：`agent/w01-governance-source-ci`
- 范围：决策、治理、计划、追踪关系与治理校验；不删除 runtime，不实现 package，不修改
  GitHub 控制面，不生成凭据，不创建 tag/Draft/Release
- 关联决策：[ADR-0016](../../adr/0016-pre1-incremental-retirement-engineering-package.md)
- 关联计划：[W01–W16 work plan](../work-plan.md)
- 关联验证：VAL-PRE1-SEQUENCE-001

## 目标

接受并记录新的 pre-1.0 顺序：先建立最小 packaged smoke，再把 W10/W11 以前置的独立 slice
清理 legacy，随后从 cleaned tree 完成完整 engineering test package；数据、模型、runtime、
CLI/MCP/local-source 与物理矩阵完成后，才运行 final cutover/absence；production GitHub
controls、credentials、trust pins 和 formal Release 最后处理。

## 任务

- [x] R13-01 核对 checkout、branch、HEAD、`origin/main`、ahead/behind、工作区、open PR、
  tags、Releases、最近 Actions 和 container workflow。
- [x] R13-02 审计 ADR-0015、TODO、traceability、roadmap、iteration、release runbook、skills
  和 policy tests 中的旧全局删除前置。
- [x] R13-03 接受 ADR-0016，只部分取代 ADR-0015 的 deletion sequencing，保留 Electron-only、
  数据安全、历史证据和 final fail-closed 门禁。
- [x] R13-04 首次落盘 W01–W16 稳定映射，以显式 execution rank 前置 W10/W11，不重编号。
- [x] R13-05 新增最小 smoke、slice 与 engineering package 的 REQ/TODO/VAL，并同步权威文档。
- [ ] R13-06 在最终 PR head 运行 commit-bound links/version/plan/diff 与 CI 验证并登记 evidence。

`[x]` 只表示 governance/source 文档已在本工作树编写，不表示 runtime、packaged、physical、
GitHub settings 或 Release gate 已运行。R13-06 完成前，本记录保持 `in-progress`。

## 实时基线

2026-08-04 W01 closure 开始时：

- 本地与远端 `main` 均为 `3eff97d97b2de4484d568bab5ac96d63830c79ee`，工作区干净；
- PR #19 final head `a31f17c367e0ff3d007d2334c37b403615173083` 已合入为 `3eff97d`，两者
  tree 都是 `21fe2cbe46d42bf351d2b0c84019ee63959081b7`；
- PR #19 exact branch push run `30815933733` 与 canonical main push run `30816291252` 的既有
  Python/Web/Desktop/macOS IPC jobs success，但都未执行 W01 QMD/coverage contract；
- 仓库仍有历史 `agent/*` / Dependabot branches，但没有 open PR 或发现并行修改同一 ADR/TODO/
  iteration 的活动分支；
- 最近 main 的 Desktop source CI run `30630283893` 与 container run `30630283873` 成功；
- `.github/workflows/container-images.yml`、`desktop-ci.yml`、`desktop-release.yml` 均仍存在；
- GitHub 报告 `main` protected，但这不足以证明双 Environment、三组 exact ruleset 或 Immutable
  Releases 满足 production contract；
- 编辑前 ADR 最大 `0015`、父 iteration 最大 `0007`、追加记录最大 `R12`，仓库没有 W ID；
  TODO 36 个、VAL catalog 46 个且各自 unique。R13 新增 ADR-0016、ITER-0008、W01–W16、
  4 个 TODO 与 10 个 VAL（含 formal-candidate continuity），均经 collision/set check；
- `macos-signing` / `macos-release` production settings、正式 credentials/trust pins、正式 DMG、
  clean M4 和真实 release/update evidence 仍未完成。

这些实时坐标只说明规划基线，不把 Actions success 提升为 packaged/physical/release pass。

## 验证日志

| 验证 | 当前结果 | 最低环境 | 说明 |
| --- | --- | --- | --- |
| W01 machine contract authoring | gate 仍 `not-run` | 当前工作树 | coverage manifest、反向 checker、QMD lifecycle/network/model trap、exact PR-head checkout、fixed base→head diff 与 runtime evidence renderer 已编写；checkpoint 尚未提交/运行 |
| `VAL-PRE1-SEQUENCE-001` authoring check | gate 仍 `not-run`；local observation `pass` | 当前工作树 | exact plan checker 与负向 fixtures、links、version 通过；裸 `git diff --check` 不再计入 final evidence，必须比较 `3eff97d…`→tested head |
| `VAL-PRE1-SEQUENCE-001` final head | `not-run` | clean checkout / final PR head | 必须绑定 commit 与 CI |
| `VAL-PACKAGED-SMOKE-001` | `not-run` | macOS arm64 packaged App | 本 Work 不实现 harness |
| 六个 legacy slice gate | `not-run` | slice exact before/after package | 本 Work 不删除 runtime |
| `VAL-ENGINEERING-PACKAGE-001` | `not-run` | cleaned-tree non-release package | 本 Work 不实现工程包 |
| `VAL-ELECTRON-CUTOVER-001` / `VAL-LEGACY-ABSENCE-001` | `not-run` | final cleaned bytes | 最终聚合门禁保留 |
| `VAL-RELEASE-CONTINUITY-001` | `not-run` | W13 checkpoint、formal tag diff 与 exact Draft | 本 Work 不创建正式候选 |
| `VAL-SECRET/PACK/INSTALL/RELEASE/UPDATE-001` | `not-run` | production controls/formal candidate/physical Mac | 全部后置且 fail closed |

## 风险与回退点

| 风险 | 缓解 |
| --- | --- |
| 把 W 号误当执行顺序 | work plan 保存显式 rank，并由治理 checker 验证固定序列 |
| 把最小 smoke 冒充完整工程包 | 使用独立 TODO/VAL 与 artifact class；列出明确 non-goals |
| 单个 slice 误删 shared Electron code | caller inventory、split-first、before/after package、presence gate |
| no-replacement 被滥用于必需产品能力 | 仅允许 pure legacy-only/unsupported 且无 Electron caller/data/external effect；其他情况 fail closed |
| 提前使用 production trust 或 GitHub controls | W14–W16 明确依赖 W13；engineering artifact 禁止 tag/upload/promotion |
| W15 production 变更使 W13 bytes 证据失效 | allowlisted checkpoint→tag diff、tag absence 与 exact Draft cutover/absence 独立门禁 |
| 文档 pass 冒充实现 pass | 所有 runtime/packaged/physical/control-plane gate 保持 `not-run` |

回退本治理变更只需普通 Git revert；不得因此修改用户数据、远端 package、GitHub settings、
credential、tag 或 Release。
