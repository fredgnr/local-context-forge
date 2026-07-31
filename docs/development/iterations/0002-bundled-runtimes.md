# ITER-0002：Bundled runtimes

- 状态：`in-progress`
- 开始日期：2026-07-31
- 上游基线：`main@5d95e58cefa1c94b5c9ac8dd681671e2dfd6d8dd`
- 前置检查点：`agent/electron-desktop-foundation@7e4524f`
- 当前工作分支：`agent/electron-bundled-runtimes`
- 依赖：[ITER-0001](0001-electron-foundation.md) 的源码模式 trust/IPC 契约
- 路线图阶段：P2、P3
- 追踪矩阵：[traceability](../traceability.md)

## 目标与固定范围

把已验证的源码模式进程边界变成无需系统 Python/Node/Git/QMD 的应用内置运行时，同时
保持 renderer 最小能力和 legacy browser/Docker 兼容：

- 固定 CPython 3.13.14，以 PyInstaller `onedir` 交付 Python sidecar；
- 产品源码 snapshot/Wiki Git 改用受控 Dulwich，不调用系统 Git；
- 固定 Node 22.23.2 与 QMD 2.5.3，以独立 worker + Main broker 提供 lexical 检索；
- 保持 Context7 兼容的 `resolve-library-id`、`query-docs` MCP 契约；
- wiki 默认使用已登录 Codex CLI；只有任务开始前、获得同意且 Codex 明确缺失/登出时，
  才可选择 Cursor CLI；
- 生成可复核的来源、依赖、许可证、SBOM、native closure 和精确资源清单。

本迭代不包含 embedding 模型下载、旧数据切换、DMG 发布、自签名、notarization 或自动更新。
packaged runtime 的 macOS CI 证据不替代 clean-user DMG/物理 Mac 门禁。

## 已接受决策

| 决策 | 记录 | 本轮实现状态 |
| --- | --- | --- |
| Main/Python/QMD/renderer 进程边界 | [ADR-0001](../../adr/0001-electron-python-sidecar-boundary.md) | P1 source boundary 已验证；bundled resources 重建中 |
| 私有 UDS、独立启动 token 与不重放 | [ADR-0002](../../adr/0002-uds-startup-token-protocol.md) | Python source 已验证；QMD/broker 与 packaged lifecycle 待实现 |
| provider preflight、attempt 和 commit point | [ADR-0005](../../adr/0005-provider-attempt-execution-boundary.md) | 待实现 |
| 产品 Git 使用受控 Dulwich | [ADR-0006](../../adr/0006-dulwich-product-git-boundary.md) | 待实现 |
| QMD worker/Main broker/lexical fallback | [ADR-0007](../../adr/0007-qmd-retrieval-broker-runtime.md) | 待实现 |
| 内置 MCP companion 与只读 Main bridge | [ADR-0008](../../adr/0008-mcp-companion-main-bridge.md) | 待实现 |
| Python/Node 来源与 fail-closed 打包清单 | [ADR-0009](../../adr/0009-bundled-runtime-provenance.md) | 待实现 |

## 任务

- [x] **R00 恢复与治理**：从 P1 Draft PR 恢复工作树；记录 2026-07-30 未发布工作区被自动
  维护清理的事实；恢复 ADR-0005–0009，不把丢失代码或旧测试摘要作为当前证据。
- [ ] **R01 产品 Git 边界**：以 Dulwich 完成 source snapshot 与 Wiki publish/rollback；
  保留既有安全/生命周期语义，并增加产品 `PATH` trap。
- [ ] **R02 Python bundled sidecar**：固定/验证 CPython 3.13.14 来源，hash-lock 构建工具，
  生成 `onedir`、manifest/SBOM/notices/native closure，并从 Main 启动已审计 staging。
- [ ] **R03 QMD runtime**：实现 worker、独立 token、Main broker、Python retrieval port、
  revision/fallback；随后 staging Node/QMD/better-sqlite3 并运行真实 macOS UDS 生命周期。
- [ ] **R04 MCP companion**：实现两个兼容工具、source/debug 手动授权、独立 capability 和
  official SDK contract replay。
- [ ] **R05 provider attempts**：实现策略/consent/发现/preflight、数据库 attempt/CAS、
  Main 固定执行、恢复为 uncertain 及 Web 状态/重建 UI。
- [ ] **R06 集成与发布**：同步 manifest/schema，运行 source/packaged/macOS 门禁，完成独立
  安全复核，将本迭代作为 stacked Draft PR 发布。

