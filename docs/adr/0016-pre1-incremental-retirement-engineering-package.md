# ADR-0016：Pre-1.0 增量式 legacy retirement 与工程测试包门禁

- 状态：Accepted
- 日期：2026-08-03
- 关联需求：REQ-PRE1-SEQUENCING-001、REQ-PACKAGED-SMOKE-001、
  REQ-LEGACY-SLICE-001、REQ-ENGINEERING-PACKAGE-001、REQ-ELECTRON-ONLY-001
- 关联验证：VAL-PRE1-SEQUENCE-001、VAL-PACKAGED-SMOKE-001、
  VAL-LEGACY-DECOUPLE-001、VAL-LEGACY-DEPLOY-001、VAL-LEGACY-TRANSPORT-001、
  VAL-LEGACY-PROVIDER-001、VAL-LEGACY-RELEASE-001、VAL-LEGACY-DOCS-001、
  VAL-ENGINEERING-PACKAGE-001、VAL-ELECTRON-CUTOVER-001、
  VAL-LEGACY-ABSENCE-001、VAL-RELEASE-CONTINUITY-001
- 部分取代：ADR-0015 §1 第一段的全局 replacement/pass-before-deletion 语句、§3 全文、
  “后果”中退役前先完成完整 packaged M4 的成本条目，以及验证结尾的统一删除前置
- 实施计划：[Pre-1.0 work plan](../development/work-plan.md)与
  [legacy retirement manifest](../development/legacy-retirement.md)

## 上下文

ADR-0015 正确确定了 Electron-only 目标、严格 `remove` / `retain` / `split` 边界、用户数据
保护和最终 absence gate，但把完整 `VAL-ELECTRON-CUTOVER-001` 设为任何 legacy 删除的统一
前置。该顺序要求先把 Docker、browser HTTP、Host Runner、legacy MCP、container/GHCR 等废弃
表面一起带入完整工程打包、SBOM、依赖审计和物理验证，然后才删除它们。

项目仍处于 pre-1.0，未对这些 legacy 表面承诺兼容性。继续把它们带入完整工程包会扩大
维护、打包和审计范围，并在最终收敛时产生重复工作。但在完全没有 packaged 反馈回路时直接
删除共享目录同样危险：`web/src/**` 是 Electron renderer，`backend/app/**` 同时包含 private
UDS sidecar 与领域服务，目录名不能证明所有权。

因此需要一个介于 source CI 与完整工程测试包之间的最小 packaged smoke harness，并把
legacy retirement 改成可独立复核、可独立回退的 slice。完整工程测试包应建立在清理后的
Electron-only tree 上。正式 GitHub 控制面、production credentials、trust pins 和 Release
继续保持 fail closed，但在最终 cutover/absence 前不抢占实现顺序。

## 决策

### 1. 三种产物严格分离

REQ-PACKAGED-SMOKE-001：最小 packaged smoke artifact 只建立删除反馈回路。它必须绑定 exact
commit、artifact digest、架构和有限 inventory，至少验证 packaged App 启动、renderer/preload
握手、Main 启动 private UDS sidecar、一个健康/领域请求、正常退出、无 orphan、无 public INET
listener，且 exercised path 不从系统发现 Python/Node/Git。
它不得被描述为完整工程包、安装候选或发行候选。

REQ-ENGINEERING-PACKAGE-001：完整 engineering test package 必须从完成 W10/W11 清理后的 tree
构建，包含 Electron renderer、bundled Python sidecar、QMD worker、stdio MCP companion 和工程
测试入口，作为数据、模型、Python、QMD、CLI、MCP、本地仓库和物理验证的载体。

两类 engineering artifact 均必须：

- 显著标记 `UNOFFICIAL`、`engineering-only`、`publishable=false`；
- 只使用 unsigned 或 ad-hoc identity，不读取 production Environment 或 release secret；
- 不要求或嵌入 production update public key/certificate lock；updater 为 `unavailable` 且不联网；
- 不由 release tag 触发，不上传 GitHub artifact，不创建 Draft/Release，不进入 update feed，
  不能 promotion；
- 不提升 `VAL-PACK-001`、`VAL-INSTALL-001`、`VAL-RELEASE-001`、`VAL-SECRET-001` 或
  `VAL-UPDATE-001`。

这要求后续实现独立的 engineering packaging mode；不得放宽 formal `beforePack`、update trust
audit 或现有 release policy tests。当前仓库没有可用的最小 harness，本 ADR 只接受门禁和
任务，不宣称 `VAL-PACKAGED-SMOKE-001` 已运行。

Formal release candidate 仍只允许在 W13 cleaned engineering checkpoint 的 cutover/absence
通过后，由生产 GitHub 控制面、正式凭据和 trust pins 按 ADR-0014 的 tag → unique Draft →
trusted-main promotion 链产生。由于 W15 的 production pins、签名配置和 release metadata 会
形成新的 commit/bytes，W13 证据不能直接复用为该正式候选证据；§5 的连续性门禁必须另行通过。

