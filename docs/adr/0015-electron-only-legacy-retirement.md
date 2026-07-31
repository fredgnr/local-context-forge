# ADR-0015：Electron-only 收敛与 legacy 运行面退役

- 状态：Accepted
- 日期：2026-07-31
- 关联需求：REQ-ELECTRON-ONLY-001、REQ-PRE1-BREAKING-001
- 关联验证：VAL-ELECTRON-CUTOVER-001、VAL-LEGACY-ABSENCE-001
- 依赖：ADR-0001、ADR-0002、ADR-0003、ADR-0004、ADR-0005、ADR-0006、ADR-0007、
  ADR-0008、ADR-0009、ADR-0010、ADR-0011、ADR-0012、ADR-0013、ADR-0014
- 实施计划：[Electron-only legacy retirement](../development/legacy-retirement.md)

## 上下文

项目仍处于 pre-1.0 早期研发阶段，当前仓库同时存在两套产品运行面：

1. legacy Docker/Compose 通过 `api`、`mcp`、`web` 三个容器公开 loopback TCP
   `8000`、`8001`、`8080`，并依赖安装脚本、Host Runner spool、HTTP MCP、浏览器
   `fetch` fallback、容器运维脚本和 GHCR 镜像；
2. 目标 Electron 应用把 `web/src/**` 构建成 sandboxed renderer，以 Electron Main
   为信任边界，经私有 UDS 使用 Python sidecar、QMD worker 和 stdio MCP companion，
   并由 Main 管理 Codex/Cursor provider。

两套运行面长期并存会迫使每次 UI、provider、数据、模型、API、CI 和发布变更同时维护
两种传输与部署方式。更严重的是，目录名会误导删除范围：`web` 不等于 legacy Web，
因为 `web/src/**` 是 Electron renderer 的现行源代码；`backend` 也不等于 legacy API，
因为 `backend/app/**` 的领域逻辑和私有 UDS sidecar 是 Electron 的核心组成。

产品尚未对外承诺稳定的 Docker、HTTP API、HTTP MCP、端口、环境变量、镜像、安装脚本或
legacy 数据导入合同。维护这些兼容层会延迟 Electron all-in-one 的完成。本决策因此允许
pre-1.0 的大范围不兼容收敛，但必须把“停止兼容”与“删除用户数据”严格分开。

## 决策

### 1. 唯一目标运行面

REQ-ELECTRON-ONLY-001：Electron 成为唯一受支持的产品安装、启动、UI、provider、检索、
MCP 和发布运行面。Electron 完整替代相应能力并通过本 ADR 的门禁后，删除以下 legacy-only
能力，而不是继续保留 shim、代理、弃用窗口或双写路径：

- Docker/Compose 的 `api`、`mcp`、`web` 服务与 Dockerfile；
- 浏览器可直接访问的 Web 部署、Nginx、loopback TCP REST API 与端口配置；
- Python HTTP/stdio legacy MCP gateway；
- Host Runner、LaunchAgent/spool 协议和 legacy provider 选择路径；
- `install.sh`、`install.command`、`scripts/lcf` 及只服务 legacy 部署的运维脚本；
- container/GHCR build、publish、SemVer tag 和相关文档合同；
- 只证明以上兼容面的测试、环境变量、Make target、示例和说明。

“Electron-only”不表示把所有逻辑塞进一个 OS 进程。ADR-0001 的 Main、Python sidecar、
QMD worker、MCP companion 和受控 CLI 子进程拓扑继续有效；all-in-one 指一个可安装、可启动、
不依赖用户安装 Docker/Python/Node/Git/ctags 的 `.app`/DMG 产品。

### 2. 早期破坏性变更政策

REQ-PRE1-BREAKING-001：在项目进入稳定兼容承诺前，legacy 命令、URL、端口、REST schema、
HTTP MCP transport、环境变量、Compose service、镜像名、volume layout、备份格式和旧 alpha
数据格式均不承诺向后兼容。退役实现不得为这些表面新增 alias、自动迁移器、协议转发器、
双写、兼容镜像或长期维护分支。

如果旧 Electron alpha 数据与新格式不兼容，应用必须 fail closed、使用新的版本化数据根，
或要求用户显式选择导出/重置；不得把“不兼容”实现为静默覆盖、清空或递归删除旧目录。
这是一项数据安全要求，不是兼容承诺。

### 3. 删除前置门禁

本 ADR 接受的是方向和删除授权条件，不是“立即删除”的授权。本轮只建立规划。实际删除
必须在全部能力聚合满足以下条件后进行：

