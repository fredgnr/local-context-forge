# ITER-0008：增量式 legacy retirement 与工程测试包

- 状态：`planned`
- 依赖：ADR-0016；W01 的 `VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001`、
  `VAL-CI-COVERAGE-001=pass`；随后 W02 的 `VAL-PACKAGED-SMOKE-001=pass`
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

- [ ] I01（W02）实现独立 non-release packaging mode 和最小 packaged smoke；验证 exercised
  path 不发现系统 Python/Node/Git；updater unavailable/no-network，禁止 production trust、tag、
  upload、Draft/Release。
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
