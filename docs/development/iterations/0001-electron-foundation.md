# ITER-0001：Electron foundation

- 状态：`in-progress`
- 开始日期：2026-07-30
- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 开发分支：`agent/electron-desktop-foundation`
- 路线图：[P0–P7](../roadmap.md)
- 追踪矩阵：[traceability](../traceability.md)

## 本轮目标

建立 macOS Apple Silicon Electron all-in-one 的治理、版本与源码模式纵切：React renderer
只能经类型化 preload 调用 Electron Main，Main 再经私有 UDS 调用 Python sidecar。保留现有
Docker 路径。本轮只验证源码级边界，不把它表述为已打包、可安装或可更新的桌面发行版。

## Scope

本轮包含：

- 根 `AGENTS.md`、分层文档索引、项目 skills、ADR 与证据链；
- 单一产品/协议版本 manifest 和同步检查；
- React renderer、preload 与 Electron Main 的最小桌面骨架；
- 自定义 `lcf://app`、严格 CSP、导航/权限拒绝和类型化 route allowlist；
- 源码模式 Python sidecar、UDS + 每次启动令牌、握手、超时和进程恢复；
- renderer bridge 的桌面/浏览器双 transport 与 fail-closed 负向测试；
- 不读取 release secrets 的源码测试 CI；
- 文档、验证证据和后续迭代边界。

本轮不包含：

- PyInstaller `onedir`、内置 Node 22/QMD worker 或 packaged sidecar 回归；
- CLI provider preflight、MCP packaged contract、模型下载或旧数据迁移；
- DMG、签名、Release、更新 feed 或物理 Mac 门禁；
- Intel macOS、Windows 或 Linux 桌面发行；
- notarization、hardened runtime 或 Mac App Store；
- 多用户/远程服务暴露；
- 删除 Docker、Compose、原安装器或旧文档；
- 与 Electron 迁移无关的重构、依赖升级或产品功能扩张。

## 已接受决策

| 决策 | 记录 | 实现状态 |
| --- | --- | --- |
| Main 为信任边界；Python 与 Node worker 分离 | [ADR-0001](../../adr/0001-electron-python-sidecar-boundary.md) | `planned` |
| sidecar/worker 使用私有 UDS + 每次启动令牌 | [ADR-0002](../../adr/0002-uds-startup-token-protocol.md) | `planned` |
| DMG、自签名、受保护发布与更新 fallback | [ADR-0003](../../adr/0003-macos-release-signing-update-policy.md) | `planned` |
| macOS 路径、按需模型与可回滚旧数据迁移 | [ADR-0004](../../adr/0004-runtime-paths-legacy-data-migration.md) | `planned` |

## 任务

- [x] **T01 治理骨架**：建立根规则、文档索引、路线图、追踪矩阵、初始 ADR 和两个项目 skill；
  通过 VAL-GOV-001/002 后勾选。
- [ ] **T02 Electron 信任边界**：实现 Main/preload/renderer 骨架和类型化 IPC。
- [ ] **T03 本地协议纵切**：实现源码模式 UDS、每进程独立启动令牌、握手、停止和手动恢复。
- [ ] **T04 Renderer 适配**：桌面 bridge fail closed，浏览器 transport 保持兼容，清除 CSP
  不允许的 inline style，并阻止桌面 Markdown 外链。
- [ ] **T05 契约与 CI**：同步产品/协议版本，添加 source-mode tests 和无 secret 的 PR CI。
- [ ] **T06 收口与发布**：全量回归、独立安全审查、更新证据和变更清单，发布 Draft PR。

## 验收

