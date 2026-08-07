# PR #21 independent NO-GO 与 remediation 交接

本记录追加在 [W02 static assembly checkpoint](2026-08-06-08137c7-assembly.md)
之后，保存 Draft PR #21 对旧 exact head 的独立验收结论，并为同一 branch/PR 上的修复建立
不可迁移的起点。本记录继续追加第一次 remediation 技术执行的失败事实；不把它覆盖成下一候选
的 `not-run`。旧 checkpoint 文档不回写；其中的 workflow `success` 和当时记录的技术输出仍是
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

以下是 remediation candidate 要证明的有限边界，不是 gate 已通过的声明。第一次技术执行在
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

在新的 exact head 被独立接受前，旧 run、checkpoint、inventory、第一次 remediation 的失败
payload/provenance 或本记录都不得迁移为新 head
的 `pass`。当前状态固定为：

| 项目 | 当前结论 |
| --- | --- |
| PR #21 first remediation technical attempt | `fail` / `superseded`（绑定 `9f7d5d…` / `ea8e62…` 与 `311819*` runs） |
| PR #21 next exact remediation technical candidate | `not-run`（等待 next exact head 与 fresh Actions） |
| latest independent acceptance | `NO-GO`（仍绑定旧 `8c5fd…` / `785f46…` head/tree；第一次 remediation 为 `pending`） |
| W02 | `in-progress` |
| `VAL-PACKAGED-SMOKE-001` | `not-run` |
| W10/W11 | `locked` |
| packaged App / bundle sidecar launch | `not-run` |
| public release | `NO-GO` |

第一次 remediation 未启动 packaged `.app`，未从 bundle 启动 sidecar；下一 exact remediation
candidate 尚未运行。本 Work 不删除 legacy runtime，
不修改 production settings/credentials/trust pins，不创建 tag、engineering product artifact、
Draft Release 或 Release；上文记录的 W01 source-evidence artifacts 与 Buildx action records 不属于
engineering product artifact。