### 2. 固定执行顺序

REQ-PRE1-SEQUENCING-001：W ID 是稳定工作包标识，不是执行序号。权威执行顺序固定为：

```text
W01 → W02 → W10 → W11 → W03 → W04 → W05 → W06 →
W07 → W08 → W09 → W12 → W13 → W14 → W15 → W16
```

其阶段语义为：

1. 治理与 source baseline，包括 `VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001` 与
   `VAL-CI-COVERAGE-001`；
2. 最小 packaged smoke harness；
3. W10/W11 的独立 legacy slices；
4. 清理后的完整 engineering test package；
5. 数据、模型、Python、QMD、CLI、MCP、本地仓库和工程物理矩阵；
6. W13 exact cleaned engineering checkpoint 的 Electron cutover 与 legacy absence；
7. GitHub production control plane；
8. production credentials/trust pins、formal candidate、唯一 Draft、promotion 与真实更新门禁。

GitHub Environments、rulesets、Immutable Releases、production credential bundle、正式签名身份、
production update public key/certificate lock、正式 tag/Draft/promotion 均不得为了 W02/W03 提前
配置或使用。
W02 也不得在 W01 的 `VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001` 与
`VAL-CI-COVERAGE-001` 全部通过前开始。

### 3. 独立 removal slice

REQ-LEGACY-SLICE-001：聚合 `VAL-ELECTRON-CUTOVER-001` 不再是每个早期 deletion slice 的统一
授权条件。每个 slice 必须独立满足以下前置和后置门禁：

前置：

1. ADR-0016 已 Accepted，`VAL-PACKAGED-SMOKE-001` 在 slice baseline 为 `pass`；
2. exact path/capability 已标为 `remove`、`retain` 或 `split`，有唯一 owner 与 caller inventory；
3. shared path 先完成 Electron/legacy 解耦；受影响的现有或必需 Electron capability 必须有
   replacement，其 focused source/integration gate 为 `pass`；
4. 对纯 legacy-only 且已由 REQ-PRE1-BREAKING-001 明确不支持的 capability，可记录
   `no-replacement / unsupported`，但必须用 caller inventory 证明没有 Electron owner、没有用户
   数据或外部副作用，且该例外不得用于 protected Electron path、数据保留、最终必需产品能力或
   formal release safety chain；
5. 明确本 slice 不修改或删除用户 data、volume、container/image、Application Support、Keychain、
   历史 evidence、远端 GHCR package 或 GitHub Release。

后置：

1. 从 slice 的 exact head 重建新的 non-release package，重跑相同 packaged smoke；
2. focused 与 aggregate source regression 通过；
3. 对应 slice absence gate 通过，且 protected Electron paths/resources 的 presence gate 通过；
4. evidence 绑定 commit、package digest、命令、环境、结果和回退点；
5. 失败只回退该 slice，不恢复或扩展 legacy 长期支持。

未被 slice 触及的模型、真实 CLI/MCP、外置卷等完整物理 gate 可以继续 `not-run`，不再阻断
其他独立 slice。任何涉及 shared ownership、用户数据或不明确 external side effect 的 slice
仍必须 fail closed。

### 4. 最终聚合门禁仍然保留

`VAL-ELECTRON-CUTOVER-001` 改为清理后 W13 exact engineering checkpoint 的最终能力声明门禁，
而不是所有早期 slice 的全局前置。`VAL-LEGACY-ABSENCE-001` 仍验证所有 forbidden path、
listener、import、workflow 与 active-doc 已消失，且 protected renderer、sidecar、QMD、companion、数据与 formal
release safety paths 仍存在。

两个门禁都通过前不得宣称 Electron-only 完成；它们通过前也不得进入 production GitHub
controls/credentials。slice-level pass 不能相互替代或聚合成未经运行的 final pass。

### 5. 正式发行安全链后置但不削弱

ADR-0003、ADR-0011 和 ADR-0014 继续完整有效：

- ordinary/non-release build 可使用 unsigned/ad-hoc test artifact；
- unprovisioned updater 必须 `unavailable` 且不发起网络请求；
- 正式候选仍需受保护 tag、`macos-signing`、唯一 Draft、physical review、trusted-main fixed-ID
  promotion、不可变资产和完整 post-publish attestation；
- `VAL-RELEASE-CONTINUITY-001` 必须证明 W13 checkpoint 到 formal tag 的 source diff 只包含
  明确 allowlist 的 production public trust pins、release metadata 与版本变更，不包含 runtime
  逻辑或任何 legacy surface；并在 formal tag 重新运行 source/aggregate absence；
