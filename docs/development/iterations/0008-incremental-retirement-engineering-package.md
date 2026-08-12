# ITER-0008：增量式 legacy retirement 与工程测试包

- 状态：`in-progress`
- 开始日期：2026-08-05
- 实施基线：`main@1786255b55dd1a78659ed92235893876175a0722` / tree
  `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64`
- 当前分支：`agent/w02a-engineering-smoke-boundary`
- 历史静态 assembly checkpoint：Draft PR #21 exact source
  `08137c7bce5469350b861cef7960e4a0530151bf` / tree
  `d7814ac96136cea33fb7069d9538a4aad8dffa38`；Desktop source CI `31024794734`
  success；engineering-smoke assembly run `31024794972` / job `92370351806` success
- 当前 independent review：PR #21 reviewed source
  `8c5fd23206b671b768fd21d253bf292642f93a51` / tree
  `785f4656de8a7233b6dd632fe4815976d33468fb`，仍是 latest independent `NO-GO`；同一 branch/PR
  第一次 remediation exact `9f7d5d11225517ff5b1643d4bb71983346358ae0` / tree
  `ea8e62e9b76c3270d60135a8633f56db025ad921` technical `fail` / `superseded`；第二次 exact
  `9ecf0effaa48a8b010ff46ffb42afc57e0f3d948` / tree
  `ee82712c7874155eba038d1ce05d374416ed34e5` 同样 technical `fail` / `superseded`；第三次 exact
  `2665ec61712fe410608ac50c7a6d44fa35746092` / tree
  `c3cd1706838f7050533e2812dfdcad482aaedde5` 也为 technical `fail` / `superseded`；第四次 exact
  `c2be665f5832c15064cae87c694a782e51351e7c` / tree
  `f90b527b4de1a422f63c4bfeb01f9c1010e22b7d` 仍为 technical `fail` / `superseded`；第五次 exact
  `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / parent
  `c2be665f5832c15064cae87c694a782e51351e7c` / tree
  `2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5` 也为 technical `fail` / `superseded`；第六次 exact
  `cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` / parent
  `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / tree
  `911e91d6849266fa75b0efde794ae9b5236f5504` 同样 technical `fail` / `superseded`；第七次 exact
  remediation technical candidate `not-run`（无 committed exact head/tree；无 fresh exact-head Actions）
- 依赖：ADR-0016；W01 的 `VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001`、
  `VAL-CI-COVERAGE-001=pass` 已闭环；W10/W11 随后仍依赖 W02 的
  `VAL-PACKAGED-SMOKE-001=pass`
- 替代计划：ITER-0007 的“完整 cutover 后才允许任何删除”执行顺序
- 路线图阶段：Pre-1.0 W02、W10、W11、W03、W13
- 关联需求：REQ-PRE1-SEQUENCING-001、REQ-PACKAGED-SMOKE-001、REQ-LEGACY-SLICE-001、
  REQ-ENGINEERING-PACKAGE-001、REQ-ELECTRON-ONLY-001
- 关联验证：VAL-PACKAGED-SMOKE-001、六个 legacy slice gate、
  VAL-ENGINEERING-PACKAGE-001、VAL-ELECTRON-CUTOVER-001、VAL-LEGACY-ABSENCE-001

## 稳定 ID 闭环

- Requirements：`REQ-PRE1-SEQUENCING-001`、`REQ-PACKAGED-SMOKE-001`、
  `REQ-LEGACY-SLICE-001`、`REQ-ENGINEERING-PACKAGE-001`。
- 本 Work 新增 tasks：`TODO-PRE1-SEQUENCING-001`、`TODO-PACKAGED-SMOKE-001`、
  `TODO-PACK-ENGINEERING-001`、`TODO-LEGACY-REMOVE-PROVIDER-001`。
- 本 Work 新增 validations：`VAL-PRE1-SEQUENCE-001`、`VAL-PACKAGED-SMOKE-001`、
  `VAL-LEGACY-DECOUPLE-001`、`VAL-LEGACY-DEPLOY-001`、
  `VAL-LEGACY-TRANSPORT-001`、`VAL-LEGACY-PROVIDER-001`、
  `VAL-LEGACY-RELEASE-001`、`VAL-LEGACY-DOCS-001`、
  `VAL-ENGINEERING-PACKAGE-001`、`VAL-RELEASE-CONTINUITY-001`。