## 验收

- [ ] 产品 Python 路径在失败 `PATH` 下完成 ingest、publish、lint、version、doctor 和真实
  UDS health，不启动系统 Python/Git/ctags。
- [ ] QMD worker 在 bundle 内 Node 22.23.2/better-sqlite3 arm64 上完成 reconcile/search，
  stale/崩溃按 ADR-0007 降级且不下载模型。
- [ ] renderer 不得到 executable、argv、PID、stderr、socket、token、MCP capability 或路径。
- [ ] provider attempt 的 create/claim/select/commit/spawn/complete cut-point 可恢复；commit
  后未知结果不 fallback、不重放。
- [ ] MCP 只有两个 Context7 兼容只读工具，app 未运行/未批准/stale/oversize 均 fail closed。
- [ ] Python/QMD staging 的 source digest、inventory、native closure、SBOM、notices 和
  `beforePack` tamper rejection 可复现。
- [ ] VAL-GIT-001、VAL-PY-001、VAL-QMD-001、VAL-CLI-001、VAL-MCP-001、VAL-PACK-001
  获得与其最低环境相符的证据；无法执行的物理门禁保持 `not-run`。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| VAL-P1-SOURCE-001 | `pass` | 2026-07-30；`7e4524f` | 继承 ITER-0001 Actions 证据 | 仅证明恢复基线，不证明本迭代改动 |
| VAL-GIT-001 | `not-run` | — | 待 R01 | 未实现 |
| VAL-PY-001 | `not-run` | — | 待 R02 | CPython 3.13.14 真正 archive 校验与 macOS onedir 尚未运行 |
| VAL-QMD-001 | `not-run` | — | 待 R03 | real QMD/native/UDS 尚未运行 |
| VAL-CLI-001 | `not-run` | — | 待 R05 | 未实现 |
| VAL-MCP-001 | `not-run` | — | 待 R04 | 未实现 |
| VAL-PACK-001 | `not-run` | — | 待 R02/R03 | 未生成当前 staging |

2026-07-30 曾在被清理的未发布工作树中报告过 Dulwich、QMD source broker、provider foundation
和 packaging fixture 的阶段性通过数。由于对应 bytes、diff 和最终测试产物未提交，以上摘要
只作为重建输入，不能在本表标记 `pass`。

## 风险、阻塞与回滚点

| 风险/阻塞 | 影响 | 缓解/回滚点 |
| --- | --- | --- |
| 自动 workspace maintenance 清理未发布工作 | 本地实现和测试证据丢失 | 每个可审查纵切尽早提交到 stacked Draft 分支；远端 P1 `7e4524f` 为恢复点 |
| CPython 3.12.13 无官方 Darwin arm64 asset | 原计划在 M4 必然无法构建 | ADR-0009 改锁 3.13.14，并双重校验 archive/hash manifest |
| Dulwich 默认 config/transport 行为 | 读取宿主配置或弱化 snapshot/Wiki 语义 | 路径预检、受控 config/HTTPS、现有回归和 C Git 只读互操作 |
| better-sqlite3 ABI/dylib 不匹配 | worker 只在 CI/build 主机可用 | 显式 rebuild、arm64/ABI/RPATH closure 审计、真实 bundled test |
| QMD 2.5.3 不物理清理旧 documents | index 数据增长 | committed allowlist 阻止查询；不声明物理删除，后续独立 compact 设计 |
| provider commit 后 Main 崩溃 | 结果未知、可能重复计费/发布 | attempt 标记 `uncertain`；用户显式新建 retry，不自动重放 |
| source/debug MCP pairing 不是 production identity | 同用户 client 识别有限 | 每连接 UI 批准/撤销；production Keychain/signature pairing 留后续门禁 |
| 打包工具链审计存在 high/no-fix | 阻断 release | 本迭代不宣称 release；在 ITER-0004 前升级、隔离或正式风险接受 |

## 当前变更清单

治理：

- `docs/adr/0005-*` 至 `0009-*`
- `docs/adr/README.md`
- `docs/development/{README,roadmap,traceability}.md`
- `docs/development/iterations/{README,0001-electron-foundation,0002-bundled-runtimes}.md`
- `.agents/skills/lcf-desktop-development/references/architecture.md`

实现路径在各任务落盘后追加；生成 staging、缓存、模型、索引、用户数据和私有 evidence 不入库。
