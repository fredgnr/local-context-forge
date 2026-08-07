# 项目状态快照

本页是 Local Context Forge 当前状态的权威入口。用户指南、路线图、迭代记录和 Release
说明应链接本页，不应各自推断“已经可发布”。架构与实现细节分别见
[系统设计](../17-system-design.md)和[开发者手册](contributor-handbook.md)；剩余工作见
[TODO](todo.md)。

## 快照坐标

| 字段 | 值 |
| --- | --- |
| 截止日期 | 2026-08-07 |
| canonical repository | `fredgnr/local-context-forge` |
| 本轮实施基线 | `main@1786255b55dd1a78659ed92235893876175a0722` |
| 基线来源 | PR #20 accepted final `36885e04df09c4789d8ec3c9dc5c5e78a381a634` 合入；accepted/resulting-main tree 均为 `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64` |
| 产品版本 | `0.3.0-alpha.1` |
| 数据库 schema | `5` |
| 活动父迭代 | [ITER-0002](iterations/0002-bundled-runtimes.md) |
| 活动实施记录 | [ITER-0008](iterations/0008-incremental-retirement-engineering-package.md) / W02 |
| W02 historical static assembly checkpoint | Draft PR #21 `08137c7bce5469350b861cef7960e4a0530151bf` / tree `d7814ac96136cea33fb7069d9538a4aad8dffa38`；assembly run `31024794972` / job `92370351806`；technical history only |
| W02 current reviewed candidate | Draft PR #21 `8c5fd23206b671b768fd21d253bf292642f93a51` / tree `785f4656de8a7233b6dd632fe4815976d33468fb`；independent `NO-GO`；same PR remediation technical candidate `not-run` |
| 当前结论 | **W02 in-progress：PR #21 independent `NO-GO`；remediation `not-run`；packaged launch/runtime `not-run`；W10/W11 locked；public release NO-GO** |

PR #20 的旧 final candidate 已被独立验收拒绝；remediation exact final
`36885e04df09c4789d8ec3c9dc5c5e78a381a634` 已通过 PR/source 与独立验收并合入 canonical
`main@1786255b55dd1a78659ed92235893876175a0722`。resulting-main run `30986208251`
attempt 1 的五个 source jobs 均成功，W01 退出条件已闭环。该闭环只授权开始 W02，不表示：

- 存在可推荐给普通用户的 DMG；
- 打包应用已经在干净 M4 用户上运行；
- GitHub Environments、rulesets、Immutable Releases 已按生产要求配置；
- 自签名证书和更新密钥已经 provision；
- 真实 Codex、QMD 模型、本地外置卷、MCP 或跨版本更新门禁已经通过。

## 可复现的当前源码证据

