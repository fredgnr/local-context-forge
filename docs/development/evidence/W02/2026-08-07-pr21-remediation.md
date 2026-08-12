# PR #21 independent NO-GO 与 remediation 交接

本记录追加在 [W02 static assembly checkpoint](2026-08-06-08137c7-assembly.md)
之后，保存 Draft PR #21 对旧 exact head 的独立验收结论，并为同一 branch/PR 上的修复建立
不可迁移的起点。本记录按顺序保留第一次与第二次 remediation 技术执行的失败事实；不把任一次
覆盖成下一候选的 `not-run`。旧 checkpoint 文档不回写；其中的 workflow `success` 和当时记录的技术输出仍是
历史事实，但不能证明本记录识别的 Python build scratch lifecycle 安全属性，也不能作为任一
remediation head 的通过证据。

## 失败候选的权威坐标

| 字段 | 值 |
| --- | --- |
| context | `CTX-PR21-NOGO-CURRENT` |
| canonical repository | `fredgnr/local-context-forge` |
| PR | [Draft #21](https://github.com/fredgnr/local-context-forge/pull/21) |
| base / merge-base | `1786255b55dd1a78659ed92235893876175a0722` |
| branch | `agent/w02a-engineering-smoke-boundary` |
| independently reviewed head | `8c5fd23206b671b768fd21d253bf292642f93a51` |
| independently reviewed tree | `785f4656de8a7233b6dd632fe4815976d33468fb` |
| reviewed topology | `26` commits；`54` changed files；`11527` additions / `392` deletions |
| engineering-smoke run / job | [run `31026905444`](https://github.com/fredgnr/local-context-forge/actions/runs/31026905444) / job `92377586784` |
| exact-head source run | [run `31026907916`](https://github.com/fredgnr/local-context-forge/actions/runs/31026907916) |
| container run | [run `31026906777`](https://github.com/fredgnr/local-context-forge/actions/runs/31026906777) |
| remote engineering artifacts | `[]` |
| independent decision | **`NO-GO`** |

<!-- w02-pr21-nogo-authority: context=CTX-PR21-NOGO-CURRENT,base=1786255b55dd1a78659ed92235893876175a0722,merge-base=1786255b55dd1a78659ed92235893876175a0722,reviewed-head=8c5fd23206b671b768fd21d253bf292642f93a51,reviewed-tree=785f4656de8a7233b6dd632fe4815976d33468fb,branch=agent/w02a-engineering-smoke-boundary,commits=26,files=54,additions=11527,deletions=392,assembly-run=31026905444,assembly-job=92377586784,source-run=31026907916,container-run=31026906777,decision=NO-GO -->

## NO-GO finding

`H1 build scratch lifecycle / held dirfd / inode binding / publish / cleanup`
是 High merge blocker：旧 `_create_private_build_root()` 只返回 pathname，没有持有 destination
parent、scratch parent 和 candidate 的 directory descriptor 或生命周期 identity snapshot。
PyInstaller、audit、publish、rollback、evidence preservation 与 final cleanup 随后继续按可重新
绑定的 path 操作。parent/candidate 的 rename → recreate 或 ABA replacement 因而可能让 build、
inventory、post-publish verification 与 cleanup 观察不同 inode；pathname 上的
`shutil.rmtree()` 还可能删除 replacement 或遗留被移走的原目录。

旧 run 的业务 step 虽为 `success`，但没有独立的 held-dirfd/inode lifecycle 或 exact cleanup
门禁；Actions 自身的 post-job cleanup 也不是该安全属性的证据。旧 PR body 中 “every
assembly/audit/cleanup step succeeded” 与 “independent reviews: no blocker” 均不得继续作为
当前结论。

Git provenance 同样不足：旧实现只复核 `HEAD`、porcelain status 与 commit timestamp，未绑定
exact `HEAD^{tree}`、index/worktree/submodule、ignored scratch 生命周期或构建实际读取的 committed
source snapshot；缺少 `LCF_SOURCE_SHA` 时还会回退到 PR 可能使用的 synthetic
`GITHUB_SHA`。check/use/recheck 之间消费临时替换内容后再恢复，不能由末端 clean status 排除。

旧 assembly job 日志实际把 `LCF_SOURCE_SHA` 设为 reviewed head
`8c5fd23206b671b768fd21d253bf292642f93a51`，同时把 `LCF_GITHUB_CONTEXT_SHA` 设为 PR context
`fb3079b851362e2cdb8a6db21c2e071b9b07a842`；两者不是同一对象，后者不得作为 source commit
fallback。job 末尾三条 `Post job cleanup` 属于 setup-python、setup-node 与 checkout action 的 post
steps，不是 Python build scratch exact cleanup 证据。old exact-head Python source job 的可复算结果
是 backend pytest `450` passed、Host Runner `8` tests、demo SDK `3` passed、tools unittest `152`
tests，以及 QMD `10` passed / `1` allowlisted skip；旧 PR body 的 `595 passed, 1 skipped` 聚合不能
由该日志复算，remediation 更新不得保留这个数字。

## remediation candidate threat boundary

以下是 remediation candidate 要证明的有限边界，不是 gate 已通过的声明。前两次技术执行均在
toolchain 安全检查和 source tests 处 fail closed，assembly 的后续 production-input consumers
均跳过，因此不能从设计、cleanup-only 成功或未执行的步骤推导 implementation `pass`。

exact-source bootstrap 的有限 TCB 是 server-reviewed workflow 与 system Git/runtime。sanitized
system Git 将 exact source SHA checkout 到 random、euid-owned、`0700` private root 成功后，
在任何 repo-owned script 首次运行之前，才开始排除主动 same-UID namespace/content writer；
此后 tests、builders、auditors、packager 的 repo-derived inputs 均只能从该 root 消费。private
root 内运行的 exact Git checker 会做 full raw tree/index/worktree/local-metadata post-check，但它是
defense-in-depth，不能追溯证明自身首次加载。

Node seal 分离 deterministic npm installed-content digest 与 run-local inode/time identity snapshot；
它只绑定 exact repo-derived package/lock/source inputs 和 sealed npm toolchain。electron-builder 下载的
base runtime 仍是既有 packager trust boundary，本记录不声称所有 third-party packaging inputs exact，
也不声称在上述明确排除期间抵抗主动 same-UID ABA writer。formal build job 的 shared
Python/renderer provenance consumers 同步加固；formal package/App/credentials、Draft/promotion、
distribution/publish semantics 与 production settings 均未运行或推进。

Python scratch/capability 保证限定在一次 process-level build CLI lifecycle：取消或固定失败后该
进程必须退出，不支持也不声称安全复用同一进程做 same-process retry。已经持有的 scratch capability 上，个别
只读或瞬时 fd syscall 到 Python object store 之间的窄窗口依赖进程退出关闭 fd；这不削弱已实现的
namespace identity 复验、transactional publish/rollback 与 exact cleanup fail-closed 保证，也不扩展为
任意 same-process retry/recovery 语义。

Python outer bootstrap 的 transient roots 只允许出现在 validated `RUNNER_TEMP` 下，固定前缀为
`python-sidecar-toolchain-*` 与 `lcf-python-installer.*`。build step 后的第一个 validation 是
cleanup-only `always()` gate：先验证 `RUNNER_TEMP` 并断言两类前缀均不存在，再检查 repo scratch；
它不依赖 framework interpreter 或 provenance 成功。后续 success-only step 才复验 interpreter 与
五个 provenance keys。bootstrap 自身的 descriptor-relative cleanup 仍是失败路径的主保证，
workflow cleanup-only gate 是独立 fail-closed evidence，而不是 cleanup 的替代物。

Focused Python lifecycle tests 只在 sidecar/renderer/Desktop/static assembly 与 success-only
provenance validation 全部完成后运行，并且是最后一个 repo-code step。该 step 在运行任何 test
Python 前先 `export PYTHONDONTWRITEBYTECODE=1`，并用显式 `python -B` 执行安装入口与 pytest；
其后不再加载任何影响 production artifact 的 repo Python 或 Node。这样 test 安装、pytest cache
或测试态 bytecode 不可能成为后来 production bootstrap/import 的未审计输入。

## 第一次 remediation 技术执行：`fail` / `superseded`

第一次 remediation exact candidate 的坐标和结果必须作为失败历史保留；Buildx action records
不是产品或 engineering artifact，cleanup-only 成功也不改变 assembly job 的失败结论。

| 字段 | 值 |
| --- | --- |
| exact head | `9f7d5d11225517ff5b1643d4bb71983346358ae0` |
| exact tree | `ea8e62e9b76c3270d60135a8633f56db025ad921` |
| committed-source snapshot SHA-256 | `6b44dc785f6f3cd957e35c3eff1857ef55ac07a6fb3a98dcab44601486d2c1e6` |
| renderer lock SHA-256 | `ae4f9bdf4283763a980ee4b21f3fdd844d4de43a0b35fa7086406eddc2ab857f` |
| engineering-smoke run / job | [run `31181911570`](https://github.com/fredgnr/local-context-forge/actions/runs/31181911570) / job `92876982671` |
| exact-head source run | [run `31181911534`](https://github.com/fredgnr/local-context-forge/actions/runs/31181911534) |
| container run | [run `31181911527`](https://github.com/fredgnr/local-context-forge/actions/runs/31181911527) |
| remote engineering product artifacts | `[]` |
| technical result | **`fail`**；第一次 remediation attempt 已 `superseded` |
| independent acceptance | `pending`；没有替代旧 `8c5fd…` head 的 independent `NO-GO` |
| canonical activation | `blocked` |

<!-- w02-pr21-first-remediation-authority: source=9f7d5d11225517ff5b1643d4bb71983346358ae0,tree=ea8e62e9b76c3270d60135a8633f56db025ad921,assembly-run=31181911570,assembly-job=92876982671,source-run=31181911534,container-run=31181911527,result=fail -->

assembly run `31181911570` / job `92876982671` 在 installed toolchain 校验处以固定错误
`Installed toolchain symlink is unsafe` 失败。紧随其后的 cleanup-only gate 成功；success-only
provenance validation、sidecar/renderer/Desktop/static assembly、bundle audit 与 focused Python
lifecycle tests 均跳过，engineering artifacts 列表为 `[]`。因此没有 `.app` inventory/digest，
也没有可迁移到后续 candidate 的 assembly `pass`。

exact-head source run `31181911534` 同样为 `fail`：Python 为 `739` passed / `2` failed /
`1` skipped，两个失败均是 unsafe ownership or mode；Desktop 为 `292` passed / `1` failed，失败
原因是缺少 `web/node_modules/vite`；Web `51/51` success；macOS IPC `49` passed / `1` warning，
job success。W01 aggregate 按合同 fail closed，不能用成功的 Web/macOS 子项抵消 Python/Desktop
失败。

container run `31181911527` 的三个 jobs 为 `3/3` success，但 PR 路径没有 publish：registry login
和 platform verification 跳过，Buildx 的 `push=false`、`load=false`。Buildx records 只是 action
records，不是本 Work 的 product/engineering artifacts，也不能提升 assembly、packaged smoke 或
release gate。

source run 的 W01 failure evidence payload artifact `8995148172` 的 ZIP / inner SHA-256 分别为
`d0fa244c318fd64039eb70618be023103465ab580d9c192b643558d49b2c27aa` /
`0d48fc0ca4b7edab977f31484f14c39cab5a7ecbc7b5299a2d1f2b1c22a86709`；provenance artifact
`8995148811` 的 ZIP / inner SHA-256 分别为
`a43697a8b83737ddda3b3e102a270b299adf6658a2f7d3017ffd93cad2af9c3a` /
`bb5dc6ae465782e220b5bdde2dd309a5c8662255426d4c51a28fc871eced21a4`。两份证据绑定上述
source/tree、run 与 Draft PR #21，明确记录 result `fail`、independent acceptance `pending`、
canonical activation `blocked`；它们不能自我提升或覆写旧 independent `NO-GO`。

## 第二次 remediation 技术执行：`fail` / `superseded`

第二次 remediation exact candidate 修复了第一次 source run 的 Desktop Web-lock/Vite 安装缺口，
但 Python real-venv mode/ownership 合同和 engineering assembly 的 installed-toolchain file 校验仍
fail closed。因此它同样只能追加为失败历史，不能替代旧 independent `NO-GO`，也不能解锁下一阶段。

| 字段 | 值 |
| --- | --- |
| exact head | `9ecf0effaa48a8b010ff46ffb42afc57e0f3d948` |
| exact tree | `ee82712c7874155eba038d1ce05d374416ed34e5` |
| synthetic PR context SHA | `6b1f30254f9627995756ecb75f51d4231849ced9` |
| committed-source snapshot SHA-256 | `9080dd15fe407ab7947b28a58bedec60f8a7422a9245b551a7b065117514d50c` |
| renderer lock SHA-256 | `ae4f9bdf4283763a980ee4b21f3fdd844d4de43a0b35fa7086406eddc2ab857f` |
| engineering-smoke run / job | [run `31184441362`](https://github.com/fredgnr/local-context-forge/actions/runs/31184441362) / job `92885372402` |
| exact-head source run | [run `31184441306`](https://github.com/fredgnr/local-context-forge/actions/runs/31184441306) |
| container run | [run `31184441281`](https://github.com/fredgnr/local-context-forge/actions/runs/31184441281) |
| remote engineering product artifacts | `[]` |
| technical result | **`fail`**；第二次 remediation attempt 已 `superseded` |
| independent acceptance | `pending`；没有替代旧 `8c5fd…` head 的 independent `NO-GO` |
| canonical activation | `blocked` |

<!-- w02-pr21-second-remediation-authority: source=9ecf0effaa48a8b010ff46ffb42afc57e0f3d948,tree=ee82712c7874155eba038d1ce05d374416ed34e5,assembly-run=31184441362,assembly-job=92885372402,source-run=31184441306,container-run=31184441281,result=fail -->

engineering-smoke run `31184441362` / job `92885372402` 在 `Build and audit locked Python
sidecar` 以固定错误 `Installed toolchain file is unsafe` 失败。紧随其后的 cleanup-only gate
成功；success-only provenance、renderer、Desktop profile、static assembly/bundle audit 与 focused
Python lifecycle tests 均跳过，engineering product artifacts 为 `[]`。因此本轮仍没有 `.app`
inventory/digest，也没有 packaged launch/runtime evidence。

exact-head source run `31184441306` 为 `fail`。Desktop `293/293`、Web `51/51`、macOS arm64 IPC
`49` passed / `1` warning 三个 jobs success；Python 为 `744` passed / `2` failed / `1` skipped /
`2` warnings，失败分别是 real-venv exact-cleanup assertion 和 installed-tree
`unsafe ownership or mode`。Python 失败后 QMD setup/source check/version steps 全部 skipped，
`qmd_source` 为空；W01 evidence job 仍按 `always()` 运行并 fail closed。因此成功的 Desktop/Web/
macOS 子项不能把 source aggregate 提升为 `pass`。

source run 的 W01 failure payload artifact `8996169850` 的 ZIP / inner SHA-256 分别为
`29e7f5c0f16edac4afcc3651888bad8994c23afbab9cf5945eb6ed3148c5434a` /
`d8d76efe31b4a6fa0fec233b13bc4e72522af61e27159b29ff365c94966d02f7`；provenance artifact
`8996170497` 的 ZIP / inner SHA-256 分别为
`643f143c27ca019e29660aa28d022e1411433f2a550dedac4b17e3d2c720d879` /
`9e464c4a8dee2743c0e3b9ff5e22f8adf603c56e62a4240a16c51d9b146b8105`。重算值与 Actions
metadata/provenance 互相匹配，并绑定 exact source/tree、synthetic PR context、run 与 Draft PR #21。
payload 明确记录 result `fail`、technical candidate gates `fail`、independent acceptance `pending`、
canonical activation `blocked`，全部 downstream gates 为 `not-run`。

container run `31184441281` 的 api/web/mcp 三个 jobs 为 `3/3` success，但 PR merge-context checkout
不构成 exact-head source evidence。registry login 与 published-platform verification skipped，三个
Buildx jobs 均为 `push=false` / `load=false`，所以没有镜像 publication；自动生成的 `.dockerbuild`
action records 不是 product/engineering artifacts，也不能提升 W02、packaged smoke 或 release gate。

## 第三次 remediation candidate 的 producer 私有化边界：`not-run`

第二次执行证明 subprocess `umask=077` 不是完整的 installed-tree mode 合同：real venv 可以显式复制
或保留来源文件模式，因而仍可能产生 `0640`、`0660` 或 `0775`；`umask` 不会改写显式 `chmod`，也
不能把 regular-file hardlink 变成独立 inode。原 strict seal 对 group/world write、非规范只读 mode
和 `nlink != 1` 的拒绝保持不变，不能为兼容 hosted runner 而放宽。

下一 candidate 在每个 hash-locked producer 退出后、任何 installed tool 被消费前增加
**producer output privatization**。它只在已持有的 random `0700` capability 内按 dirfd、`O_NOFOLLOW`
遍历：普通文件与目录先验证 type/euid/egid/special bits/bounds/identity，再把非 executable file
规范为 `0600`、executable file 与目录规范为 `0700`；symlink 不按 raw mode/uid/gid 修改，仍由紧随
其后的 portable target 与 identity inventory 验证。bootstrap venv 与 final build venv 都必须先完成
该步骤，再进入既有 inventory → read-only chmod → inventory/seal。

对 `nlink > 1` 的 regular file，privatization 不在原 inode 上 `chmod`。只有 alias 本身没有
group/world write 时，才把 bounded bytes 复制到同目录 `O_EXCL` private inode，复核原/新两端
identity、mode、size 与完整 bytes，用 Darwin `RENAME_SWAP` / Linux `RENAME_EXCHANGE` 的
**atomic exchange** 换入，再验证正式路径 `nlink == 1`、删除被换出的旧 alias 并 fsync parent。
group/world-writable hardlink、atomic exchange 不可用、任何 drift 或 special file 都继续 fail closed；
树外 alias 后续变化不能修改已经 materialized 的 sealed inode。第三候选的实现与本地测试不等于
Actions `pass`，其 technical result 在 fresh exact-head source/assembly 完成前仍是 `not-run`。

## 第三次 remediation 技术执行：`fail` / `superseded`

第三次 exact candidate 实现并验证了上一节的 producer output privatization，但 fresh macOS
assembly 暴露了独立的 Darwin fdesc 可移植性缺口；container run 同时暴露 Web arm64 build
在 QEMU 下执行 Node/npm 的阻塞。它仍是失败历史，不得由 source success 或本地后续修复提升。

| 字段 | 值 |
| --- | --- |
| exact head | `2665ec61712fe410608ac50c7a6d44fa35746092` |
| exact tree | `c3cd1706838f7050533e2812dfdcad482aaedde5` |
| engineering-smoke run / job | [run `31258135925`](https://github.com/fredgnr/local-context-forge/actions/runs/31258135925) / job `93104615763` |
| exact-head source run | [run `31258135929`](https://github.com/fredgnr/local-context-forge/actions/runs/31258135929) |
| container run | [run `31258135932`](https://github.com/fredgnr/local-context-forge/actions/runs/31258135932) |
| remote engineering product artifacts | `[]` |
| technical result | **`fail`**；第三次 remediation attempt 已 `superseded` |
| independent acceptance | `pending`；没有替代旧 `8c5fd…` head 的 independent `NO-GO` |
| canonical activation | `blocked` |

<!-- w02-pr21-third-remediation-authority: source=2665ec61712fe410608ac50c7a6d44fa35746092,tree=c3cd1706838f7050533e2812dfdcad482aaedde5,assembly-run=31258135925,assembly-job=93104615763,source-run=31258135929,container-run=31258135932,result=fail -->

engineering-smoke run `31258135925` / job `93104615763` 在 `Build and audit locked Python
sidecar` 失败：outer bootstrap 把 `/dev/fd/<held-source-fd>/backend` 作为 subprocess `cwd`，而
Darwin fdesc 不能把已打开目录 fd 当作可继续遍历的 pathname。固定对外错误为
`Exact uv runtime export failed`。紧随其后的 cleanup-only gate 成功；provenance、renderer、
Desktop profile、static assembly/bundle audit 与 focused lifecycle tests 均 skipped，engineering
product artifacts 为 `[]`。因此没有新的 `.app` inventory/digest 或 packaged launch evidence。

exact-head source run `31258135929` 为 `success`：Python/QMD、Web、Desktop、macOS arm64 IPC 与
W01 exact-head evidence 五个 jobs 均 success。payload artifact `9022014613` 与 provenance artifact
`9022014784` 的 GitHub artifact SHA-256 分别为
`374e3300b2501b340e590f97f80ace41d7f7a36a80671460ace4000401b4950d` 与
`81879840d66d379e16a69d23d2161b645e8d3bb5e6636b8dae7dfa3d48cd134c`，均绑定 exact head
`2665ec…`。source success 不能抵消 assembly failure，也不构成 packaged/physical evidence。

container run `31258135932` 为 `cancelled`。API 与 MCP jobs success；Web 的 target-arm64 Node/npm
builder 在 QEMU 下执行 `npm ci` 时出现 illegal-instruction/retry/stall，并在 120-minute job boundary
取消。三个 PR jobs 的 registry login 与 published-platform verification 均 skipped，API/MCP
Buildx 仍为 `push=false` / `load=false`；两个 `.dockerbuild` records 不是 product/engineering
artifacts。后续本地 portability 修复只有在新的 exact head 完成 fresh Containers Actions 后才能
获得 technical result。

## 解除条件（同一 W02-A implementation stage）

本轮不创建新的 W、Requirement、TODO 或 Validation ID。新的候选必须至少提供：

1. 显式 scratch capability：canonical/euid-owned/`0700`/same-filesystem/exact-empty parent，
   持有 destination/scratch/candidate dirfd，绑定 dev/inode/metadata，并在每个 phase 复验；
2. exact commit/tree 与 committed-source snapshot provenance；不得以 synthetic merge SHA fallback；
3. capability-bound publish、post-publish audit、rollback、old-destination removal、failure evidence
   与 descriptor-relative exact cleanup；identity drift 时拒绝删除 replacement，并以固定脱敏错误失败；
4. rename/recreate/ABA、symlink/broken-symlink、publish/rollback/cleanup/evidence failure、Git tree/source
   drift 的 deterministic adversarial tests，以及 workflow/policy mutation closure；
5. 新 exact head 的 fresh source/assembly Actions、空 engineering artifact 列表和独立验收。

在新的 exact head 被独立接受前，旧 run、checkpoint、inventory、三次 remediation 的失败
payload/provenance 或本记录都不得迁移为新 head
的 `pass`。当前状态固定为：

| 项目 | 当前结论 |
| --- | --- |
| PR #21 first remediation technical attempt | `fail` / `superseded`（绑定 `9f7d5d…` / `ea8e62…` 与 `311819*` runs） |
| PR #21 second remediation technical attempt | `fail` / `superseded`（绑定 `9ecf0e…` / `ee8271…` 与 `311844*` runs） |
| PR #21 third remediation technical attempt | `fail` / `superseded`（绑定 `2665ec…` / `c3cd17…` 与 `312581*` runs） |
| PR #21 next exact remediation technical candidate | `not-run`（local source validation 已完成；等待 fresh exact-head Actions） |
| latest independent acceptance | `NO-GO`（仍绑定旧 `8c5fd…` / `785f46…` head/tree；三次 remediation 均为 `pending`） |
| W02 | `in-progress` |
| `VAL-PACKAGED-SMOKE-001` | `not-run` |
| W10/W11 | `locked` |
| packaged App / bundle sidecar launch | `not-run` |
| public release | `NO-GO` |

三次 remediation 均未启动 packaged `.app`，未从 bundle 启动 sidecar；下一 exact remediation
candidate 尚无 fresh exact-head Actions result。本 Work 不删除 legacy runtime，
不修改 production settings/credentials/trust pins，不创建 tag、engineering product artifact、
Draft Release 或 Release；上文记录的 W01 source-evidence artifacts 与 Buildx action records 不属于
engineering product artifact。

## 第四次 remediation 技术执行：`fail` / `superseded`

第四次 exact candidate 修复了第三次执行的 Darwin held-cwd 和 Web `$BUILDPLATFORM`
blocker；fresh Desktop source 与 Containers 均成功，但 Engineering 在 Python sidecar inner build
与其后的 cleanup-only gate 分别失败。因此这一 head 仍只能作为 append-only 失败历史，不能把
source/container success 迁移成 technical candidate `pass`。

| 字段 | 值 |
| --- | --- |
| exact head | `c2be665f5832c15064cae87c694a782e51351e7c` |
| exact parent | `2665ec61712fe410608ac50c7a6d44fa35746092` |
| exact tree | `f90b527b4de1a422f63c4bfeb01f9c1010e22b7d` |
| base / merge-base | `main@1786255b55dd1a78659ed92235893876175a0722` |
| synthetic PR context SHA | `95bd786d11289d1755086e9d3411469c1f0fe45b` |
| engineering-smoke run / job | [run `31358373320`](https://github.com/fredgnr/local-context-forge/actions/runs/31358373320) / job `93362214499` |
| exact-head source run | [run `31358373316`](https://github.com/fredgnr/local-context-forge/actions/runs/31358373316) |
| container run | [run `31358373311`](https://github.com/fredgnr/local-context-forge/actions/runs/31358373311) |
| remote engineering product artifacts | `[]` |
| technical result | **`fail`**；第四次 remediation attempt 已 `superseded` |
| independent acceptance | `pending`；没有替代旧 `8c5fd…` head 的 independent `NO-GO` |
| canonical activation | `blocked` |

<!-- w02-pr21-fourth-remediation-authority: source=c2be665f5832c15064cae87c694a782e51351e7c,tree=f90b527b4de1a422f63c4bfeb01f9c1010e22b7d,assembly-run=31358373320,assembly-job=93362214499,source-run=31358373316,container-run=31358373311,result=fail -->

Engineering run `31358373320` / job `93362214499` 正确区分 source head/tree 与 synthetic PR
context。policy `62/62` 与 exact-Git test `1/1` 成功；`Build and audit locked Python sidecar`
随后以 `Exact Python sidecar inner build failed (exit=2; category=unclassified)` 失败，紧接的
cleanup-only `always()` gate 也以 exit `1` 失败。日志没有输出 inner fixed error enum，也没有为
cleanup assertion 命名；provenance、renderer、Desktop profile、static assembly/bundle audit 与
focused lifecycle tests 全部 skipped，engineering product artifacts 为 `[]`。

Actions 原始日志直接证明的是 inner `exit=2/category=unclassified` 与随后 cleanup gate `exit=1`；
它没有打印 inner stage、`st_nlink`、cleanup assertion label 或 errno。exact tree、运行平台与当时实现
分别给出以下高置信因果归因；fresh Darwin Actions 仍须以新增的固定分类和真机回归完成实证闭环：

1. `_verify_source_inventory()` 把所有 filesystem 的 directory `st_nlink` 固定为
   `2 + immediate subdirectory count`。Apple APFS reference 把 directory `nchildren` 定义为全部
   directory entries，但没有找到公开 Apple/XNU source 对 `nchildren` 到 POSIX `st_nlink` 的直接
   映射；Darwin/APFS 实测资料支持 `2 + all immediate entries`。exact root 有 `15` 个 directory 与
   `12` 个 non-directory entries，所以旧模型要求 `17`，entries 模型要求 `29`。在该平台和代码
   路径下，最强因果归因是 post-materialization inventory 在 uv、PyInstaller、frozen smoke 和
   publish 之前 fail closed；outer 只识别 launcher 固定行，所以 inner exit `2` 被折叠成
   `unclassified`。新增 Darwin 真机回归将直接观测空目录、普通文件与子目录对 `st_nlink` 的影响。
2. source snapshot 已密封为 `0500`。Darwin 对 directory rename 还要求 source directory 的
   owner-write authorization；旧 cleanup 在 held child fd 仍为 `0500` 时先调用
   `renameatx_np(RENAME_EXCL)`，之后才 `fchmod(0700)`。结合 Apple `rename(2)` 对 write-disabled
   directory 的限制，最强因果归因是该 ordering 使 exact tree cleanup 失败并留下随机后缀 build
   root。lifecycle 状态和 outer cleanup result 排除了 `RUNNER_TEMP` canonical/owner/mode、installer/
   toolchain prefix 与无后缀 scratch residue，因此最后的
   `desktop/generated/python-sidecar-build-*` assertion 是唯一与 observed exit 相容的 gate；这仍是
   从代码与状态作出的归因，不是 raw log 输出的 assertion label。fresh fixed enum 与同时持有 child
   dirfd 的 Darwin cleanup 回归将验证 errno/order；诊断不会列举路径或目录内容。

Desktop source run `31358373316` 的五个 expected jobs 全部 success。Containers run
`31358373311` 的 API/Web/MCP 三个 jobs 全部 success，证明 Web 双架构修复没有回退；PR 路径
registry login 与 published-platform verification 均 skipped，Buildx `push=false`，没有 GHCR
publication。`.dockerbuild` records 仍只是 action records，不是 product/engineering artifacts。

## 第五次 remediation technical candidate：`not-run`

本次 remediation 继续使用同一 Draft PR #21 与
`agent/w02a-engineering-smoke-boundary`，没有创建新 W/Requirement/TODO/Validation ID。candidate
bytes 在 commit 后才获得非自引用的 exact head/tree；该坐标与 fresh run IDs 将写入 Draft PR
body，而不是为回写成功 run ID 再制造 docs-only head。

实现保持原安全边界并增加以下闭环：

- source inventory 只接受**整棵树一致**的 `subdirectories` 或 APFS `entries` link-count 模型；
  混合模型继续 fail closed，name/type/hash/mode/uid/gid/device 与 pre/post fd identity 复验不变；
- held child fd 先恢复为 owner-only `0700`，立即复验原 name 与同一 inode，再执行 no-replace
  quarantine；build root、scratch parent 与 old destination 也统一走 identity-bound quarantine，
  对所有可观察、可注入测试的 rename/recreate/ABA identity drift 均保留 replacement 并 fail closed；
- inner builder 只向 lifecycle owner 创建并显式 allowlist 的 pipe 写一条最多 `128` bytes 的固定
  primary/cleanup enum；outer 严格校验 schema/allowlist，不回显 raw stderr/path/token；
- workflow cleanup-only gate 保持 build 后第一个独立 `always()` gate，并为每个 assertion 输出一个
  固定脱敏 label；success-only provenance 仍与它分离；
- owned external child 统一由 capability owner 启动：child-only `fchdir`、absolute exact target、
  explicit fd allowlist、signal disposition/mask reset、bounded output/deadline、TERM→KILL→reap 与
  descendant absence proof；Git/native/frozen/PyInstaller consumers 绑定 held repository/source/bundle
  descriptors，outer installer/toolchain 另以 private root epoch capability 拒绝 namespace drift。accepted
  threat boundary 仍明确排除 exact checkout 完成后主动同 UID writer；不把 pathname consumer 的最终
  syscall interval夸写为工具直接消费 held regular-file bytes。

本地完整 Python packaging corpus 为 `533 passed / 2 skipped`；两个 skip 分别是 foreign-owner
filesystem capability case 与 Darwin/APFS 真机 case，在当前 Linux 环境 `not-run`。最终 reviewed
bytes 的实际 local gate 记录如下；所有命令均设置 `PYTHONDONTWRITEBYTECODE=1`，除显式 npm cache
override 外使用 repository canonical recipe：

| Gate | 实际命令 | 结果 |
| --- | --- | --- |
| Python sidecar packaging | `make python-sidecar-packaging-test` | exit `0`；collected `535`，`533 passed / 2 skipped` |
| backend full | `cd backend && .venv/bin/pytest`；另以 `-q -rs` 只读复跑取得 skip reason | exit `0`；`797 passed / 3 skipped / 2 warnings`；skip 为 sandbox 禁止 AF_UNIX、filesystem 拒绝 foreign uid、Darwin/APFS-only stat；warnings 为既有 Starlette/httpx deprecation 与 Pydantic forward-reference |
| tools full unittest | `python3 -B -m unittest discover -s tools/tests -p 'test_*.py'` | exit `0`；`207/207` |
| packaged-smoke policy | `make packaged-smoke-policy-check` | exit `0`；semantic checker pass、policy mutations `66/66`、exact-Git `1/1` |
| pre-1 aggregate | `make pre1-work-plan-check` | exit `0`；CI coverage、W01 evidence、pre-1 plan、packaged-smoke policy pass；tools `207/207` |
| individual governance | `backend/.venv/bin/python tools/check_version_sync.py`；`check_markdown_links.py`；`-B tools/check_ci_coverage.py`；`-B tools/check_w01_evidence.py` | exit `0`；version `0.3.0-alpha.1`、Desktop protocols `1.0/1.1`；links `89` files；coverage/W01 pass |
| Web source | `make NPM='npm --cache /tmp/lcf-web-npm-cache-3024e8ed3918' ci-web` | exit `0`；Vitest `7/7` files、`51/51` tests、0 skip；typecheck pass；Vite build `35` modules |
| Containers policy | `backend/.venv/bin/pytest -q tests/backend/test_container_workflow_policy.py` | exit `0`；`3/3`；未运行 Docker/buildx/login/push |
| Desktop source | `make desktop-test desktop-typecheck desktop-build` | exit `0`；Vitest `31/31` files、`286 passed / 7 skipped`；7 skips 均因当前 sandbox AF_UNIX `EPERM`；typecheck/build pass |
| syntax/static | in-memory `compile()` 8 个 modified Python files；PyYAML parse + 每个 workflow `run` block 送入 `bash -n` | exit `0`；Desktop release `19/19` 与 packaged-smoke `10/10` Bash blocks pass；`actionlint` / `shellcheck` 未安装，标为 `not-run` |
| diff/status | `git diff --check`；before/after `git status --short` | exit `0`；同一 `17` 个 tracked modifications，无 staged/untracked drift |

最初两个 Web `npm ci` 尝试因 sandbox 不允许默认 `/root/.npm` cache 而在 tests 前 exit `2`；一次
Desktop test 随后因该不完整 Web dependency 出现 `285 passed / 7 skipped / 1 failed`。改用 task-private
`/tmp` npm cache 完成 canonical Web install 后，表中 Web 与 Desktop recipes 均 fresh pass；这些
environment prerequisite failures 没有被改写成产品 regression，也没有产生 tracked drift。上述 local
source 结果不替代真实 macOS arm64 Actions。
在同一最终 exact head 的 fresh Desktop source、Engineering、Containers 全部成功且 Draft PR body
准确之前，本候选固定为：

| 项目 | 当前结论 |
| --- | --- |
| PR #21 fourth remediation technical attempt | `fail` / `superseded`（绑定 `c2be665f…` / `f90b527b…` 与 `31358373316` / `31358373320` / `31358373311`） |
| PR #21 fifth remediation technical candidate | `not-run`（local regression only；fresh exact-head Actions pending） |
| latest independent acceptance | `NO-GO`（仍绑定旧 `8c5fd…` / `785f46…`）；本候选 `pending` |
| canonical activation | `blocked` |
| W02 | `in-progress` |
| `VAL-PACKAGED-SMOKE-001` | `not-run` |
| W10/W11 | `locked` |
| packaged App / bundle sidecar launch | `not-run` |
| public release | `NO-GO` |

第四次和本次 remediation 均未启动 assembled `.app`，未从 assembled bundle 启动 sidecar，未创建
DMG/ZIP/tag/Draft Release/Release，未发布 GHCR，未读取或修改 production credentials/settings。

## 第五次 remediation 技术执行：`fail` / `superseded`

第五次 exact candidate 的 fresh Desktop source 与 Engineering 均失败，Containers 成功且
PR 路径未 publish。因此该 candidate 必须作为 append-only 失败历史保留；不得用
Containers success、cleanup success 或当前本地修复将其提升为 `pass`。

| 字段 | 值 |
| --- | --- |
| exact head | `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` |
| exact parent | `c2be665f5832c15064cae87c694a782e51351e7c` |
| exact tree | `2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5` |
| engineering-smoke run / job | [run `31454826263`](https://github.com/fredgnr/local-context-forge/actions/runs/31454826263) / job `93666344718` |
| exact-head Desktop source run / Python job | [run `31454826261`](https://github.com/fredgnr/local-context-forge/actions/runs/31454826261) / job `93666344561` |
| container run | [run `31454826243`](https://github.com/fredgnr/local-context-forge/actions/runs/31454826243) |
| technical result | **`fail`**；第五次 remediation attempt 已 `superseded` |
| independent acceptance | `pending`；没有替代旧 `8c5fd…` head 的 independent `NO-GO` |
| canonical activation | `blocked` |

<!-- w02-pr21-fifth-remediation-authority: source=c04fe9fce2bc2f0f4350e080f7f02c44699c975d,parent=c2be665f5832c15064cae87c694a782e51351e7c,tree=2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5,assembly-run=31454826263,assembly-job=93666344718,source-run=31454826261,source-job=93666344561,container-run=31454826243,result=fail -->

Desktop source run `31454826261` 的 Python job `93666344561` 在
`test_remove_tree_restores_owner_write_before_directory_quarantine` fixture 准备期间触发
`EACCES`：测试在 `0500` directory 中创建 `state` fixture 时已失败，尚未调用被测
product cleanup。因此 raw log 直接证明的是 fixture-ordering 失败，不是 product cleanup
regression。W01 exact-head evidence 随后按 fail-closed 合同 downstream 失败；它不能把该
source run 洗绿。

Engineering run `31454826263` / job `93666344718` 在 `Python framework installation`
失败，后续 cleanup step 成功。Actions raw log 直接证明的边界只是该 stage 失败与
cleanup success。exact code path 把当前 `sys.executable` 用作 held launcher，同时调用
`/usr/sbin/installer` 替换同一 locked Python framework；结合运行时序，最强因果归因是
installer 成功替换 launcher pathname 后，post-exit executable identity 复验把该预期
self-update 视为 binding drift。这是高置信代码/时序归因，不是 raw log 直接输出的
binding root cause；日志未记录 launcher 替换前后的 identity 或专用因果 enum。

Containers run `31454826243` 成功，但 PR 路径没有 registry publication。该 success 只属于
container continuity，不能抵消 Desktop source/Engineering failure，也不能提升 W02、
packaged smoke 或 release gate。本记录不在未单独核验 artifact API 的情况下声称
engineering product artifacts 列表。

## 第六次 remediation technical candidate：`not-run`

第六次 candidate 仍在同一 Draft PR #21 / branch 中修复第五次暴露的 fixture ordering
与 installer-launcher transition。它尚未形成可绑定的 committed exact head/tree，也没有
fresh exact-head Desktop source、Engineering 或 Containers Actions；因此不得为它伪造坐标
marker，technical result 必须保持 `not-run`。本轮不创建新 W/Requirement/TODO/
Validation ID。

当前未提交工作树的本地 Linux 回归为：rebind/fixture focused tests `18 passed`；完整 Python
packaging corpus `545 passed / 2 skipped`；完整 backend source suite `809 passed / 3 skipped`；
pre-1 policy/checker corpus `211 tests`；host runner `8 tests`、demo SDK `3 passed`、Markdown links
`89 files` 均通过。这些结果只证明当前本地 bytes 的回归状态，不是 committed exact-head
Actions、macOS framework installer 或 packaged App launch/runtime evidence，不得将第六次
technical result、`VAL-PACKAGED-SMOKE-001` 或 release gate 提升为 `pass`。

本轮本地复核绑定如下；`HEAD` 只是工作树基线，不是第六候选的 committed exact head：

| 字段 | 值 |
| --- | --- |
| local validation date | `2026-08-11` |
| local baseline | `HEAD c04fe9fce2bc2f0f4350e080f7f02c44699c975d` + 当前未提交的 `14` 个 tracked file bytes；无 sixth candidate commit/tree |
| local environment | `Linux 6.18.35 x86_64`；CPython `3.12.13` |
| unavailable boundary | macOS arm64 framework package install、assembled `.app` launch/runtime、fresh exact-head Actions 均为 `not-run` |

实际命令和结果为：

| Gate | 实际命令 | 结果 |
| --- | --- | --- |
| focused fixture/rebind | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q tests/backend/test_python_sidecar_packaging.py -k 'held_executable or installer_rebind or remove_tree_restores_owner_write_before_directory_quarantine or reviewed_python_installer'` | exit `0`；`18 passed / 529 deselected` |
| Python sidecar packaging | `make python-sidecar-packaging-test` | exit `0`；`545 passed / 2 skipped` |
| backend full | `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest` | exit `0`；`809 passed / 3 skipped / 2 warnings` |
| pre-1 aggregate | `make pre1-work-plan-check` | exit `0`；四个 policy/governance checks pass；tools unittest `211/211` |
| MCP compile/import | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m compileall -q mcp/mcp_server`；`PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -c "import mcp_server.client; import mcp_server.server"` | exit `0`；import 产生既有 Pydantic incomplete forward-reference warning |
| Host Runner | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m unittest discover -s host_runner/tests -t .` | exit `0`；`8/8` |
| demo SDK | `cd examples/demo-python-sdk && PYTHONDONTWRITEBYTECODE=1 ../../backend/.venv/bin/python -m pytest` | exit `0`；`3/3` |
| version / Markdown links | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python tools/check_version_sync.py`；`PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python tools/check_markdown_links.py` | exit `0`；version `0.3.0-alpha.1`、Desktop protocols `1.0/1.1`；links `89` files |
| diff/status | `git diff --check`；`git status --short` | exit `0`；恰好上述 `14` 个 tracked modifications，无 staged/untracked files |

| 项目 | 当前结论 |
| --- | --- |
| PR #21 fifth remediation technical attempt | `fail` / `superseded`（绑定 `c04fe9f…` / `2f8b3ace…` 与 `31454826261` / `31454826263` / `31454826243`） |
| PR #21 sixth remediation technical candidate | `not-run`（无 committed exact head/tree；无 fresh exact-head Actions） |
| latest independent acceptance | `NO-GO`（仍只绑定旧 `8c5fd…` / `785f46…`）；fifth/sixth candidates `pending` |
| canonical activation | `blocked` |
| W02 | `in-progress` |
| `VAL-PACKAGED-SMOKE-001` | `not-run` |
| W10/W11 | `locked` |
| packaged App / bundle sidecar launch | `not-run` |
| public release | `NO-GO` |

第五次失败在 assembled App launch/runtime 之前，第六次尚未执行；两者都没有提供
`VAL-PACKAGED-SMOKE-001` 要求的 bundle launch/runtime evidence。旧 independent `NO-GO`
不得被仓库内文本自我提升，W10/W11 继续 locked，public release 继续 `NO-GO`。

## 第六次 remediation 技术执行：`fail` / `superseded`

上一节保留了第六次 candidate 在 commit 之前的 `not-run` 与本地回归计数；这是当时
bytes 的真实历史，本节不回写或删除它。后续 fresh exact-head Actions 已经执行，
Engineering 在 reviewed Python installer launcher 的固定安全校验处 fail closed，所以第六次必须
追加为失败历史，不得用成功的 source/container 子路或之前的 local pass 提升。

| 字段 | 值 |
| --- | --- |
| exact head | `cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` |
| exact parent | `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` |
| exact tree | `911e91d6849266fa75b0efde794ae9b5236f5504` |
| synthetic PR context SHA | `d01c1b4d9ea2c5f77605859a9af8137580b52d8e` |
| committed-source snapshot SHA-256 | `dfed1f824a60ebcfb0e8e9facfb46e5552f412b273cb58979596eb3c26d97884` |
| engineering-smoke run / job | [run `31460588223`](https://github.com/fredgnr/local-context-forge/actions/runs/31460588223) / job `93683139742` |
| exact-head Desktop source run | [run `31460588210`](https://github.com/fredgnr/local-context-forge/actions/runs/31460588210) |
| container run | [run `31460588212`](https://github.com/fredgnr/local-context-forge/actions/runs/31460588212) |
| remote engineering product artifacts | `[]` |
| technical result | **`fail`**；第六次 remediation attempt 已 `superseded` |
| independent acceptance | `pending`；没有替代旧 `8c5fd…` head 的 independent `NO-GO` |
| canonical activation | `blocked` |

<!-- w02-pr21-sixth-remediation-authority: source=cc6ade1113d4753cc6094c5ee23a588dbbe8c18e,parent=c04fe9fce2bc2f0f4350e080f7f02c44699c975d,tree=911e91d6849266fa75b0efde794ae9b5236f5504,assembly-run=31460588223,assembly-job=93683139742,source-run=31460588210,container-run=31460588212,result=fail -->

Engineering run `31460588223` / job `93683139742` 的 packaged-smoke policy `67/67` 与
exact-Git test `1/1` 均成功，然后在 `Python framework installation` 以固定错误
`Reviewed Python installer launcher is unsafe` 失败。紧接的 cleanup-only `always()` step
成功；后续 success-only provenance、renderer、Desktop profile、static assembly/bundle audit 与
focused lifecycle tests 全部 skipped，remote engineering product artifacts 为 `[]`。该边界直接
证明的是 fixed launcher 安全检查失败、cleanup success 和 later stages skipped；没有
assembled App launch/runtime evidence。

Desktop source run `31460588210` 的预期 jobs 全部 success。Containers run
`31460588212` 也成功，但 PR 路径保持 no publish；成功的 source/container 子路不能
抵消 Engineering failure。上述 snapshot digest 只密封该 exact source，不是 package digest。

## 第七次 remediation technical candidate：`not-run`

当前修复仍在同一 Draft PR #21 / branch 上处理第六次暴露的 installer framework
permission/sealing 边界。它还没有 committed exact head/tree，也没有 fresh exact-head
Desktop source、Engineering 或 Containers Actions；因此不为它伪造 authority marker，technical
result 保持 `not-run`。本轮不创建新 W/Requirement/TODO/Validation ID。

对 locked `actions/python-versions` archive 内 exact Python.org pkg 的只读解析已把第六次失败
收窄为真实 payload/postinstall 权限边界；`Versions/3.13/bin/python3.13` 是 `nlink=1` 的 regular
Mach-O，原 component postinstall 会在启动 framework Python 后执行 recursive group/mode
变更。第七候选不放宽 `_held_executable` guard，也不再把 `actions/setup-python` 或原完整
product pkg 当作 reviewed framework producer。当前本地设计先在私有 producer root 中校验
archive/hash manifest/member、exact outer pkg byte digest、Apple installer signature 与 policy；
只有原 signed outer pkg 承担签名来源证明。随后只用系统 `pkgutil --expand` 读取
`Python_Framework.pkg`，逐项绑定 `Bom`、`PackageInfo`、`Payload` 及原 `Scripts/postinstall`
的 locked size/SHA-256/mode，并把唯一 script entry 原子替换为 exact 17-byte
`#!/bin/sh\nexit 0\n`、mode `0755`、SHA-256
`306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb`。只 flatten 该 component，
再 re-expand 复验三份未变 payload metadata/content 与唯一 no-op postinstall；component installer
不执行原 full pkg 的其他 components，也没有 package Python 启动。

安装前以 `-e` / `-L` 双重存在性检查绑定并收紧既有 canonical ancestors，使 dangling
symlink 也在任何 privileged mutation 前 fail closed；若 exact `Versions/3.13` 已存在，则把旧 root
移动到 root-owned 同 parent quarantine，并确认 target absent，避免 installer merge 把旧的
excluded/dynamic 内容带入新树。只安装上述 component 后，installer success 仍不授权运行
framework Python。固定 privileged seal 对 exact root 使用 physical、same-device、no-follow
遍历，只对 regular file/directory 执行 root ownership、ACL removal 与 group/other-write removal，
不通过 symlink 改目标或因两条 reviewed broken links 失败；canonical ancestors 另行绑定 identity、
owner、mode 与无 ACL。随后以大小写无关规则删除任一 component 名为 `__pycache__` 的树和任一
basename 以 `.pyc` / `.pyo` 结尾的文件，并以同样大小写无关的残留检查 fail closed。

在首次 framework Python 启动前，已绑定 identity/SHA-256 的 Node executable 只执行
server-reviewed inline loader；该 loader 以 `O_NOFOLLOW` 同时持有 verifier JS 与 toolchain lock，
逐项校验 owner、mode、`nlink=1`、exact size/SHA-256 与九字段 identity，再从 held verifier bytes
编译、从 held lock bytes 解析，且在关闭 descriptors 前做终态 identity 复验。随后 verifier 以
physical/no-follow 遍历验证 owner/mode/type/link、contained relative symlink、exact 两条 reviewed
broken links 与 cache absence，并按 canonical JSON 重算 core payload digest
`863a6353e58b9c71dc44847051aa582519a66b9347d8c09915ef5254c694bb5d`。它只排除九个 exact
dynamic roots；fresh payload 中 `lib/python3.13/site-packages` 只允许 locked `README.txt`，其余
八个 exclusion roots 必须 absent，故旧安装或任何未列出的额外 path 不能躲进 exclusion。只有
Node core/fresh-exclusion verifier 成功后，才精确复验并删除同 parent quarantine；该 cleanup
成功后才允许首次启动 exact framework Python。运行时命名为
`--install-reviewed-python` 的模式不再安装 package，也不调用 `sudo` / `installer`；它只从私有
root 重验 locked signed distribution bytes、framework seal/core 与 interpreter binding，然后
sidecar build 才能继续。这些当前未提交的第七候选设计与本地 bytes 仍不是 fresh macOS
exact-head Actions authority，也不构成 packaged smoke evidence。

### 第七候选 pre-commit local validation

该记录只绑定 2026-08-11 的本地工作树 bytes。它不是 committed exact-head、macOS Framework
安装、assembled App launch/runtime 或 Actions authority，因此第七候选 technical result 仍为
`not-run`，不能提升 `VAL-PACKAGED-SMOKE-001`、W02、W10/W11 或 release 状态。

| 字段 | 值 |
| --- | --- |
| local baseline | `HEAD cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` + 未提交 `25`-file bytes；无 seventh candidate commit/tree |
| local environment | `Linux 6.18.35 x86_64`；CPython `3.12.13`；Node `v24.14.0`；npm `11.9.0` |
| unavailable boundary | macOS arm64 component install/root seal/pre-Python verifier、assembled `.app` launch/runtime、fresh exact-head Actions 均为 `not-run` |

| Gate | 实际命令 | 结果 |
| --- | --- | --- |
| packaged policy / verifier | `PYTHONDONTWRITEBYTECODE=1 make packaged-smoke-policy-check` | exit `0`；Node verifier `42/42`、policy mutation `80/80`、exact-Git `1/1` |
| Python packaging | `PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' make python-sidecar-packaging-test` | exit `0`；`559 passed / 2 skipped` |
| formal workflow policy | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m pytest -q -p no:cacheprovider tests/backend/test_desktop_release_workflow_policy.py` | exit `0`；`11/11` |
| backend full | `cd backend && PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' .venv/bin/pytest` | exit `0`；`824 passed / 3 skipped / 2 warnings` |
| Desktop engineering consumer | `cd desktop && npm run test:engineering-smoke && npm run typecheck && npm run build` | exit `0`；`76/76`、typecheck/build pass |
| pre-1 governance | `python3 -B tools/check_pre1_work_plan.py`；`python3 -B -m unittest tools.tests.test_check_pre1_work_plan` | exit `0`；direct checker pass、`51/51` |
| workflow/static | `node` + installed `js-yaml` parse two workflows and run `/bin/bash -n` on every `run` block；`python3 -m py_compile`；`node --check`；JSON parse | exit `0`；2 workflows、35 Bash blocks、Python/Node/JSON pass |
| version / Markdown | `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python tools/check_version_sync.py`；`PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python tools/check_markdown_links.py` | exit `0`；version/protocol sync pass；89 files |
| diff/scope | `git diff --check`；`git status --short` | exit `0`；25 个 scoped files，真实 index 为空，无额外未跟踪文件 |

| 项目 | 当前结论 |
| --- | --- |
| PR #21 sixth remediation technical attempt | `fail` / `superseded`（绑定 `cc6ade1…` / parent `c04fe9f…` / tree `911e91d…` 与 `31460588210` / `31460588223` / `31460588212`） |
| PR #21 seventh remediation technical candidate | `not-run`（无 committed exact head/tree；无 fresh exact-head Actions） |
| latest independent acceptance | `NO-GO`（仍只绑定旧 `8c5fd…` / `785f46…`）；sixth/seventh candidates `pending` |
| canonical activation | `blocked` |
| W02 | `in-progress` |
| `VAL-PACKAGED-SMOKE-001` | `not-run` |
| W10/W11 | `locked` |
| packaged App / bundle sidecar launch | `not-run` |
| public release | `NO-GO` |

第六次失败在 assembled App launch/runtime 之前，第七次尚未执行。当前汇总是六次
remediation attempts `fail` / `superseded` 与第七次 exact candidate `not-run`；
`VAL-PACKAGED-SMOKE-001` 仍为 `not-run`，W02 仍 `in-progress`，W10/W11 继续
locked，latest independent 结论仍是旧 reviewed head/tree 的 `NO-GO`，canonical activation
仍 `blocked`，public release 仍 `NO-GO`。