- [ ] 每项硬约束都能由 `REQ -> ADR -> task -> path -> VAL -> evidence` 追踪。
- [ ] 源码级负向测试证明 renderer 不能直接访问 Node、文件、子进程、令牌、socket 或 updater。
- [ ] Main 只接受可信 frame、版本化 channel 和精确 API allowlist；`/api/admin/*` 被拒绝。
- [ ] UDS 目录/socket 权限、令牌、launch ID、协议、request ID、deadline 与 payload 上限有测试。
- [ ] 现有 Web/API/Host Runner 回归通过，browser/Docker transport 不变。
- [ ] 普通 CI 只需 `contents: read`，且不引用 release Environment 或 secret。
- [ ] packaged/DMG/签名/更新/迁移门禁保持 `not-run`，并链接到后续迭代。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| VAL-GOV-001 | `pass` | 2026-07-30；working tree on `5fce306` | Python 扫描仓库 Markdown 相对链接目标 | 全部目标存在 |
| VAL-GOV-002 | `pass` | 2026-07-30；working tree on `5fce306` | `quick_validate.py` 分别检查两个 skill；reference 行数检查 | 两个 skill 均 valid；references 均少于 100 行 |
| VAL-P1-SOURCE-001 | `not-run` | — | Electron/Web/Python source tests、typecheck、build | 实现进行中 |
| VAL-P1-REGRESSION-001 | `not-run` | — | Web/API/Host Runner 全量回归 | 实现进行中 |
| VAL-CI-001 | `not-run` | — | workflow 静态审计和 Draft PR checks | workflow 尚未创建 |
| VAL-TRUST-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-PY-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-QMD-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-IPC-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-CLI-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-MCP-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-INSTALL-001 | `not-run` | — | 见追踪矩阵 | 尚无 DMG |
| VAL-MODEL-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-RELEASE-001 | `not-run` | — | 见追踪矩阵 | 尚无 release |
| VAL-SECRET-001 | `not-run` | — | 见追踪矩阵 | 尚无 release workflow |
| VAL-UPDATE-001 | `not-run` | — | 物理 0.0.1 → 0.0.2 | 尚未实现；阻断更新声明 |
| VAL-DATA-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-LEGACY-001 | `not-run` | — | 见追踪矩阵 | 尚未执行迁移演练 |

## 风险与缓解

| 风险 | 影响 | 缓解/回滚点 |
| --- | --- | --- |
| 自签名且未 notarize | Gatekeeper 提示与用户信任下降 | 明确披露、固定发布来源与更新公钥；保留手动 DMG |
| 无 hardened runtime | 降低进程级平台加固 | 收紧 renderer/IPC/子进程边界；不得宣称等同 notarized 应用 |
| PyInstaller 隐式依赖遗漏 | 打包后功能缺失 | 对 `onedir` 运行回归和资源清单审计 |
| QMD/Node native 兼容 | arm64 worker 启动或索引失败 | 固定 Node 22 与依赖；干净机 contract/smoke |
| UDS 路径、权限或 stale socket | 启动失败或本机同用户注入 | 短路径、0700 目录、令牌、owner/symlink 检查、每次启动清理 |
| 模型下载中断/篡改 | 磁盘浪费或加载不可信权重 | partial 文件、完整性校验、原子 rename、显式清理 |
| 旧数据模式漂移 | 丢失、重复或无法回滚 | 只读盘点、备份、staging、journal、原目录不改写 |
| 自动更新在自签名环境失效 | 用户停留旧版本 | G6 实机阻断；失败则校验后下载并打开 DMG |
| 公开仓库 secret 泄漏 | 签名/更新供应链受损 | protected Environment、审批、fork/PR secret 负向验证 |
| 过早删除 Docker | 现有用户无恢复路径 | legacy 保留至 P7 和独立 ADR |

## 迭代修订

| 日期 | 修订 | 原因 |
| --- | --- | --- |
| 2026-07-30 | 把 packaged runtimes、数据/模型、DMG、更新和 legacy 退出拆到 ITER-0002–0006 | 让源码纵切与只能在 macOS/真实产物上完成的门禁分别审查，避免一次 PR 产生虚假完成声明 |

## 变更清单

当前治理变更：

- `AGENTS.md`
- `docs/README.md`
- `docs/development/README.md`
- `docs/development/roadmap.md`
- `docs/development/traceability.md`
- `docs/development/iterations/0001-electron-foundation.md`
- `docs/adr/README.md`
- `docs/adr/0001-electron-python-sidecar-boundary.md`
- `docs/adr/0002-uds-startup-token-protocol.md`
- `docs/adr/0003-macos-release-signing-update-policy.md`
- `docs/adr/0004-runtime-paths-legacy-data-migration.md`
- `.agents/skills/lcf-desktop-development/**`
- `.agents/skills/lcf-change-traceability/**`

实现文件必须在实际修改时追加到本节并更新
[本次变更映射](../traceability.md#本次变更映射)。当前列表不表示未来路径已创建。
