# 项目状态快照

本页是 Local Context Forge 当前状态的权威入口。用户指南、路线图、迭代记录和 Release
说明应链接本页，不应各自推断“已经可发布”。架构与实现细节分别见
[系统设计](../17-system-design.md)和[开发者手册](contributor-handbook.md)；剩余工作见
[TODO](todo.md)。

## 快照坐标

| 字段 | 值 |
| --- | --- |
| 截止日期 | 2026-08-12 |
| canonical repository | `fredgnr/local-context-forge` |
| 本轮实施基线 | `main@1786255b55dd1a78659ed92235893876175a0722` |
| 基线来源 | PR #20 accepted final `36885e04df09c4789d8ec3c9dc5c5e78a381a634` 合入；accepted/resulting-main tree 均为 `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64` |
| 产品版本 | `0.3.0-alpha.1` |
| 数据库 schema | `5` |
| 活动父迭代 | [ITER-0002](iterations/0002-bundled-runtimes.md) |
| 活动实施记录 | [ITER-0008](iterations/0008-incremental-retirement-engineering-package.md) / W02 |
| W02 historical static assembly checkpoint | Draft PR #21 `08137c7bce5469350b861cef7960e4a0530151bf` / tree `d7814ac96136cea33fb7069d9538a4aad8dffa38`；assembly run `31024794972` / job `92370351806`；technical history only |
| W02 latest independent review | Draft PR #21 `8c5fd23206b671b768fd21d253bf292642f93a51` / tree `785f4656de8a7233b6dd632fe4815976d33468fb`；independent `NO-GO`（append-only） |
| W02 first remediation attempt | exact `9f7d5d11225517ff5b1643d4bb71983346358ae0` / tree `ea8e62e9b76c3270d60135a8633f56db025ad921`；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 second remediation attempt | exact `9ecf0effaa48a8b010ff46ffb42afc57e0f3d948` / tree `ee82712c7874155eba038d1ce05d374416ed34e5`；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 third remediation attempt | exact `2665ec61712fe410608ac50c7a6d44fa35746092` / tree `c3cd1706838f7050533e2812dfdcad482aaedde5`；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 fourth remediation attempt | exact `c2be665f5832c15064cae87c694a782e51351e7c` / tree `f90b527b4de1a422f63c4bfeb01f9c1010e22b7d`；Desktop `31358373316` success；Containers `31358373311` success/no publish；Engineering `31358373320` / job `93362214499` fail；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 fifth remediation attempt | exact `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / parent `c2be665f5832c15064cae87c694a782e51351e7c` / tree `2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5`；Desktop source `31454826261` / Python job `93666344561` fail；Engineering `31454826263` / job `93666344718` fail / cleanup success；Containers `31454826243` success/no publish；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 sixth remediation attempt | exact `cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` / parent `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / tree `911e91d6849266fa75b0efde794ae9b5236f5504`；Desktop source `31460588210` success；Engineering `31460588223` / job `93683139742` fixed launcher unsafe fail / cleanup success；Containers `31460588212` success/no publish；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 seventh remediation attempt | exact `aaf3f51f69dfded82b8237e03a871017317e7158` / parent `cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` / tree `60c2c6c2553ff8d10c2faee47ec838b34e378fc5`；Desktop source `31559498106` success；Engineering `31559498116` / job `93998717925` manifest literal primary fail / unbound-source cleanup secondary fail；Containers `31559498070` success/no publish；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 eighth remediation attempt | exact `15336568c6fcf3a40eb051cdb2b90242ef1e1e09` / parent `aaf3f51f69dfded82b8237e03a871017317e7158` / tree `66779e9ca8df445fb413e93faed4d265899fb1ec`；Desktop source `31570734560` success；Engineering `31570734636` / job `94031972543` root-owned quarantine canonical `cd` permission fail after manifest/component checks passed；cleanup success did not prove framework quarantine residue absent；Containers `31570734580` success/no publish；technical `fail` / `superseded`；independent `pending`；activation `blocked` |
| W02 ninth remediation candidate | current worktree / pre-commit；无 committed exact head/tree 或 fresh exact-head Actions；technical `not-run`；independent `pending`；activation `blocked` |
| 当前结论 | **W02 in-progress：latest independent `NO-GO`（仅绑定旧 reviewed head/tree）；eight remediation attempts `fail` / `superseded`；ninth exact candidate `not-run`（current worktree / pre-commit；无 committed exact head/tree；无 fresh exact-head Actions）；packaged launch/runtime `not-run`；W10/W11 locked；public release NO-GO** |

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
artifacts empty，因此这不是 packaged runtime gate，也不是任何 later remediation candidate 的
evidence。

