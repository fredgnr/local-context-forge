# PR #21 independent NO-GO 与 remediation 交接

本记录追加在 [W02 static assembly checkpoint](2026-08-06-08137c7-assembly.md)
之后，保存 Draft PR #21 对旧 exact head 的独立验收结论，并为同一 branch/PR 上的修复建立
不可迁移的起点。旧 checkpoint 文档不回写；其中的 workflow `success` 和当时记录的技术输出
仍是历史事实，但不能证明本记录识别的 Python build scratch lifecycle 安全属性，也不能作为
remediation 后新 head 的通过证据。

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

## remediation threat boundary

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

在新的 exact head 被独立接受前，旧 run、checkpoint、inventory 或本记录都不得迁移为新 head
的 `pass`。当前状态固定为：

| 项目 | 当前结论 |
| --- | --- |
| PR #21 remediation technical candidate | `not-run`（等待新 exact head 与 fresh Actions） |
| independent acceptance | `NO-GO`（绑定上述旧 head/tree） |
| W02 | `in-progress` |
| `VAL-PACKAGED-SMOKE-001` | `not-run` |
| W10/W11 | `locked` |
| packaged App / bundle sidecar launch | `not-run` |
| public release | `NO-GO` |

本 remediation 不启动 packaged `.app`，不从 bundle 启动 sidecar，不删除 legacy runtime，
不修改 production settings/credentials/trust pins，不创建 tag、artifact、Draft 或 Release。
