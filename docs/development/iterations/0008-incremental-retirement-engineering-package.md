# ITER-0008：增量式 legacy retirement 与工程测试包

- 状态：`in-progress`
- 开始日期：2026-08-05
- 实施基线：`main@1786255b55dd1a78659ed92235893876175a0722` / tree
  `1b9f3a34847fd3acc8b7f3a31ff19332d5328b64`
- 当前分支：`agent/w02a-engineering-smoke-boundary`
- 当前静态 assembly checkpoint：Draft PR #21 exact source
  `08137c7bce5469350b861cef7960e4a0530151bf` / tree
  `d7814ac96136cea33fb7069d9538a4aad8dffa38`；Desktop source CI `31024794734`
  success；engineering-smoke assembly run `31024794972` / job `92370351806` success
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
  - [x] engineering-smoke boundary/assembly：本 Work，static assembly/bundle audit substage `pass`；
    exact Draft head 上只构建和审计 macOS arm64 `.app`，不启动 assembled App；pre-pack frozen
    sidecar staging smoke 已成功，但没有从 bundle 启动 sidecar，不把 assembly/staging 当成
    packaged runtime smoke；见 [assembly evidence](../evidence/W02/2026-08-06-08137c7-assembly.md)；
  - [ ] packaged App launch/runtime smoke：后续 Work，`not-run`；验证 renderer/preload、private
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
| W02 boundary/assembly source | `pass`（Draft exact-head substage） | `08137c7bce5469350b861cef7960e4a0530151bf` / tree `d7814ac96136cea33fb7069d9538a4aad8dffa38`；source run `31024794734` | 独立 config、manifest、staging/audit、policy/workflow 与 source tests 成功；PR #21 仍是 Draft |
| engineering-smoke `.app` static assembly / bundle audit | `pass` | [run `31024794972` / job `92370351806`](https://github.com/fredgnr/local-context-forge/actions/runs/31024794972/job/92370351806) | inventory `879` / native `78` / SHA-256 `7fcdb699ad367e7c7da28a074694c6fe8a0a67b54829173894d311de4f6ffe5c`；remote artifacts empty；[evidence](../evidence/W02/2026-08-06-08137c7-assembly.md) |
| pre-pack frozen sidecar staging smoke | `pass` | assembly job build step | 只证明 sidecar build/staging；assembled `.app` 未启动，sidecar 未从 bundle 启动 |
| packaged App launch/runtime smoke | `not-run` | assembled macOS arm64 App required | renderer/preload、bundle-owned sidecar/UDS、quit/no-orphan、listener 与 packaged PATH trap 未运行 |
| `VAL-PACKAGED-SMOKE-001` | `not-run` | packaged App launch/runtime | 本 Work 明确不启动 packaged App |
| W10/W11 six slice gates | `not-run` | exact before/after packages | W10/W11 locked；本 Work 不删除 legacy runtime |
| public release | `not-run` / `NO-GO` | W14–W16 | 不改 settings/credentials/pins，不创建 tag/upload/Draft/Release |

## 当前 owned paths

- engineering-smoke assembly：`.github/workflows/packaged-smoke.yml`、
  `desktop/electron-builder.smoke.yml`、`desktop/scripts/{packagingAuditCommon,prepareEngineeringSmoke,beforePackEngineeringSmoke,afterPackEngineeringSmoke,auditEngineeringSmokeBundle}.cjs`、
  `runtime/engineering-smoke-manifest.schema.json`、对应 Desktop tests；
- engineering-only runtime disposition：`desktop/src/{contracts,main/distribution,main/index,main/updateClient}.ts`
  与 `web/src/desktopBridge.ts`；formal/default distribution 保持原有 fail-closed 语义；
- fail-closed policy：`tools/check_packaged_smoke_policy.py` 与对应 tests；
- source staging 修复：`runtime/version.json`、`tools/{build_python_sidecar,check_version_sync}.py`、
  `desktop/scripts/stageRenderer.cjs` 与对应 tests；
- governance/evidence：`docs/development/{todo,status,traceability,work-plan}.md`、本迭代、R13、
  iteration/evidence indexes、`docs/development/evidence/W02/**`、
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