最终独立验收随后绑定 PR #21 reviewed head
`8c5fd23206b671b768fd21d253bf292642f93a51` / tree
`785f4656de8a7233b6dd632fe4815976d33468fb` 并给出 `NO-GO`：旧 build scratch 没有 held
dirfd/inode capability，Git provenance 没有绑定 exact tree/committed source bytes，publish、rollback、
failure evidence 与 cleanup 仍可受 pathname rename/recreate/ABA 影响。旧 exact-head assembly run
`31026905444` / job `92377586784`、source run `31026907916`、container run `31026906777` 只作为
失败候选的历史技术结果保存。当前 [append-only remediation record](evidence/W02/2026-08-07-pr21-remediation.md)
固定 `CTX-PR21-NOGO-CURRENT`，并追加第一次 remediation exact
`9f7d5d11225517ff5b1643d4bb71983346358ae0` / tree
`ea8e62e9b76c3270d60135a8633f56db025ad921` 的技术失败。其 committed-source snapshot / renderer
lock SHA-256 分别为 `6b44dc785f6f3cd957e35c3eff1857ef55ac07a6fb3a98dcab44601486d2c1e6` /
`ae4f9bdf4283763a980ee4b21f3fdd844d4de43a0b35fa7086406eddc2ab857f`。

第一次 remediation 的 assembly run `31181911570` / job `92876982671` 因
`Installed toolchain symlink is unsafe` 失败；cleanup-only gate 成功，但后续 assembly/audit/test
stages 跳过且 engineering product artifacts 为 `[]`。source run `31181911534` 也是 `fail`：Python
`739` pass / `2` fail / `1` skip（unsafe ownership or mode），Desktop `292` pass / `1` fail
（缺 `web/node_modules/vite`），Web `51/51` success，macOS IPC `49` pass / `1` warning success；
W01 aggregate fail closed。container run `31181911527` 为 `3/3` success，但 PR 不 publish，login/
platform verify 跳过且 `push=false` / `load=false`；Buildx records 不是 product artifacts。

W01 failure evidence payload artifact `8995148172` 的 ZIP / inner SHA-256 为
`d0fa244c318fd64039eb70618be023103465ab580d9c192b643558d49b2c27aa` /
`0d48fc0ca4b7edab977f31484f14c39cab5a7ecbc7b5299a2d1f2b1c22a86709`；provenance artifact
`8995148811` 为 `a43697a8b83737ddda3b3e102a270b299adf6658a2f7d3017ffd93cad2af9c3a` /
`bb5dc6ae465782e220b5bdde2dd309a5c8662255426d4c51a28fc871eced21a4`。它们绑定上述
source/tree/run/PR #21，result `fail`、independent `pending`、activation `blocked`。第一次 attempt
已 `superseded`。

第二次 remediation exact `9ecf0effaa48a8b010ff46ffb42afc57e0f3d948` / tree
`ee82712c7874155eba038d1ce05d374416ed34e5` 的 source snapshot 为
`9080dd15fe407ab7947b28a58bedec60f8a7422a9245b551a7b065117514d50c`。engineering run
`31184441362` / job `92885372402` 因 `Installed toolchain file is unsafe` 失败，cleanup-only
success，后续 assembly/audit/tests skipped，engineering product artifacts 为 `[]`。source run
`31184441306` 也是 `fail`：Desktop `293/293`、Web `51/51`、macOS IPC `49` pass / `1` warning
success；Python `744` pass / `2` fail / `1` skip / `2` warnings，QMD skipped，W01 aggregate
fail closed。container run `31184441281` 为 `3/3` success/no publication，registry login/platform
verification skipped 且 `push=false` / `load=false`。

