# ITER-0001：Electron foundation

- 状态：`validated`
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
| Main 为信任边界；Python 与 Node worker 分离 | [ADR-0001](../../adr/0001-electron-python-sidecar-boundary.md) | Electron/Python 源码纵切已实现；packaged runtimes 仍为 `planned` |
| sidecar/worker 使用私有 UDS + 每次启动令牌 | [ADR-0002](../../adr/0002-uds-startup-token-protocol.md) | Python 源码合同已实现；macOS/packaged 集成仍为 `not-run` |
| DMG、自签名、受保护发布与更新 fallback | [ADR-0003](../../adr/0003-macos-release-signing-update-policy.md) | 仅有 packaging 配置骨架；发行、签名与更新均为 `not-run` |
| macOS 路径、按需模型与可回滚旧数据迁移 | [ADR-0004](../../adr/0004-runtime-paths-legacy-data-migration.md) | 私有 desktop data/runtime 目录已实现；模型与迁移仍为 `planned` |

## 任务

- [x] **T01 治理骨架**：建立根规则、文档索引、路线图、追踪矩阵、初始 ADR 和两个项目 skill；
  通过 VAL-GOV-001/002 后勾选。
- [x] **T02 Electron 信任边界**：实现 Main/preload/renderer 骨架和类型化 IPC。
- [x] **T03 本地协议纵切**：实现源码模式 UDS、每进程独立启动令牌、握手、停止和手动恢复。
- [x] **T04 Renderer 适配**：桌面 bridge fail closed，浏览器 transport 保持兼容，清除 CSP
  不允许的 inline style，并阻止桌面 Markdown 外链。
- [x] **T05 契约与 CI**：同步产品/协议版本，添加 source-mode tests 和无 secret 的 PR CI。
- [x] **T06 收口与发布**：全量回归、独立安全审查、更新证据和变更清单，发布 Draft PR。

## 验收

- [x] 每项硬约束都能由 `REQ -> ADR -> task -> path -> VAL -> evidence` 追踪。
- [x] 源码级负向测试证明 renderer 不能直接访问 Node、文件、子进程、令牌、socket 或 updater。
- [x] Main 只接受可信 frame、版本化 channel 和精确 API allowlist；`/api/admin/*` 被拒绝。
- [x] UDS 目录/socket 权限、令牌、launch ID、协议、request ID、deadline 与 payload 上限有测试。
- [x] 现有 Web/API/Host Runner 回归通过，browser/Docker transport 不变。
- [x] 普通 CI 只需 `contents: read`，且不引用 release Environment 或 secret。
- [x] GitHub Actions 的全部必需 source jobs 在发布提交上通过并留下 run URL。
- [x] 真实 AF_UNIX bind 在 Linux/macOS source 环境无 skip 通过；macOS/packaged IPC
  仍由后续物理门禁验证。