以上 ID 在 TODO、traceability 与本迭代逐项出现；缩写或“六个 gate”不能替代机器闭环。

## 目标

在不删除用户数据、不改 GitHub production control plane 且不弱化 formal release policy 的
前提下，先建立最小 packaged feedback loop，再逐 slice 删除 unsupported legacy runtime，
然后从 cleaned Electron-only tree 构建完整 engineering test package。最终 cutover/absence
只在 W04–W12 工程物理矩阵完成后运行。

## 计划任务

- [ ] I01（W02）实现独立 non-release packaging mode 和最小 packaged smoke；不创建新的稳定
  task/VAL ID。内部执行阶段为：
  - [ ] engineering-smoke boundary/assembly：旧 static technical run 保留；PR #21 independent
    acceptance `NO-GO`；第一次至第六次 remediation technical attempts 均为 `fail` / `superseded`，
    第七 exact candidate `not-run`。旧 exact Draft head 只构建和审计 macOS arm64
    `.app`，未启动 assembled App；其 pre-pack frozen sidecar staging success 不能证明 held-dirfd/
    inode scratch lifecycle、exact Git tree/source provenance 或 fail-closed cleanup。当前 Work 只在
    同一 branch/PR 修复这些 blocker；见 [旧 assembly evidence](../evidence/W02/2026-08-06-08137c7-assembly.md)
    与 [append-only remediation record](../evidence/W02/2026-08-07-pr21-remediation.md)；
  - [ ] exact-source bootstrap 的有限 TCB 是 server-reviewed workflow 与 system Git/runtime；
    sanitized system Git 把 exact SHA checkout 到 random、euid-owned、`0700` private root 成功后，
    才开始排除主动 same-UID namespace/content writer，并从该 root 运行 repo-owned helper、tests、
    builders 与 consumers。exact Git checker 的 full raw post-check 是 defense-in-depth，不是对自身
    首次加载的追溯证明；npm seal 只声明 repo-derived inputs 与 installed-content digest，既有
    electron-builder/base runtime trust boundary 不在该声明内；
  - [ ] 第七候选的 reviewed framework producer 不调用 `actions/setup-python`，也不安装原完整
    Python.org product pkg。system shell/Node 先校验 locked archive 与原 outer pkg 的 exact bytes、
    Apple signature/policy，再只展开并绑定 `Python_Framework.pkg` 的 `Bom`、`PackageInfo`、
    `Payload` 和原唯一 postinstall；把 postinstall 原子替换为 exact 17-byte locked no-op 后，仅
    flatten/re-expand/install 该 component。安装前隔离旧 `Versions/3.13` 并确认 target absent；
    ancestor/target 存在性同时检查 `-e` 与 `-L`，dangling symlink 在 privileged mutation 前失败；
    安装后先对非 symlink file/directory seal，再大小写无关删除/拒绝 `__pycache__`、`.pyc`、
    `.pyo`，最后由从 O_NOFOLLOW-held verifier/lock bytes 启动的 pre-Python Node verifier 绑定
    core digest、两条 reviewed broken links 与 fresh dynamic exclusions。只有该 verifier 成功后
    才精确复验/删除 quarantine，cleanup 成功后才首次
    运行 framework Python；运行时
    `--install-reviewed-python` 只验证 signed distribution/framework/interpreter binding，不安装且
    不调用 `sudo`。这是尚未运行的本地设计，不是 Actions evidence；
  - [ ] Python scratch/capability 保证限定在一次 process-level build CLI lifecycle；取消或固定
    失败后进程退出且不复用作 same-process retry。已持有 scratch 上瞬时 fd syscall→object store
    的窄窗口依赖退出时关闭 fd；namespace identity、transactional publish/rollback 与 exact
    cleanup 的 fail-closed 保证保持不变；
  - [ ] validated `RUNNER_TEMP` 下固定 `python-sidecar-toolchain-*` 与
    `lcf-python-installer.*` transient roots；bootstrap descriptor-relative cleanup 后，workflow 的
    首个 post-build cleanup-only `always()` gate 先断言两类前缀不存在且不依赖 framework/provenance，
    后续 success-only provenance validation 单独运行；
  - [ ] focused Python lifecycle tests 移到 static assembly/provenance 之后并作为 final repo-code
    step；运行前设置 `PYTHONDONTWRITEBYTECODE=1` 并使用显式 `python -B`；其后不再有 production repo Python load
    或 Node load，使 test 安装、pytest cache 或测试态 bytecode 不会成为后续 production input；
  - [ ] packaged App launch/runtime smoke：六次 remediation 均未启动 bundle，第七 candidate 也尚未运行，
    当前 `not-run`；验证 renderer/preload、private
    UDS health/domain request、quit/no orphan、无 public INET，以及 exercised path 不发现系统
    Python/Node/Git；
  - updater unavailable/no-network，禁止 production trust、tag、upload、Draft/Release；
  - W10/W11 保持 locked，直至完整 `VAL-PACKAGED-SMOKE-001=pass` 经独立验收并在 resulting
    `main` 重跑成功。