第二轮 W01 payload/provenance artifacts `8996169850` / `8996170497` 的 ZIP SHA-256 分别为
`29e7f5c0f16edac4afcc3651888bad8994c23afbab9cf5945eb6ed3148c5434a` /
`643f143c27ca019e29660aa28d022e1411433f2a550dedac4b17e3d2c720d879`，inner SHA-256 分别为
`d8d76efe31b4a6fa0fec233b13bc4e72522af61e27159b29ff365c94966d02f7` /
`9e464c4a8dee2743c0e3b9ff5e22f8adf603c56e62a4240a16c51d9b146b8105`；重算值匹配，且绑定
source/tree、synthetic `6b1f30254f9627995756ecb75f51d4231849ced9`、run/PR #21、result `fail`、
independent `pending`、activation `blocked` 和 downstream `not-run`。第二次 attempt 同样已
`superseded`；下一 exact remediation technical candidate 尚未执行，不能从任一旧 run 迁移
`pass`，latest independent conclusion 仍是旧 head 的 `NO-GO`。

第三次 remediation exact `2665ec61712fe410608ac50c7a6d44fa35746092` / tree
`c3cd1706838f7050533e2812dfdcad482aaedde5` 的 source run `31258135929` 五个 jobs 全部
success，但 engineering run `31258135925` / job `93104615763` 在 locked Python sidecar 的
outer uv export 使用 `/dev/fd/<fd>/backend` cwd 时因 Darwin fdesc 不支持 child traversal 而失败；
cleanup-only success，后续 stages skipped，engineering product artifacts `[]`。container run
`31258135932` 中 API/MCP success，Web 的 target-arm64 Node/npm builder 在 QEMU 下 stall 后
cancelled；所有 PR login/platform-publish steps skipped，没有镜像 publication。第三次 attempt 已
`superseded`。

第四次 remediation exact `c2be665f5832c15064cae87c694a782e51351e7c` / tree
`f90b527b4de1a422f63c4bfeb01f9c1010e22b7d` 的 Desktop source run `31358373316` 五个 jobs
success，Containers run `31358373311` API/Web/MCP `3/3` success 且 PR no-login/no-push；Engineering
run `31358373320` / job `93362214499` 则在 inner build 以 exit `2` / `unclassified` 失败，随后的
cleanup-only gate 以 exit `1` 失败，后续 stages skipped、engineering product artifacts `[]`。
exact tree、运行平台与当时实现给出的高置信根因分别是 APFS/Darwin directory `nlink` 模型不兼容，
以及 sealed `0500` source directory 在 Darwin no-replace rename 前尚未恢复 owner-write；Apple APFS
reference 没有直接公开 `nchildren` 到 POSIX `st_nlink` 的映射，旧 raw log 也未输出 inner stage、
`st_nlink`、cleanup assertion label 或 errno。第四次 attempt 已 `fail` / `superseded`；第五次
candidate 只有 local regression，必须运行同一 exact head 的 fresh Desktop source、Engineering、
Containers Actions。

第五次 remediation exact `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / parent
`c2be665f5832c15064cae87c694a782e51351e7c` / tree
`2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5` 完成 fresh Actions 后仍为 technical
`fail` / `superseded`。Desktop source run `31454826261` 的 Python job `93666344561` 在
`0500` directory 内创建 test fixture 时以 `EACCES` 失败，尚未调用被测 product cleanup；
W01 evidence 随后 downstream fail closed。Engineering run `31454826263` / job
`93666344718` 在 Python framework installation 失败，cleanup step success。exact code path
与时序对“installer 替换当前 held Python launcher 后触发 post-exit identity drift”给出
高置信归因，但 raw log 没有直接输出 binding root cause 或 launcher 替换前后
identity。Containers run `31454826243` success/no publish，不能抵消前两路失败。该
Actions 未提供 assembled App launch/runtime evidence。

第六次 remediation exact `cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` / parent
`c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / tree
`911e91d6849266fa75b0efde794ae9b5236f5504` 完成 fresh Actions 后也为 technical `fail` /
`superseded`。Desktop source `31460588210` success；Engineering `31460588223` / job
`93683139742` 在 policy `67/67` 与 exact-Git `1/1` 通过后以固定错误
`Reviewed Python installer launcher is unsafe` 失败，cleanup success、later stages skipped、
engineering product artifacts `[]`；Containers `31460588212` success/no publish。source snapshot
SHA-256 为 `dfed1f824a60ebcfb0e8e9facfb46e5552f412b273cb58979596eb3c26d97884`。
该 Actions 未提供 assembled App launch/runtime evidence。