1. VAL-ELECTRON-CUTOVER-001 在 packaged Apple Silicon 应用上证明目标能力已由 Electron
   替代；source test、mock 或浏览器开发服务器不能代替 packaged gate；
2. 删除变更先完成 [严格路径矩阵](../development/legacy-retirement.md#严格改动范围)，
   每个路径必须标为 `remove`、`retain` 或 `split`，不得通过目录名批量推断；
3. `split` 路径先抽离 Electron 依赖部分，再删除 legacy 分支；
4. 删除后 VAL-LEGACY-ABSENCE-001 的静态 absence gate 与 Electron 回归门禁同时通过；
5. 任何一个尚未被 Electron 替代的 capability 都会阻断全部 destructive removal；此时只允许
   继续做 split、caller inventory、测试和 packaged evidence，不得删除任何 legacy capability、
   文件或兼容分支。

### 4. 必须保留的 Electron 组成

下列内容不属于 legacy 删除授权：

- `desktop/**`，包括 Main、preload、packaging、QMD worker 和 `desktop/companion/**`；
- `web/src/**` 的 React renderer、类型、样式和 Electron bridge，以及 renderer 的 Vite/npm
  构建输入；只能删除其中 browser/HTTP fallback 和 legacy-only UI 分支；
- `backend/app/**` 的领域服务、数据库、队列、source/Wiki、provider attempt、验证及
  private UDS sidecar；只能删除 public TCP entrypoint、Host Runner spool adapter、CORS/
  browser compatibility 和确认无 Electron caller 的 legacy 分支；
- `backend/packaging/**`、runtime provenance/schema、desktop release/update workflow 与工具；
- Context7 兼容的 `resolve-library-id`、`query-docs` 行为；transport 收敛到 bundled stdio
  companion → Main private bridge，不删除工具语义；
- `~/Library/Application Support/Local Context Forge/` 中的 Electron 用户数据、当前格式
  backup/restore 语义以及缓存、日志、Keychain 和 runtime path 的安全边界；
- ADR、迭代和 evidence 历史。历史文档可以描述已退役行为，但当前用户入口必须明确标记。

### 5. 用户数据和外部资产

删除源代码不自动执行任何 legacy uninstall，也不得删除或修改仓库外的用户资产：

- `./data`、`./imports`、`./backups`、`.lcf/`；
- Docker named volume、bind mount、container 或本地镜像；
- 既有 GHCR package、GitHub Release、Actions artifact；
- Application Support、Caches、Logs 或 Keychain 条目。

项目不再承诺读取、迁移或恢复 legacy data/volume/backup，但应提供一次明确的停止支持说明：
需要保留历史数据的用户应在升级前自行复制或继续使用固定的旧源码/镜像。任何远端 package
删除或本机数据清理都是独立、显式、可复核的破坏性操作，不能夹带在退役 PR 或安装脚本中。

### 6. 传输与发布边界

- 删除的是 browser/public loopback TCP API，不是 Python sidecar 内部服务合同。当前
  FastAPI route 可暂时经 UDS 留作 Main 的私有实现细节；后续可在不暴露 renderer 权限的
  前提下重构为更窄的领域 adapter。
- 删除的是 `mcp/**` legacy gateway，不是 `desktop/companion/**` 和 ADR-0008 的只读 MCP
  桥。
- 删除的是 Nginx/browser Web 部署，不是 `web/src/**` renderer。
- 删除 `container-images.yml` 后，release tag 只服务 desktop 候选/推广流程。停止 GHCR
  发布不修改 ADR-0014 的 Draft、trusted-main promotion、fixed Release ID、签名 secret、
  Environment 或物理门禁。

## 对既有 ADR 的影响

本 ADR 不改写既有 Accepted ADR 文件；以下条款自本 ADR 起被精确地部分取代：

| 既有决策 | 被取代的范围 | 继续有效的范围 |
| --- | --- | --- |
| ADR-0004 | “支持的 legacy 输入”“迁移事务”“Legacy 生命周期”、legacy `imports/` / `migration/` 数据类别、以 VAL-DATA/UPDATE/LEGACY 和回滚迁移为删除前提，以及“迁移后立即删除”的兼容性讨论 | 非 legacy 的标准 macOS 路径与数据分类、模型下载/CAS、默认不删除 Application Support、当前 Electron 数据的 backup 安全语义 |
| ADR-0005 | 决策 9 中 legacy browser/Docker provider 必须继续保留的要求，以及上下文中把 Host Runner 视为长期兼容面 | Desktop `codex_only` / `codex_then_cursor`、Main supervisor、attempt CAS、固定 argv、commit 后不 fallback/replay |
| ADR-0006 | 决策 8 中 legacy shell/Docker 产品运行时可以继续依赖 Git 的例外 | packaged 产品禁止系统 Git，Dulwich policy 和测试使用 C Git 创建/验证 fixture 的例外 |
| ADR-0012 | 决策 6–7 中 Docker/browser 环境配置和 explicit imports 策略必须保持不变的兼容要求 | Main picker、一次性 opaque grant、renderer 路径保密、Backend 复验和本地私有仓库边界 |

ADR-0014 的规范正文只定义 desktop 候选与公开推广，并未建立 GHCR same-tag 的规范条款，
因此本 ADR **不 supersede ADR-0014 本身**。本 ADR 取代的是 roadmap、traceability、runbook 和
发布说明中“同一 tag 同时触发 GHCR 与 desktop”的现有产品约束；删除 container workflow 后，
ADR-0014 的 desktop-only 两阶段流程完整保留。

ADR-0001 中“旧 Docker 与桌面形成两套启动路径”的迁移期限制，以及 ADR-0012 之外其他文档中
“保留 browser/Docker transport”的描述，均由本 ADR 的 Electron-only 目标收敛；ADR-0001 的
信任边界和进程拓扑不变。

## 后果

正面后果：

- 只有一套部署、provider、MCP、数据路径和发布面，显著降低测试与支持矩阵；
- 消除三个常驻容器、Nginx、公共 loopback 端口和 Host Runner spool 的攻击面；
- container/GHCR 与 desktop tag 不再产生非原子部分发布状态；
- renderer 和领域代码仍可复用，避免把“删 Web/API”误做成 UI/sidecar 重写。

成本与限制：

- 现有 Docker/browser/HTTP API/HTTP MCP 用户将没有兼容升级路径；
- 旧脚本、镜像和数据只能由用户固定旧版本自行访问，项目不提供迁移 SLA；
- `web/src/**`、`backend/app/**` 和测试需要先做精细拆分，不能一次删除整个目录；
- 退役前仍需完成 packaged M4 真机能力验证；Accepted 不表示这些门禁已通过；
- source tree 的删除不能清理外部 GHCR package、Docker volume 或用户目录。

## 被拒绝的替代方案

1. **永久保留 Docker/browser 作为 advanced mode。** 拒绝：形成第二套受支持产品面，
   与 all-in-one 的单一运行目标冲突。
2. **保留只读 HTTP API/MCP 兼容代理。** 拒绝：仍需端口、认证、schema 和网络安全维护；
   bundled stdio companion 已覆盖目标 MCP 用例。
3. **先删除整个 `web/` 与 `backend/`。** 拒绝：会删除 Electron renderer 和 private
   sidecar 核心，违反严格范围要求。
4. **为所有 legacy data 实现自动迁移后再退役。** 拒绝：项目尚未承诺此兼容合同，成本会
   延迟 Electron 完整替代；数据保留和不自动删除仍是强制要求。
5. **退役时顺便删除旧 volume/GHCR package。** 拒绝：这是独立破坏性操作，不能由源码
   收敛隐式授权。
6. **保留 container workflow 但停止文档宣传。** 拒绝：仍会消耗 CI、发布镜像并把 tag
   与两个产物体系耦合。

## 验证门禁

### VAL-ELECTRON-CUTOVER-001

在无 Docker/Homebrew/Python/Node/Git/ctags 运行依赖的干净 M4/macOS 用户上，以 packaged
candidate 完成：安装/首启、仓库提交、审核、队列、取消/失败恢复、页面生成与发布、查询、
embedding model 切换与重建、重启后持久化、Codex 默认与受控 Cursor fallback、bundled MCP
两个工具、当前 Electron 数据 backup/restore，以及无 public TCP listener。记录 exact commit、
candidate digest、机器/OS、步骤、结果和脱敏 artifact。

### VAL-LEGACY-ABSENCE-001

退役提交必须同时满足实施计划中的 machine-checkable absence gate：legacy 文件不存在，
产品/CI 无 Compose、GHCR、Host Runner、legacy MCP、public REST/browser fallback 或端口引用，
且 retained/split path 的 Electron source、packaging、renderer、sidecar、MCP 和 release tests
通过。历史 ADR/evidence 中的文字不计为运行面残留。

两个门禁目前均为 `not-run`。在 VAL-ELECTRON-CUTOVER-001 通过前，本 ADR 不授权执行删除；
在 VAL-LEGACY-ABSENCE-001 通过前，不得宣称 Electron-only 收敛完成。