- [ ] I02（W10）完成 shared ownership/caller inventory 与解耦 gate。
- [ ] I03（W10）删除 public TCP/CORS/browser HTTP/legacy MCP transport，保留 private UDS 与
  bundled stdio companion；在 exact before/after package 上运行 transport gate。
- [ ] I04（W10）删除 Host Runner/LaunchAgent/spool、direct provider/Ollama/Windows helper，
  保留 Main-owned Codex/Cursor attempts；运行 provider gate。
- [ ] I05（W11）删除 Docker/Compose/Nginx/legacy install 与 operations surface；运行 deploy gate。
- [ ] I06（W11）删除 container CI/GHCR publish/tag coupling，保留 formal desktop release safety
  chain 和历史 GHCR package；运行 release-surface gate。
- [ ] I07（W11）删除 legacy env/config/tests/Make targets/active docs，保留 ADR/iteration/evidence
  历史；运行 docs gate。
- [ ] I08（W03）从 cleaned tree 构建完整 engineering test package，记录 exact inventory/digest。
- [ ] I09（W13）在 W04–W12 后从 final commit 重建同一工程包，运行完整 cutover 与 aggregate
  absence；在 checkpoint 前冻结 formal continuity verifier/allowlist/schema；只在两者通过后
  解锁 W14。

## 当前验证日志