第七候选已提交的 producer/seal 设计不再使用 `actions/setup-python` 生产 reviewed framework，也不安装原
完整 product pkg。它在验证 locked archive 与 exact outer pkg signature/policy 后，只把
`Python_Framework.pkg` 的唯一 postinstall 固定替换为 17-byte no-op，并 re-expand 复验原
`Bom` / `PackageInfo` / `Payload` 后安装该 component。既有 exact root 先隔离且 target 必须
absent；安装后依次执行 non-symlink seal、大小写无关 cache 清理、以 O_NOFOLLOW-held
verifier/lock bytes 启动的 Node core/fresh-exclusion verification，再精确复验并清理 quarantine；
首次 framework Python 只允许位于该 cleanup 之后。运行时
`--install-reviewed-python` 只验证 locked distribution/framework/interpreter binding，不安装也不
调用 `sudo`。这些是第七次已提交的 producer/seal 设计，但它在执行到更早的 manifest literal
绑定时就已 fail closed，未进入 component install。

第七次 exact `aaf3f51f69dfded82b8237e03a871017317e7158` / parent
`cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` / tree
`60c2c6c2553ff8d10c2faee47ec838b34e378fc5` 完成 fresh Actions 后为 technical `fail` /
`superseded`。Desktop source `31559498106` success；Engineering `31559498116` / job
`93998717925` 在 archive 与 exact hashes manifest SHA-256 校验后，因 manifest 实际
uppercase digest + single-space 与 workflow lowercase digest + double-space literal 不符而 primary
fail。source provenance 因 producer 早退未绑定，cleanup-only gate 又无条件解引用 reviewed root，
形成 secondary fail；later stages skipped，artifacts `[]`。Containers `31559498070` success/no
publish。第八候选把 manifest 真实整行保持在 `grep -Fxc` + count one 的 fail-closed binding 中，
并让 cleanup 显式区分 unbound zero-residue 与 bound strict source/repo closure。第八次 exact
`15336568c6fcf3a40eb051cdb2b90242ef1e1e09` / parent `aaf3f51…` / tree `66779e9…` 的
manifest/component 检查通过，但 Engineering `31570734636` / job `94031972543` 在 root-owned
`0700` 空 quarantine 的 ordinary-runner canonical `cd` permission denied；cleanup success 仅覆盖
runner/source/repo，未证明 `/Library/Frameworks/**` residue absent，later skipped、artifacts `[]`、
no App launch。第八次为 technical `fail` / `superseded`。第九候选要求 privileged quarantine 在
普通 runner 访问前完成 canonical binding，并把 identity-bound exact framework quarantine zero-residue 加入
cleanup gate；current worktree / pre-commit，无 committed exact head/tree 或 fresh Actions，因此
保持 `not-run`。

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
| 最小 packaged smoke | old static assembly technical `pass`；latest independent `NO-GO`；eight remediation attempts `fail` / `superseded`；ninth exact candidate `not-run`；packaged launch/runtime `not-run` | W02 removal feedback | old/failed exact Draft runs cannot prove a later candidate；没有启动 assembled App，不完成 `VAL-PACKAGED-SMOKE-001` |
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
| P7 Electron-only 退出 | `in-progress` | W01 已闭环；W02 old static assembly/audit 是历史技术结果，PR #21 latest independent verdict `NO-GO`，first through eighth remediation technical attempts `fail` / `superseded`；ADR-0015/0016、W01–W16 与严格删除计划 | PR #21 ninth exact remediation candidate、W02 packaged runtime smoke、W10/W11 slices、W03 engineering package、W13 final gates |

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