PR #19 final head `a31f17c367e0ff3d007d2334c37b403615173083` 的 branch push run
[`30815933733`](https://github.com/fredgnr/local-context-forge/actions/runs/30815933733) 与 canonical
merge `3eff97d97b2de4484d568bab5ac96d63830c79ee` 的 main push run
[`30816291252`](https://github.com/fredgnr/local-context-forge/actions/runs/30816291252) 均有既有
Python/Web/Desktop/macOS IPC success。它们早于 W01 QMD/coverage contract，不能关闭 W01。
W01 旧机械 checkpoint `8573f608df589bc2ef9e05f0c75d84887464c825` 的
[PR #20 run 30927840380](https://github.com/fredgnr/local-context-forge/actions/runs/30927840380)
在 exact checkout 上完成新的五 job aggregate：Python 323、Host Runner 8、demo SDK 3、Web
51、Desktop 252、macOS IPC 49、governance 42，QMD 10 pass / 1 allowlisted native skip；
network trap active；模型文件/缓存增量为 0 只覆盖 isolated `HOME`、三个 XDG 根和 isolated
`TMPDIR`，未扫描 repository worktree 或 global tmp。旧 final candidate
`2b7629468c711d0db5107f7001aa90c0271079ae` / tree `ad1b76febd1adcaf1ada96ed7dd43fbe1e5a3adf`
的 [run 30929070329](https://github.com/fredgnr/local-context-forge/actions/runs/30929070329) 也确实是
technical source `pass`，但独立验收为 `fail`、canonical activation 为 `not-eligible`。旧 run、
artifact 与 NO-GO 作为历史保留，不能解锁 W02。

修复后的 schema v2 只验证固定历史坐标和字段一致性，不再要求旧 checkpoint 是当前 `HEAD`
的 ancestor，也不再动态限制 checkpoint→未来 `HEAD` 的路径。当前 bytes 的正确性由每个
exact-head `Desktop source CI` payload 与独立 provenance artifact 证明；PR/branch artifact 的
canonical activation 固定为 `blocked`，canonical-main source result 与 independent acceptance
分开记录。

修复 Checkpoint A `f4074a31bde50710bb40e1e8509dfdcd232835c4` / tree
`f059ad8bd3cfc6accac707745d5d8727bfb532bd` 的 [run 30980342634](https://github.com/fredgnr/local-context-forge/actions/runs/30980342634)
五个 jobs 全部成功。payload artifact `8919891304` 的 archive / inner SHA-256 分别为
`2d6801946e82b4acbd6621e722049c1a42f3e7578a8c959e19c3762259114d0a` /
`f71615cc0112ee228dd3c17c2d77a3c07e14ad3e2212f08ef3c92b95e48313c3`；provenance artifact
`8919891597` 的 archive / inner SHA-256 分别为
`f65ce338d7c8bdbb1a8b5e25d60b82e139f81ebd4359562b26e498e605ff46c9` /
`894567927446763c95b8a67bb92e8897a4ff3cc1dcdccfc590fb69a070b39cb0`。该 PR artifact 只记录
technical `pass`，independent acceptance 在该历史记录时刻仍为 `pending`，canonical activation
仍为 `blocked`。该 JSON 保持不可变，不承担后续状态。

后续外部闭环由 [W02 entry record](evidence/W02/2026-08-05-entry.md) 追加记录：accepted final
`36885e04df09c4789d8ec3c9dc5c5e78a381a634` 与 resulting main
`1786255b55dd1a78659ed92235893876175a0722` 的 tree 均为
`1b9f3a34847fd3acc8b7f3a31ff19332d5328b64`；main push run
[`30986208251`](https://github.com/fredgnr/local-context-forge/actions/runs/30986208251) 的 Python、
Web、Desktop、macOS arm64 IPC 与 exact-head source-coverage jobs 均为 `success`。当前 W01 三个
source/governance gate、independent acceptance、canonical merge、resulting-main source 与
activation 均为 `pass`。

W02 Draft PR #21 historical exact head `08137c7bce5469350b861cef7960e4a0530151bf` 的
[Desktop source CI `31024794734`](https://github.com/fredgnr/local-context-forge/actions/runs/31024794734)
与 [engineering-smoke assembly run `31024794972`](https://github.com/fredgnr/local-context-forge/actions/runs/31024794972)
均为技术 `success`。static `.app` directory assembly 与 bundle audit 当时为技术 `pass`，inventory 为
`879` entries / `78` native files，SHA-256 为
`7fcdb699ad367e7c7da28a074694c6fe8a0a67b54829173894d311de4f6ffe5c`；见
[canonical assembly record](evidence/W02/2026-08-06-08137c7-assembly.md)。该 job 的 pre-pack
frozen sidecar staging smoke 已成功，但 assembled App 未启动、sidecar 未从 bundle 启动，remote
artifacts empty，因此这不是 packaged runtime gate，也不是 current remediation 的 evidence。

最终独立验收随后绑定 PR #21 reviewed head
`8c5fd23206b671b768fd21d253bf292642f93a51` / tree
`785f4656de8a7233b6dd632fe4815976d33468fb` 并给出 `NO-GO`：旧 build scratch 没有 held
dirfd/inode capability，Git provenance 没有绑定 exact tree/committed source bytes，publish、rollback、
failure evidence 与 cleanup 仍可受 pathname rename/recreate/ABA 影响。旧 exact-head assembly run
`31026905444` / job `92377586784`、source run `31026907916`、container run `31026906777` 只作为
失败候选的历史技术结果保存。当前 [append-only remediation record](evidence/W02/2026-08-07-pr21-remediation.md)
固定 `CTX-PR21-NOGO-CURRENT`；新的 exact head 和 fresh Actions 尚不存在，因此 remediation
technical candidate 是 `not-run`，不能从旧 run 迁移 `pass`。
更早 PR #17 证据包括：

- [Desktop source CI run 30611309112](https://github.com/fredgnr/local-context-forge/actions/runs/30611309112)：
  Python、Web、Desktop source checks，以及 macOS 15 arm64 source IPC contract 均成功；
- [Container PR build run 30611309114](https://github.com/fredgnr/local-context-forge/actions/runs/30611309114)：
  容器 PR 构建成功，但不发布镜像。

这些运行不包含可用 packaged smoke、真实签名、
DMG、模型权重、已登录 Codex、干净用户安装或 GitHub 控制面验证，因此不能提升任何
packaged/physical gate。

## 交付路径状态

| 路径 | 当前可用性 | 适用对象 | 主要限制 |
| --- | --- | --- | --- |
| Electron 源码模式 | 可用于开发和 source 验证 | 开发者 | 借用开发机 Python/Node；不是正式包 |
| 最小 packaged smoke | old static assembly technical `pass`；reviewed candidate independent `NO-GO`；remediation `not-run`；packaged launch/runtime `not-run` | W02 removal feedback | old exact Draft runs cannot prove scratch lifecycle/provenance/cleanup；没有启动 assembled App，不完成 `VAL-PACKAGED-SMOKE-001` |
| 完整 engineering test package | `planned` / `not-run` | W04–W12 工程物理验证 | 只能从 W10/W11 cleaned tree 构建；UNOFFICIAL、无 production trust/tag/upload |
| Electron 正式 DMG | `not-run` / 不推荐 | 将来的普通用户 | trust pins、签名、真机和 promotion 未完成 |
| Legacy Docker/Web | 已弃用、unsupported、待删除 | 仅用于解释当前仓库残留 | 不承诺修复、迁移、兼容窗口或继续可用 |
| Windows + Ollama | unsupported | — | Electron 不支持远程 Windows worker；legacy 路径将删除 |
| 公开 Sites guide | stale / 未验证 | 暂不作为使用入口 | 仍含 legacy 可复制命令；本 checkout 缺 hosting identity，禁止猜站点或误部署 |

不要新建 legacy 部署。仓库中暂存的 `./install.sh`、`install.command`、`make install`、
Compose 和 localhost HTTP 路径尚未从代码删除，但不再是受支持交付路径；它们会由
ITER-0008 的 W10/W11 slices 移除。此状态变化不自动停止现有容器，也不读取、迁移或删除旧数据。

## 阶段状态

| 阶段 | 状态 | 已有内容 | 尚缺的退出证据 |
| --- | --- | --- | --- |
| P0 治理与契约 | `validated` | AGENTS、skills、ADR、迭代、追踪矩阵 | 持续维护链接和证据 |
| P1 Electron 信任边界 | `in-progress` | Main/preload/renderer source 合同 | packaged renderer/IPC 审计 |
| P2 Python sidecar | `in-progress` | PyInstaller/Dulwich/source 打包合同 | clean M4 bundled runtime |
| P3 QMD/MCP/provider | `in-progress` | worker、broker、companion、attempt source 合同 | native QMD、真实模型、真实 CLI/MCP |
| P4 Desktop 数据、模型 | `planned` | 标准路径部分落地 | Desktop backup/restore、完整模型供应链、unknown layout fail-closed |
| P5 DMG 与发布 | `planned` / 后置 W14–W16 | 两阶段 workflow/source policy | W13、GitHub settings、trust pins、签名 Draft、clean-user |
| P6 更新实机门禁 | `planned` | signed check/download/open-DMG source client | 真实 `N-1 → N`、失败注入；automatic apply 尚未设计 |
| P7 Electron-only 退出 | `in-progress` | W01 已闭环；W02 old static assembly/audit 是历史技术结果，PR #21 current independent verdict `NO-GO`；ADR-0015/0016、W01–W16 与严格删除计划 | PR #21 remediation、W02 packaged runtime smoke、W10/W11 slices、W03 engineering package、W13 final gates |

P2/P3 的实现依赖 P1 已冻结的 source IPC contract，而不是 P1 的完整 packaged gate。
P5/P6 的 source foundation 提前落地，不代表可以绕过 P4 或对应物理退出门禁。

## 验证门禁摘要

### Source 级已有证据

| Gate | 旧 candidate technical / independent / activation | accepted remediation final PR/source | accepted final independent acceptance | resulting-main source | canonical activation |
| --- | --- | --- | --- | --- | --- |
| `VAL-PRE1-SEQUENCE-001` | `pass` / `fail` / `not-eligible` | `pass` | `pass` | `pass` | `pass` |
| `VAL-GOV-001` | `pass` / `fail` / `not-eligible` | `pass` | `pass` | `pass` | `pass` |
| `VAL-CI-COVERAGE-001` | `pass` / `fail` / `not-eligible` | `pass` | `pass` | `pass` | `pass` |

Checkpoint A 仍是历史 remediation 记录；当前列使用 exact accepted final、独立验收、accepted
merge 与 resulting-main source run 的后续外部事实。PR head、synthetic merge SHA 与 resulting
main SHA 未静默互换。W01 全部退出只解锁 W02 实施，不解锁 W10/W11 或任何 packaged、physical、
settings、signing、Release gate。

其他既有 source 证据：

| Gate | 结果 | 说明 |
| --- | --- | --- |
| `VAL-GOV-001` baseline | `pass` | `71890ee` 的 Python source job（Actions 30611309112）包含 Markdown 相对链接检查 |
| `VAL-DOC-HANDOFF-001` R11 local review | `pass`（仅本地） | 修复后三路只读审计无 Critical/High/Medium；dirty worktree 不能替代最终 commit/PR |
| `VAL-DOC-HANDOFF-001` R11 checkpoint | `pass` | [`625db76` clean-checkout 证据](evidence/VAL-DOC-HANDOFF-001/2026-07-31-625db76.md)；冻结全部实质文档 |
| `VAL-DOC-HANDOFF-001` R11 final head | `not-run` | clean checkout/最终 PR head 的 commit-bound 复核待运行 |
| `VAL-GOV-001` R11 final head | `not-run` | 本轮本地检查后，仍须由 documentation PR 最终 head CI 绑定 |
| `VAL-GOV-001` R12 checkpoint | `pass` | `64ec3c2` clean-checkout link/version/skill/diff/ID checks；证据同下一行 |
| `VAL-LEGACY-SCOPE-001` R12 checkpoint | `pass` | [`64ec3c2` clean-checkout evidence](evidence/VAL-LEGACY-SCOPE-001/2026-07-31-64ec3c2.md)；只验证 planning/docs scope |
| `VAL-P1-SOURCE-001` | `pass` | Linux/macOS source jobs 与真实 AF_UNIX bind |
| `VAL-P1-REGRESSION-001` | `pass` | Backend/Desktop/Web/Host Runner 已有组件证据 |
| `VAL-RELEASE-POLICY-001` | `pass` | 两阶段 workflow/bootstrap 的 source policy |
| `VAL-RELEASE-PROMOTION-001` source | `pass` | Draft-only、trusted-main、fixed Release ID source 合同 |
| `VAL-UPDATE-CLIENT-001` | `pass` | manifest、cache、IPC、verified DMG source 合同 |
| `VAL-LOCAL-SOURCE-001/002` | `pass` | grant/path 与 Backend 双层 source policy |

W02 historical static assembly 与 current remediation（均不等于 packaged runtime gate）：

| Substage | 结果 | 证据与限制 |
| --- | --- | --- |
| historical engineering-smoke `.app` directory assembly / bundle audit | technical `pass` | Draft PR #21 exact `08137c7…`；[run `31024794972` / job `92370351806`](https://github.com/fredgnr/local-context-forge/actions/runs/31024794972/job/92370351806)；inventory SHA-256 `7fcdb699…`；remote artifacts empty；assembled App 未启动；cannot migrate to later head |
| historical pre-pack frozen sidecar staging smoke | technical `pass` | old assembly job build step；仅为 staging history，sidecar 未从 assembled bundle 启动；不能证明 held lifecycle |
| reviewed PR #21 candidate independent acceptance | `NO-GO` | exact `8c5fd232…` / tree `785f4656…`；H1 scratch capability/Git provenance/fail-closed cleanup blocker；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| same PR remediation technical candidate | `not-run` | new exact head and fresh Actions required；old `310269*` runs cannot be reused |
| packaged App launch/runtime | `not-run` | `VAL-PACKAGED-SMOKE-001` 仍未运行，W10/W11 locked |

### 必须保持 `not-run`

| Gate | 最低真实环境 |
| --- | --- |
| `VAL-PACKAGED-SMOKE-001` | 独立 engineering-smoke mode 的 macOS arm64 packaged App |
| 六个 `VAL-LEGACY-*` slice gate | exact before/after commit 与 fresh package digest；本 Work 不执行删除 |
| `VAL-ENGINEERING-PACKAGE-001` | W10/W11 cleaned tree 的完整 non-release 工程包 |
| `VAL-TRUST-001` | packaged App 的 renderer/Main 权限审计 |
| `VAL-PY-001`、`VAL-GIT-001`、`VAL-IPC-001` | 无外部 runtime 的 clean macOS arm64 |
| `VAL-QMD-001`、`VAL-QMD-EMBED-001`、`VAL-MODEL-EMBED-001` | bundled native QMD + 真实模型 |
| `VAL-CLI-001` | 已安装并登录的真实 Codex/Cursor |
| `VAL-MCP-001`、`VAL-MCP-ONBOARD-001` | `/Applications` packaged App + 官方签名 Codex |
| `VAL-LOCAL-SOURCE-003` | home、外置卷、私有仓库和重启物理矩阵 |
| `VAL-DATA-001`、`VAL-MODEL-001` | Desktop backup/restore、完整模型下载/激活 |
| `VAL-SECRET-001` | 真实 GitHub Environments/rulesets/Immutable Releases |
| `VAL-RELEASE-001`、`VAL-INSTALL-001` | 真实签名 Draft 与 clean-user Gatekeeper/smoke |
| `VAL-UPDATE-001` | 两个真实单调版本的 `N-1 → N` 与失败恢复 |
| `VAL-ELECTRON-CUTOVER-001` | W13 final cleaned engineering package；W16 exact Draft digest 的完整第二次执行 |
| `VAL-LEGACY-ABSENCE-001` | W13 同一 engineering digest；W16 exact Draft/tag source 的第二次 aggregate absence |
| `VAL-RELEASE-CONTINUITY-001` | W13 checkpoint→formal tag allowlisted diff、tag source/absence 与 W16 exact Draft cutover/absence |

`VAL-LEGACY-001` 与 `VAL-LEGACY-CONTROL-001` 从未运行，并由 ADR-0015 取代；它们保持
`not-run (superseded)`，不再是退出或发布门禁。

完整 REQ/ADR/ITER/VAL 映射见[追踪矩阵](traceability.md)。

## 当前阻塞

1. Draft PR #21 reviewed `8c5fd232…` / tree `785f4656…` 的最终独立结论是 `NO-GO`。必须先在
   同一 branch/PR 修复 held-dirfd/inode scratch lifecycle、exact Git tree/committed-source provenance、
   capability-bound publish/rollback/evidence 与 fail-closed cleanup，并为新 exact head 取得 fresh
   source/assembly Actions；旧 `310269*` runs 不能迁移为 remediation `pass`。
2. packaged App launch/runtime harness 仍未实现或运行，assembled App 未启动、sidecar 未从
   bundle 启动，`VAL-PACKAGED-SMOKE-001=not-run`；因此 W10/W11 destructive slices 继续 locked。
3. W10/W11 的 decouple/deploy/transport/provider/release/docs slice 均未执行，container/GHCR
   workflow 与 legacy runtime 仍在。
4. W03 cleaned-tree engineering package 以及 Desktop data/backup/model/runtime/CLI/MCP/local 的
   W04–W12 工程物理矩阵尚未完成。
5. `macos-signing`、`macos-release`、三组 ruleset 和 Immutable Releases 的真实设置没有证据；
   按 ADR-0016 这些工作后置到 W14，不是 W02/W10/W11 的当前前置。
6. `runtime/update-metadata-key.lock.json` 和
   `runtime/macos-codesign-certificate.lock.json` 仍为 `unprovisioned`；生产公钥文件不存在。
7. 没有由受保护 workflow 生成且通过 continuity、exact Draft cutover/absence 与真机测试的唯一
   Draft 候选。
8. 更新客户端当前只支持签名检查、下载和打开 DMG；automatic apply/install/restart/
   rollback 没有已接受设计和实现。
9. `guide-site` 源和现有公开说明仍包含 legacy 安装/localhost/Host Runner 内容，且本 checkout
   没有可验证的 `.openai/hosting.json`；必须先恢复 exact Sites identity，再改写、测试和留下
   checkpoint deployment evidence。当前站点不是权威使用入口。

`guide-site/**` is excluded from `make ci-source` and Desktop source CI；该机器声明表示
`external-blocked` / unvalidated，不表示其源码、部署或公开站点已通过。

## 下一步工作分组

### Ready now：无需外部管理员或物理候选

1. 在 Draft PR #21 现有 branch 上完成 H1 remediation，运行 deterministic rename/recreate/ABA、
   provenance drift、publish/rollback/evidence/cleanup failure tests；对新 exact head 运行 fresh source 与
   assembly Actions，再交付独立验收。保持 remote artifact、production trust、tag/Draft/Release 边界
   不变，不启动 packaged App；
2. 后续 Work 在 independently accepted exact bundle implementation 上 fresh build、绑定 digest、启动 App并运行 runtime
   smoke，并在 resulting `main` 重跑，才可把 `VAL-PACKAGED-SMOKE-001` 提升为 `pass`；
3. W02 完整 gate 通过后，按 [work plan](work-plan.md) 分别认领 W10/W11 slice；不能把它们合成无
   owner 的大删除。

### Dependency-blocked：先取得前序设计/格式证据

1. W10/W11 每个 destructive slice 依赖 W02、exact ownership，以及 affected replacement 或合格
   pure-legacy unsupported disposition；不依赖 unrelated full physical gate；
2. W03 依赖全部 W10/W11 slice；W04 data/layout/backup 和 W05 model 再依赖 cleaned package；
3. W06–W12 使用同一工程 artifact class 完成 runtime、QMD、CLI、MCP、local 与物理矩阵；
4. W13 依赖 W03–W12，并在 final rebuilt digest 上同时运行 cutover/absence；
5. Draft、promotion 与真实 `N-1 → N` 依赖 W13–W15；promotion 前还必须在 exact Draft
   digest 重跑 cutover/absence，并通过 `VAL-RELEASE-CONTINUITY-001`。

### Admin-blocked：需要仓库控制面权限或独立 reviewer

以下任务已知需要管理员，但按新顺序必须等待 W13，不应现在执行：

1. W14 `TODO-REL-GOV-001`：配置两个 Environment、三组 ruleset 和 Immutable Releases；
2. W15 `TODO-REL-KEYS-001`：只能在 W14 通过后由可信管理员 provision credential bundle 并
   提交 public trust pins。

解除依赖后，才依次创建唯一 Draft、完成同一资产的 M4 物理测试、从
`workflow_dispatch --ref main` promotion，并用两个真实单调版本完成 `N-1 → N`。Automatic
apply 若要实现，必须先新增或 supersede ADR-0011。

每项的 owner、依赖、产物和验收条件见[详细 TODO](todo.md)。

## 状态更新规则

- 只有包含 commit、环境、命令、结果和脱敏证据位置的记录才能把 gate 标为 `pass`。
- “当前工作树通过”、mock、fake store、source build 或同版本重装不能替代 packaged/
  physical gate。
- 更新本页时同步活动迭代和[追踪矩阵](traceability.md)；架构决策变化先新增或
  supersede ADR。
- 公开 Release 之前再次核对本页结论；任一必需 gate 为 `fail` 或 `not-run`，仍是
  **release NO-GO**。