- [x] packaged/DMG/签名/更新/迁移门禁保持 `not-run`，并链接到后续迭代。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| VAL-GOV-001 | `pass` | 2026-07-30；evidence tree | `python3 tools/check_markdown_links.py` | 排除生成缓存后，48 个受管 Markdown 文件的仓库内相对链接通过 |
| VAL-GOV-002 | `pass` | 2026-07-30；governance commit | `quick_validate.py` 分别检查两个 skill；reference 行数检查 | 两个 skill 均 valid；references 均少于 100 行 |
| VAL-P1-CONTRACT-001 | `pass` | 2026-07-30；Linux x86_64；Node 24.14；Python 3.12.13 | `UV_CACHE_DIR=/tmp/lcf-uv-cache make ci-python`；`NPM_CONFIG_CACHE=/tmp/lcf-npm-cache make ci-web`；`NPM_CONFIG_CACHE=/tmp/lcf-npm-cache make desktop-ci` | Desktop 42、Web 34、Backend 169 通过；只覆盖纯源码合同，不包含真实 UDS bind、macOS 或 packaged runtime |
| VAL-P1-SOURCE-001 | `pass` | 2026-07-30；`6d5ddf8`；[Actions 30550023917](https://github.com/fredgnr/local-context-forge/actions/runs/30550023917) | GitHub Actions 的 Python/Web/Desktop/macOS arm64 source jobs | Ubuntu Python 170、Desktop 42、Web 34 全通过；macOS 15 arm64 IPC 43 全通过，真实 AF_UNIX bind 无 skip |
| VAL-P1-REGRESSION-001 | `pass` | 2026-07-30；Linux x86_64；Node 24.14；Python 3.12.13；Actions `6d5ddf8` | `UV_CACHE_DIR=/tmp/lcf-uv-cache make ci-python`；`NPM_CONFIG_CACHE=/tmp/lcf-npm-cache make ci-web` | 本地 Backend 169 pass + 1 sandbox-only skip、Host Runner 8、Web 34；Actions Ubuntu Backend 170 无 skip |
| VAL-CI-001 | `pass` | 2026-07-30；`6d5ddf8`；[Actions 30550023917](https://github.com/fredgnr/local-context-forge/actions/runs/30550023917) | workflow/Makefile 静态审计 + 四个必需 source jobs | workflow 仅 `contents: read`，无 Environment/secret；Python/Web/Desktop/macOS arm64 全通过 |
| VAL-TRUST-001 | `not-run` | 2026-07-30；pre-push tree | 42 个 Desktop L1 source tests + 独立静态安全复核 | 源码边界子检查通过；该门禁还要求 packaged app，因此不能标记 pass |
| VAL-PY-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-QMD-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-IPC-001 | `not-run` | 2026-07-30；`6d5ddf8` | Main/Python UDS、令牌、握手、超时、生命周期与负向 source tests | macOS arm64 source bind/合同子门禁已通过；packaged child/lifecycle 尚未运行，因此完整门禁不提升 |
| VAL-CLI-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-MCP-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-INSTALL-001 | `not-run` | — | 见追踪矩阵 | 尚无 DMG |
| VAL-MODEL-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-RELEASE-001 | `not-run` | — | 见追踪矩阵 | 尚无 release |
| VAL-SECRET-001 | `not-run` | — | 见追踪矩阵 | 尚无 release workflow |
| VAL-UPDATE-001 | `not-run` | — | 物理 0.0.1 → 0.0.2 | 尚未实现；阻断更新声明 |
| VAL-DATA-001 | `not-run` | — | 见追踪矩阵 | 尚未实现 |
| VAL-LEGACY-001 | `not-run` | — | 见追踪矩阵 | 尚未执行迁移演练 |

依赖审计补充记录：

- `desktop` 的 `npm audit --omit=dev --audit-level=high` 为 0 vulnerabilities；
- 完整 dev tree 的 `npm audit --audit-level=high` 为 `fail`：Electron 打包工具链的
  `brace-expansion` 传递路径报告 16 个 high 且当前无修复。本迭代 source CI 不执行
  `electron-builder`，但 ITER-0004 在解决、隔离或正式接受该风险前不得通过发行门禁。

独立安全复核结论：source-mode Draft PR 为 `GO`，未发现阻断项；merge-ready、
packaged app、DMG、签名、安装和 release security 均为 `NO-GO`，直到 Actions、真实
AF_UNIX/macOS、packaged runtime、干净机与 ITER-0004 依赖处置证据齐备。

## 风险与缓解

| 风险 | 影响 | 缓解/回滚点 |
| --- | --- | --- |
| 自签名且未 notarize | Gatekeeper 提示与用户信任下降 | 明确披露、固定发布来源与更新公钥；保留手动 DMG |
| 无 hardened runtime | 降低进程级平台加固 | 收紧 renderer/IPC/子进程边界；不得宣称等同 notarized 应用 |
| PyInstaller 隐式依赖遗漏 | 打包后功能缺失 | 对 `onedir` 运行回归和资源清单审计 |
| QMD/Node native 兼容 | arm64 worker 启动或索引失败 | 固定 Node 22 与依赖；干净机 contract/smoke |
| UDS 路径、权限或 stale socket | 启动失败或本机同用户注入 | 短路径、0700 目录、令牌、owner/symlink 检查、每次启动清理 |
| 截止时间后同步 handler 的线程工作可能继续 | 连续短 deadline 可积累后台工作并造成可用性下降 | Main 限制 8 个并发且非幂等结果标记 uncertain；ITER-0002 为未完成 application tasks 增加硬上限/信号量及连续超时回归 |
| Main 退出时 child 在有界 SIGTERM/SIGKILL 后仍未确认退出 | 可能短暂遗留孤儿进程和 runtime 目录 | 保留 `failed/canRetry=false`、不提前清理或重启；fd3 EOF 作为额外停止信号；在 packaged 生命周期门禁观察 |
| 同一用户可写 renderer tree 的路径组件 TOCTOU | 源码模式静态资源可能在验证与打开间被替换 | 最终文件使用 `O_NOFOLLOW`；源码模式只面向开发；ITER-0004 对 packaged resources 做完整性与 Electron 实测 |
| 响应 allowlist 不是通用 DLP | 合法 content/message 文本仍可能包含路径样式字符串 | 不赋予文件能力；结构化 `path/file`、library source、token/socket/header/stderr 已单独过滤；继续限制 renderer route |
| 模型下载中断/篡改 | 磁盘浪费或加载不可信权重 | partial 文件、完整性校验、原子 rename、显式清理 |
| 旧数据模式漂移 | 丢失、重复或无法回滚 | 只读盘点、备份、staging、journal、原目录不改写 |
| 自动更新在自签名环境失效 | 用户停留旧版本 | G6 实机阻断；失败则校验后下载并打开 DMG |
| 公开仓库 secret 泄漏 | 签名/更新供应链受损 | protected Environment、审批、fork/PR secret 负向验证 |
| Electron 打包工具链的传递依赖审计 | 完整 dev tree 的 `brace-expansion` 链报告 16 个 high、当前无修复；可能造成构建进程 DoS | P1 CI 不调用 `electron-builder`，`npm audit --omit=dev` 为 0；在 ITER-0004 发布门禁前升级/隔离并重新审计，当前结果不能作为 release 证据 |
| 过早删除 Docker | 现有用户无恢复路径 | legacy 保留至 P7 和独立 ADR |

## 迭代修订

| 日期 | 修订 | 原因 |
| --- | --- | --- |
| 2026-07-30 | 把 packaged runtimes、数据/模型、DMG、更新和 legacy 退出拆到 ITER-0002–0006 | 让源码纵切与只能在 macOS/真实产物上完成的门禁分别审查，避免一次 PR 产生虚假完成声明 |
| 2026-07-30 | 完成 P1 源码纵切并拆分 `VAL-P1-CONTRACT-001` 与完整 source/physical gates | 纯源码合同已有可复现证据，但 G1、真实 UDS、macOS、packaged app、DMG、签名和更新门禁仍开放 |
| 2026-07-30 | 首轮 macOS run 30549806596 因 pytest 临时路径自身超过 100 bytes 失败；`6d5ddf8` 改用 `/tmp` 短私有夹具，run 30550023917 四个 source jobs 全通过 | 保留生产 100-byte 上限和真实 bind 门禁，不以 skip 或放宽路径限制换取绿灯 |

## 变更清单

治理与计划：

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

版本、验证与 CI：

- `runtime/version.json`
- `tools/check_version_sync.py`
- `tools/check_markdown_links.py`
- `.github/workflows/desktop-ci.yml`
- `.github/dependabot.yml`
- `Makefile`
- `.gitignore`

Python desktop sidecar：

- `backend/app/{cli,desktop_session,factory,version}.py`
- `backend/app/{__init__,main,service}.py`
- `backend/{pyproject.toml,uv.lock}`
- `tests/backend/test_desktop_transport.py`

Electron Main/preload：

- `desktop/package.json`
- `desktop/package-lock.json`
- `desktop/electron-builder.yml`
- `desktop/README.md`
- `desktop/resources/**`
- `desktop/scripts/afterPack.cjs`
- `desktop/src/**`
- `desktop/tests/**`
- `desktop/{tsconfig.json,vitest.config.ts}`

Web renderer 适配：

- `web/src/{App,App.test,api,api.test,desktopBridge,desktopBridge.test,csp.test}.ts*`
- `web/src/MarkdownView.test.tsx`
- `web/src/components/{KnowledgeGraph,MarkdownView}.tsx`
- `web/src/styles.css`

以上路径已同步到[本次变更映射](../traceability.md#本次变更映射)。`node_modules`、
`dist`、虚拟环境、缓存、模型、索引和用户数据不属于变更清单。