W02 historical static assembly、eight remediation failures 与 ninth candidate（均不等于 packaged runtime gate）：

| Substage | 结果 | 证据与限制 |
| --- | --- | --- |
| historical engineering-smoke `.app` directory assembly / bundle audit | technical `pass` | Draft PR #21 exact `08137c7…`；[run `31024794972` / job `92370351806`](https://github.com/fredgnr/local-context-forge/actions/runs/31024794972/job/92370351806)；inventory SHA-256 `7fcdb699…`；remote artifacts empty；assembled App 未启动；cannot migrate to later head |
| historical pre-pack frozen sidecar staging smoke | technical `pass` | old assembly job build step；仅为 staging history，sidecar 未从 assembled bundle 启动；不能证明 held lifecycle |
| reviewed PR #21 candidate independent acceptance | `NO-GO` | exact `8c5fd232…` / tree `785f4656…`；H1 scratch capability/Git provenance/fail-closed cleanup blocker；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| first remediation exact candidate | `fail` / `superseded` | exact `9f7d5d…` / tree `ea8e62…`；assembly `31181911570` fail、source `31181911534` fail、container `31181911527` no-publish success；engineering product artifacts `[]`；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| second remediation exact candidate | `fail` / `superseded` | exact `9ecf0e…` / tree `ee8271…`；assembly `31184441362` fail `Installed toolchain file is unsafe` / cleanup success、source `31184441306` fail（Desktop/Web/macOS success；Python `744/2/1`；QMD skipped；W01 fail closed）、container `31184441281` no-publish success；engineering product artifacts `[]`；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| third remediation exact candidate | `fail` / `superseded` | exact `2665ec…` / tree `c3cd17…`；source `31258135929` success；assembly `31258135925` fail on Darwin fd-backed uv cwd / cleanup success；container `31258135932` API/MCP success、Web cancelled/no publish；engineering product artifacts `[]`；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| fourth remediation exact candidate | `fail` / `superseded` | exact `c2be665f…` / tree `f90b527b…`；source `31358373316` success；Engineering `31358373320` / job `93362214499` inner-build + cleanup fail；Containers `31358373311` `3/3` success/no publish；engineering product artifacts `[]`；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| fifth remediation exact candidate | `fail` / `superseded` | exact `c04fe9f…` / parent `c2be665f…` / tree `2f8b3ace…`；Desktop source `31454826261` / Python job `93666344561` fixture `EACCES` before product cleanup；W01 evidence downstream fail；Engineering `31454826263` / job `93666344718` fail at framework installation / cleanup success；launcher self-update collision is a high-confidence code/timing attribution, not raw-log proof；Containers `31454826243` success/no publish；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| sixth remediation exact candidate | `fail` / `superseded` | exact `cc6ade1…` / parent `c04fe9f…` / tree `911e91d…`；Desktop source `31460588210` success；Engineering `31460588223` / job `93683139742` policy `67/67` + exact-Git `1/1` passed 后 fail `Reviewed Python installer launcher is unsafe` / cleanup success / later skipped / artifacts `[]`；Containers `31460588212` success/no publish；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| seventh remediation exact candidate | `fail` / `superseded` | exact `aaf3f51…` / parent `cc6ade1…` / tree `60c2c6c…`；Desktop source `31559498106` success；Engineering `31559498116` / job `93998717925` manifest uppercase/single-space literal mismatch primary fail + unbound-source cleanup secondary fail / later skipped / artifacts `[]`；Containers `31559498070` success/no publish；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| eighth remediation exact candidate | `fail` / `superseded` | exact `1533656…` / parent `aaf3f51…` / tree `66779e9…`；Desktop source `31570734560` success；Engineering `31570734636` / job `94031972543` manifest/component checks pass 后 root-owned quarantine canonical `cd` permission fail；cleanup success 未证明 framework quarantine residue absent / later skipped / artifacts `[]` / no App launch；Containers `31570734580` success/no publish；independent pending / activation blocked；[record](evidence/W02/2026-08-07-pr21-remediation.md) |
| ninth exact remediation technical candidate | `not-run` | current worktree / pre-commit；尚无 committed exact head/tree 或 fresh Desktop source/Engineering/Containers Actions；不得复用任一旧 run |
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