- continuity verifier、allowlist 与 evidence schema 必须在 W13 checkpoint 前进入 source 并冻结；
  W13 后若首次新增或修改它们，或出现其他非 allowlisted source diff，必须建立新 W13 checkpoint
  并重跑 cutover/absence；
- W16 必须在**将要公开的唯一 Draft 的精确 digest**上重新运行完整
  `VAL-ELECTRON-CUTOVER-001` 与 `VAL-LEGACY-ABSENCE-001`。W13 engineering package 的 pass
  只解锁 W14，不能替代这次正式候选复验；
- `VAL-SECRET-001`、`VAL-PACK-001`、`VAL-INSTALL-001`、`VAL-RELEASE-001` 与真实
  `VAL-UPDATE-001` 仍是 formal release 的 fail-closed 门禁。

“后置”只改变实施优先级，不授权绕过或降低这些控制。

## 对 ADR-0015 的影响

本 ADR 精确取代 ADR-0015 以下顺序条款：§1 第一段中“Electron 完整替代相应能力并通过本 ADR
门禁后才删除”的全局语句；§3 全文；“后果”的成本条目“退役前仍需完成 packaged M4 真机能力
验证”；以及验证结尾中把完整聚合 cutover 作为任何删除统一前置的句子。以下 ADR-0015 条款
继续有效：

- Electron-only 唯一目标与 pre-1.0 无兼容窗口；
- 严格 `remove` / `retain` / `split` 和 protected Electron paths；
- private UDS、Main trust boundary、stdio companion 与 Context7 工具语义；
- 不删除用户数据、外部资产、Application Support、历史 ADR/iteration/evidence；
- 最终 `VAL-ELECTRON-CUTOVER-001` 与 `VAL-LEGACY-ABSENCE-001`；
- 远端 package、Release 或本机用户资产的删除需要独立显式授权。

ADR-0015 保持 Accepted，不重写其历史正文；实施以本 ADR 的后续顺序为准。

## 后果

正面后果：完整 engineering package、SBOM 和物理矩阵只覆盖目标 Electron 架构；每个 legacy
slice 有 packaged 反馈、明确 owner 和小回退半径；GitHub/credential 管理不会阻塞 pre-1.0
代码收敛。

成本与限制：必须先实现一个明确隔离于 formal release 的 packaged harness；每个 slice 都要
重复构建和 smoke；W13 必须在同一 cleaned engineering digest 上完成完整能力矩阵，而 W15/W16
还必须对 production 变更和 exact Draft 单独证明连续性，早期 pass 不能累加为发行证明。

## 被拒绝的替代方案

1. **继续要求完整 cutover 后才删除任何 legacy。** 拒绝：把废弃运行面带入完整工程包和
   审计，造成重复维护与返工。
2. **没有 packaged feedback 就一次性删除所有 legacy。** 拒绝：shared renderer/sidecar/
   provider ownership 无法仅靠目录名证明。
3. **把现有 formal package 配置直接改成宽松模式。** 拒绝：会削弱 production trust audit；
   engineering mode 必须显式隔离。
4. **先配置 GitHub controls/credentials，再做清理。** 拒绝：这些控制只服务正式发行，并非
   pre-1.0 source 收敛前置。
5. **把 engineering package 上传为 Draft 供测试。** 拒绝：会混淆 artifact class，并绕过
   formal tag、credential 和 promotion 边界。

## 验证门禁

- `VAL-PRE1-SEQUENCE-001`：机器检查 W01–W16 唯一映射和权威执行顺序，验证所有新
  REQ/TODO/VAL 在 TODO、traceability、iteration 中闭环，且 formal work 位于 final
  cutover/absence 之后。
- `VAL-PACKAGED-SMOKE-001`：未来在真实 packaged App 上运行；当前 `not-run`。
- `VAL-LEGACY-DECOUPLE/DEPLOY/TRANSPORT/PROVIDER/RELEASE/DOCS-001`：各 slice 在 exact
  before/after commit 和 package digest 上独立运行；当前均 `not-run`。
- `VAL-ENGINEERING-PACKAGE-001`：清理后的完整 non-release 工程包与 inventory；当前
  `not-run`。
- `VAL-ELECTRON-CUTOVER-001`、`VAL-LEGACY-ABSENCE-001`：W13 cleaned engineering
  checkpoint，以及 W16 exact Draft 的独立聚合复验；两个执行点当前均 `not-run`。
- `VAL-RELEASE-CONTINUITY-001`：W13 checkpoint → formal tag 受限 diff、formal tag source/
  absence，以及 exact Draft 上重新运行的完整 cutover/absence；当前 `not-run`。
- `VAL-SECRET/PACK/INSTALL/RELEASE/UPDATE-001`：正式阶段保持 `not-run`，不能由任何
  engineering artifact 提升。