| 验证/阶段 | 结果 | 坐标 | 说明 |
| --- | --- | --- | --- |
| W01 entry prerequisites | `pass` | accepted final `36885e04df09c4789d8ec3c9dc5c5e78a381a634`；resulting `main@1786255b55dd1a78659ed92235893876175a0722`；run `30986208251` | [W02 entry record](../evidence/W02/2026-08-05-entry.md)；历史 W01 JSON 保持原样 |
| W02 historical boundary/assembly source | technical `pass`（historical Draft exact-head substage） | `08137c7bce5469350b861cef7960e4a0530151bf` / tree `d7814ac96136cea33fb7069d9538a4aad8dffa38`；source run `31024794734` | config、manifest、staging/audit、policy/workflow 与 source tests 当时成功；不能迁移到后来 reviewed head 或 remediation |
| historical engineering-smoke `.app` static assembly / bundle audit | technical `pass` | [run `31024794972` / job `92370351806`](https://github.com/fredgnr/local-context-forge/actions/runs/31024794972/job/92370351806) | inventory `879` / native `78` / SHA-256 `7fcdb699ad367e7c7da28a074694c6fe8a0a67b54829173894d311de4f6ffe5c`；remote artifacts empty；[immutable evidence](../evidence/W02/2026-08-06-08137c7-assembly.md) |
| PR #21 reviewed candidate independent acceptance | `NO-GO` | `8c5fd23206b671b768fd21d253bf292642f93a51` / tree `785f4656de8a7233b6dd632fe4815976d33468fb` | H1 scratch lifecycle/Git provenance/cleanup blocker；[append-only record](../evidence/W02/2026-08-07-pr21-remediation.md) |
| PR #21 first remediation exact candidate | `fail` / `superseded` | `9f7d5d11225517ff5b1643d4bb71983346358ae0` / tree `ea8e62e9b76c3270d60135a8633f56db025ad921`；source snapshot `6b44dc785f6f3cd957e35c3eff1857ef55ac07a6fb3a98dcab44601486d2c1e6`；renderer lock `ae4f9bdf4283763a980ee4b21f3fdd844d4de43a0b35fa7086406eddc2ab857f` | assembly `31181911570` / job `92876982671` fail `Installed toolchain symlink is unsafe`；cleanup-only success，later stages skipped，engineering product artifacts `[]`；source `31181911534` fail；container `31181911527` `3/3` success/no publish；independent pending，activation blocked；[failure record](../evidence/W02/2026-08-07-pr21-remediation.md) |
| PR #21 second remediation exact candidate | `fail` / `superseded` | `9ecf0effaa48a8b010ff46ffb42afc57e0f3d948` / tree `ee82712c7874155eba038d1ce05d374416ed34e5`；source snapshot `9080dd15fe407ab7947b28a58bedec60f8a7422a9245b551a7b065117514d50c`；renderer lock `ae4f9bdf4283763a980ee4b21f3fdd844d4de43a0b35fa7086406eddc2ab857f` | assembly `31184441362` / job `92885372402` fail `Installed toolchain file is unsafe`；cleanup-only success，later stages skipped，engineering product artifacts `[]`；source `31184441306` fail（Desktop/Web/macOS success，Python `744` pass / `2` fail / `1` skip，QMD skipped，W01 fail closed）；container `31184441281` `3/3` success/no publish；independent pending，activation blocked；[failure record](../evidence/W02/2026-08-07-pr21-remediation.md) |
| PR #21 third remediation exact candidate | `fail` / `superseded` | `2665ec61712fe410608ac50c7a6d44fa35746092` / tree `c3cd1706838f7050533e2812dfdcad482aaedde5` | assembly `31258135925` / job `93104615763` fail at Darwin fd-backed uv cwd；cleanup-only success，later stages skipped，engineering product artifacts `[]`；source `31258135929` all five jobs success；container `31258135932` cancelled（API/MCP success、Web QEMU Node/npm stall，no publish）；independent pending，activation blocked；[failure record](../evidence/W02/2026-08-07-pr21-remediation.md) |
| PR #21 fourth remediation exact candidate | `fail` / `superseded` | `c2be665f5832c15064cae87c694a782e51351e7c` / tree `f90b527b4de1a422f63c4bfeb01f9c1010e22b7d` | Engineering `31358373320` / job `93362214499` fail at inner build and cleanup-only gate，later stages skipped，engineering product artifacts `[]`；source `31358373316` all five jobs success；Containers `31358373311` API/Web/MCP `3/3` success/no publish；independent pending，activation blocked；[failure record](../evidence/W02/2026-08-07-pr21-remediation.md) |
| PR #21 fifth remediation exact candidate | `fail` / `superseded` | `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / parent `c2be665f5832c15064cae87c694a782e51351e7c` / tree `2f8b3aceb4caa2d71537cd51c3b3b985c55a3db5` | Desktop source `31454826261` / Python job `93666344561` fixture `EACCES` before product cleanup，W01 evidence downstream fail；Engineering `31454826263` / job `93666344718` fail at framework installation，cleanup success；launcher self-update collision 是高置信代码/时序归因，非 raw-log proof；Containers `31454826243` success/no publish；independent pending，activation blocked；[failure record](../evidence/W02/2026-08-07-pr21-remediation.md) |
| historical sixth pre-commit candidate state | `not-run` | 当时尚无 committed exact head/tree 或 fresh exact-head Actions | first through fifth attempts remained failed/superseded history；该 append-only pre-commit 状态不因后续执行而删除 |
| historical sixth pre-commit local validation | local `pass` / 当时 exact-head macOS `not-run` | `2026-08-11`；`Linux 6.18.35 x86_64` / CPython `3.12.13`；`HEAD c04fe9f…` + 未提交 `14`-file bytes；当时无 commit/tree/Actions 坐标 | rebind/fixture focused `18 passed`；Python packaging `545 passed / 2 skipped`；backend `809 passed / 3 skipped`；pre-1 checker/tools `211 tests`；host runner `8 tests`、demo SDK `3 passed`、links `89 files`、compile/import/version/diff checks pass；exact commands/results 见 [append-only evidence](../evidence/W02/2026-08-07-pr21-remediation.md)；只证明当时本地 bytes，不抵消后续 sixth Actions failure，也不提升 `VAL-PACKAGED-SMOKE-001` 或 release gate |
| PR #21 sixth remediation exact candidate | `fail` / `superseded` | `cc6ade1113d4753cc6094c5ee23a588dbbe8c18e` / parent `c04fe9fce2bc2f0f4350e080f7f02c44699c975d` / tree `911e91d6849266fa75b0efde794ae9b5236f5504`；context `d01c1b4d9ea2c5f77605859a9af8137580b52d8e`；source snapshot `dfed1f824a60ebcfb0e8e9facfb46e5552f412b273cb58979596eb3c26d97884` | Desktop source `31460588210` success；Engineering `31460588223` / job `93683139742` policy `67/67` + exact-Git `1/1` passed 后 fail `Reviewed Python installer launcher is unsafe`，cleanup success、later stages skipped、artifacts `[]`；Containers `31460588212` success/no publish；independent pending，activation blocked；[failure record](../evidence/W02/2026-08-07-pr21-remediation.md) |
| PR #21 seventh exact remediation technical candidate | `not-run` | 尚无 committed exact head/tree 或 fresh exact-head Actions | component-only 17-byte no-op → fresh root → non-symlink seal/cache cleanup → pre-Python Node core/fresh-exclusion verification → quarantine cleanup 是本地设计；first through sixth attempts remain failed/superseded history；no run or evidence may be reused |
| PR #21 seventh pre-commit local validation | local `pass` / exact-head macOS `not-run` | `2026-08-11`；`Linux 6.18.35 x86_64` / CPython `3.12.13` / Node `v24.14.0`；`HEAD cc6ade1…` + 未提交 `25`-file bytes；无 seventh commit/tree/Actions | verifier `42/42`；policy mutation `80/80` + exact-Git `1/1`；Python packaging `559/2`；formal workflow `11/11`；backend `824/3/2 warnings`；Desktop engineering `76/76` + typecheck/build；pre-1 `51/51`；2 workflows/35 Bash blocks、version/89 links/diff pass；只证明本地 bytes，不提升 technical、packaged 或 release gate；exact commands 见 [append-only evidence](../evidence/W02/2026-08-07-pr21-remediation.md) |
| portable inventory/cleanup regressions；Darwin-only evidence | historical portable `pass` / Darwin-only `not-run` | fifth pre-commit Linux validation；当时无 fresh exact-head Actions result | Python sidecar packaging `533/2`；backend `797/3/2 warnings`；tools `207/207`；policy `66/66` + exact-Git `1/1`；Web `51/51`、Containers policy `3/3`、Desktop `286/7`；typecheck/build、links `89` files、version/coverage/W01、compile/YAML/Bash/diff checks pass。skips 分别绑定 sandbox AF_UNIX、foreign uid 与 Darwin/APFS；该结果在 Actions 执行前只能让当时的 fifth candidate 保持 `not-run`，不能抵消后续 fifth Actions failure，也不改变 `VAL-PACKAGED-SMOKE-001` 的 `not-run`。 |
| historical pre-pack frozen sidecar staging smoke | technical `pass` | old assembly job build step | 只证明旧 sidecar build/staging；assembled `.app` 未启动，sidecar 未从 bundle 启动；不能证明 remediation |
| packaged App launch/runtime smoke | `not-run` | assembled macOS arm64 App required | renderer/preload、bundle-owned sidecar/UDS、quit/no-orphan、listener 与 packaged PATH trap 未运行 |
| `VAL-PACKAGED-SMOKE-001` | `not-run` | packaged App launch/runtime | 本 Work 明确不启动 packaged App |
| W10/W11 six slice gates | `not-run` | exact before/after packages | W10/W11 locked；本 Work 不删除 legacy runtime |
| public release | `not-run` / `NO-GO` | W14–W16 | 不改 settings/credentials/pins，不创建 tag/upload/Draft/Release |

## 当前 owned paths

- engineering-smoke assembly：`.github/workflows/packaged-smoke.yml`、
  `desktop/electron-builder.smoke.yml`、`desktop/scripts/{packagingAuditCommon,prepareEngineeringSmoke,beforePackEngineeringSmoke,afterPackEngineeringSmoke,auditEngineeringSmokeBundle}.cjs`、
  `runtime/engineering-smoke-manifest.schema.json`、对应 Desktop tests；
- shared exact provenance/build boundary：`.github/workflows/desktop-release.yml` 的 formal build job、
  `tools/{check_exact_git_provenance.py,exact_node_install.cjs,verify_reviewed_python_framework.cjs,bootstrap_python_sidecar.py,build_python_sidecar.py,audit_python_sidecar.py}`、
  `desktop/scripts/buildEngineeringSmokeEntrypoints.cjs`、
  `web/scripts/buildEngineeringRenderer.cjs`、
  `desktop/scripts/{stageRenderer,auditRenderer,beforePack,prepareRelease,resealPackagedRuntimes}.cjs`、
  `runtime/{engineering-smoke,renderer-build,python-sidecar-build-manifest}.schema.json`、对应真实
  Python/Desktop/renderer tests；formal Draft/promotion 与 production distribution/publish 仍不在本
  Work 的执行范围；
- engineering-only runtime disposition：`desktop/src/{contracts,main/distribution,main/index,main/updateClient}.ts`
  与 `web/src/desktopBridge.ts`；formal/default distribution 保持原有 fail-closed 语义；
- fail-closed policy：`tools/check_packaged_smoke_policy.py` 与对应 tests；
- legacy Web container portability：`web/Dockerfile`、`.github/workflows/container-images.yml` 与
  `tests/backend/test_container_workflow_policy.py`；只修复跨架构 build stage 与 exact checkout，
  不改变 PR no-login/no-push、正式 platforms 或 W11 ownership；
- source staging 修复：`runtime/version.json`、`tools/check_version_sync.py`、
  `desktop/scripts/stageRenderer.cjs` 与对应 tests；
- governance/evidence：`docs/development/{todo,status,traceability,work-plan}.md`、本迭代、R13、
  iteration/evidence indexes、`docs/development/evidence/W02/**`（包括 append-only PR #21 NO-GO
  remediation record）、
  `tools/check_pre1_work_plan.py` 与对应 tests。
- build entry/ignore：`Makefile`、`desktop/package.json`、`.gitignore`。

生成的 sidecar、renderer、`.app`、bundle audit 和 `release-smoke/` 不入库，也不上传 Actions
artifact；本 Work 不写 production trust material。

## 每个 slice 的退出门禁

采用 [work plan 的通用模板](../work-plan.md#slice-通用模板)。任何 slice 都不能借用其他
slice 或删除前 package 的 evidence；任何 shared owner、external side effect 或 protected path
不明确时必须停止。

## 迭代退出

- W02、W10、W11、W03 的各 gate 有 commit/digest-bound evidence；
- W04–W12 的完整工程物理矩阵已在 cleaned package 上完成；
- final rebuilt bytes 同时通过 `VAL-ELECTRON-CUTOVER-001` 与
  `VAL-LEGACY-ABSENCE-001`；
- 用户数据、外部 assets 和历史 evidence 未修改；
- production GitHub controls、credentials、trust pins、tag、Draft、promotion 和 Release 仍未被
  本迭代创建或改变。

通过本迭代只解锁 W14；不等于 formal release ready。W15/W16 仍须通过
`VAL-RELEASE-CONTINUITY-001`，并在 exact Draft digest 重跑完整 cutover/absence。