1. Draft PR #21 reviewed `8c5fd232…` / tree `785f4656…` 的 latest independent conclusion 是
   `NO-GO`。第一次 remediation `9f7d5d…` / tree `ea8e62…` 已 technical `fail` / `superseded`：
   assembly/source 失败，container 仅 no-publish success。第二次 remediation `9ecf0e…` / tree
   `ee8271…` 也已 technical `fail` / `superseded`：assembly 的 installed-toolchain file 校验和
   source 的两个 Python real-venv tests 失败，container 仍仅 no-publish success。第三次
   `2665ec…` / tree `c3cd17…` source success，但 assembly 因 Darwin fd-backed cwd fail，container
   API/MCP success、Web QEMU stall cancelled。第四次 `c2be665f…` / tree `f90b527b…` 的 source
   与 Containers success，但 Engineering inner build 与 cleanup-only gate 分别失败。第五次
   `c04fe9f…` / tree `2f8b3ace…` 的 Desktop source `31454826261` 因 Python fixture
   `EACCES` 失败，Engineering `31454826263` 在 framework installation 失败但 cleanup
   success，Containers `31454826243` success/no publish；第五次也已 `fail` / `superseded`。
   第六次 `cc6ade1…` / tree `911e91d…` 的 Desktop source `31460588210` success，Engineering
   `31460588223` 在 `Reviewed Python installer launcher is unsafe` fail、cleanup success、later
   skipped、artifacts `[]`，Containers `31460588212` success/no publish；第六次也已 `fail` /
   `superseded`。第七次 `aaf3f51…` / tree `60c2c6c…` 的 Desktop source `31559498106` success，
   Engineering `31559498116` 因 manifest exact-line literal mismatch primary fail，cleanup 因 source
   尚未绑定 secondary fail，Containers `31559498070` success/no publish；第七次也已 `fail` /
   `superseded`。第八次 `1533656…` / tree `66779e9…` 的 Desktop source `31570734560` success，
   Engineering `31570734636` / job `94031972543` 在 manifest/component checks passed 后因
   root-owned quarantine canonical `cd` permission fail；cleanup success 未证明 framework residue
   absent，Containers `31570734580` success/no publish；第八次也已 `fail` / `superseded`。八次
   independent acceptance 均为 `pending`，不改变只绑定旧 reviewed head/tree 的 independent
   `NO-GO`。必须在同一 branch/PR 为第九次 exact candidate 取得 fresh
   source/Engineering/Containers Actions；旧 `310269*`、`311819*`、`311844*`、`312581*`、
   `313583*`、`314548*`、`314605*` 与 `315594*` runs 都不能迁移为 remediation `pass`。
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

1. 在 Draft PR #21 现有 branch 上形成第九次 exact remediation candidate：保留不用
   `actions/setup-python` / 原 full pkg、component-only 17-byte no-op producer/seal 边界；把 locked
   hashes manifest 的真实 uppercase/single-space 整行继续以 `grep -Fxc` + count one 绑定，并把
   cleanup 分成 source-unbound zero-residue 与 source-bound strict source/repo closure。继续先校验
   exact outer pkg，再以唯一 17-byte no-op 重打并
   component-install `Python_Framework.pkg`；隔离旧 root 并确认 target absent 后，仅对
   non-symlink seal，大小写无关清理 cache，再以 Node verifier 绑定 core/fresh exclusions，且在
   verifier 后精确复验/清理 quarantine、首次 framework Python 前完成。运行时 install-reviewed
   只验证 distribution/binding，不安装或
   `sudo`。同时保持 APFS directory-link inventory、sealed-source cleanup ordering、held-cwd、
   producer privatization、Web 双架构、renderer Vite 真实 build、H1 deterministic
   rename/recreate/ABA、provenance drift、publish/rollback/evidence/cleanup failure tests；对同一
   exact head 运行 fresh source、Engineering 与 Containers Actions，再交付独立验收。保持 remote product artifact、
   production trust、tag/Draft/Release 边界不变，不启动 packaged App；
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
