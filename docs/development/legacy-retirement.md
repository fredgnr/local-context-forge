# Electron-only legacy retirement plan

> 状态：`planned`。本页是 [ADR-0015](../adr/0015-electron-only-legacy-retirement.md) 与
> [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md) 的严格实施范围，
> 不是删除已经发生或门禁已经通过的声明。

## 1. 目标、坐标与强制规则

本计划落实六个稳定需求：

- **REQ-ELECTRON-ONLY-001**：Electron 是唯一受支持的产品运行与发布面；W01/W02 退出门禁
  通过后，按 ADR-0016 的 slice eligibility 独立删除 Docker、browser Web、public loopback API、
  legacy HTTP MCP、Host Runner、container/GHCR。
- **REQ-PRE1-BREAKING-001**：项目仍处于 pre-1.0，允许不兼容删除，不提供 legacy shim、
  自动迁移、弃用期或长期兼容分支；不兼容绝不等于可以静默删除用户数据。
- **REQ-PRE1-SEQUENCING-001**：按显式 W execution rank 执行，不按 W 号排序。
- **REQ-PACKAGED-SMOKE-001**：任何 destructive slice 前先建立最小 packaged feedback loop。
- **REQ-LEGACY-SLICE-001**：每个 slice 独立证明 affected replacement 或受限 pure-legacy
  unsupported disposition、before/after package、absence、protected presence 与无数据副作用。
- **REQ-ENGINEERING-PACKAGE-001**：完整工程测试包只从 W10/W11 cleaned tree 构建。

对应门禁：

- **VAL-PACKAGED-SMOKE-001**：最小 non-release packaged feedback；
- **六个 slice gate**：decouple、deploy、transport、provider、release、docs 的 exact before/after
  门禁；
- **VAL-ENGINEERING-PACKAGE-001**：cleaned tree 的完整 non-release 工程包；
- **VAL-ELECTRON-CUTOVER-001**：W13 cleaned engineering checkpoint 与 W16 exact Draft 的
  packaged M4 能力聚合门禁；
- **VAL-LEGACY-ABSENCE-001**：与上述 cutover 各自同 digest 的 machine-checkable absence 与
  Electron 回归。

强制执行顺序：**governance/source baseline → minimal packaged smoke → independent inventory/
split/remove slices → cleaned-tree engineering package → data/model/runtime/CLI/MCP/local/physical
matrix → final cutover + aggregate absence → production control plane/credentials/formal release**。
禁止使用 `rm -rf web backend`、按目录名猜测用途，或在没有 affected replacement/合格的
pure-legacy unsupported disposition、packaged before/after feedback 和 protected-path presence
时删除。

## 2. Current 与 Target

### Current：双运行面

```text
legacy
browser :8080 -> nginx/web -> TCP FastAPI :8000 -> domain/data/QMD
coding client ------ HTTP/stdio Python MCP :8001 ----^
Docker backend <---- volume spool ---- Host Runner / Codex or Cursor
tag -> container-images.yml -> GHCR api/mcp/web

Electron foundation
React renderer -> typed preload -> Electron Main -> private UDS Python sidecar
                                            |-----> private QMD worker
                                            |-----> bundled stdio MCP companion
                                            `-----> allowlisted Codex/Cursor CLI
```

### Target：Electron-only

```text
React renderer (web/src, sandboxed)
        |
typed preload IPC
        |
Electron Main (sole desktop trust boundary)
        |-- private UDS --> bundled Python sidecar --> shared domain/data/Wiki
        |-- private UDS --> bundled Node/QMD worker --> local embedding/index
        |-- private bridge <--> bundled stdio MCP companion
        `-- allowlisted spawn --> logged-in Codex; consented Cursor fallback

DMG / desktop Release only; no Compose, Nginx, public TCP API, HTTP MCP,
Host Runner spool, container image, GHCR release or browser deployment.
```

目标仍是多进程的单一应用，不是单进程重写。`api`、`web`、`mcp` 在本计划中指部署面时必须
带限定词，避免误删：

- **legacy Web** = Nginx/browser deployment；**renderer** = `web/src/**`；
- **public API** = browser/TCP FastAPI entrypoint；**sidecar API** = Main 经私有 UDS 使用的
  内部实现；
- **legacy MCP** = `mcp/**` Python gateway；**desktop MCP** = `desktop/companion/**` +
  Main private bridge。

## 3. Capability replacement matrix

本矩阵仍定义 capability ownership，但不再要求所有行先聚合为
`VAL-ELECTRON-CUTOVER-001=pass`。每一行可以在 W02 后进入唯一 slice；只有该行的 caller
inventory、slice disposition、split-first、baseline smoke 和数据/外部资产边界明确，才允许删除。
shared 或必需 Electron capability 必须有 affected replacement；纯 legacy-only、已明确 unsupported
且没有 Electron caller/data/external side effect 的 capability 可以记录受限
`no-replacement / unsupported`。该例外不得用于 protected path、数据保留、最终产品能力或 formal
release safety。删除后必须从 exact slice head 重建 package，重跑 smoke、focused/aggregate
source、slice absence 和 protected presence。未触及的完整物理行可继续 `not-run`。

| Capability | Current legacy owner | Electron replacement / disposition | Slice eligibility 最低证明 | 后续完整产品 gate |
| --- | --- | --- | --- | --- |
| 安装/启动/状态 | `install*`、`scripts/lcf`、Compose | W02 packaged App lifecycle；formal DMG 属 W15/W16 | W02 launch/renderer/sidecar/退出；无外部 runtime；不要求正式签名/安装 | W13 cutover；W16 install/Draft rerun |
| UI | Nginx + browser URL `:8080` | `web/src/**` staged renderer + `lcf:` protocol | W02 renderer/preload + focused CSP/navigation/source regression | W06 trust；W13/W16 cutover |
| 管理 API | loopback TCP FastAPI `:8000` | typed preload request + Main validation + private UDS sidecar | W02 private UDS health/domain request + focused IPC/UDS negative source gate | W06 IPC；W13/W16 cutover |
| 仓库导入 | browser URL/import roots | Main picker opaque grant + Backend 复验 | Main/Backend picker caller inventory 与 focused source gate；after-smoke | W12 physical local；W13/W16 cutover |
| 任务/审核/发布 | browser → REST | renderer → Main → sidecar domain service | affected domain/renderer focused + aggregate source；W02 after-smoke | W13/W16 full E2E cutover |
| provider | Host Runner spool/LaunchAgent | Main provider supervisor + persisted attempt CAS | Main-owned attempt/caller source gate；legacy import/spool absence；after-smoke | W08 real CLI；W13/W16 cutover |
| 检索/embedding | Docker QMD / external setup | bundled QMD worker + model manager | bundled worker/broker ownership 与 focused source gate；after-smoke | W05/W07 model/QMD；W13/W16 cutover |
| MCP | Python HTTP/stdio gateway `mcp/**` | bundled stdio companion → Main `mcp.sock` | companion/Main bridge contract + caller inventory；after-smoke | W09 real MCP；W13/W16 cutover |
| 数据路径 | repo-relative/bind mount/volume | Application Support/Caches/Logs/temp | path ownership source gate；删除不读写 legacy/external data；after-smoke | W04 data；W13/W16 cutover |
| 备份/恢复 | `scripts/backup.sh`、`restore.sh` | `no-replacement / unsupported` 可用于旧脚本；W04 Desktop current-format backup 是独立未来能力 | 无 Electron caller；删除不读取/修改 data、backup、volume；不得宣称 legacy archive 可导入 | W04 current-format backup；W13/W16 cutover |
| 运维/诊断 | shell doctor/log/smoke/reindex | `no-replacement / unsupported` 可用于旧 shell 工具；W12 Desktop diagnostics 是独立未来能力 | 无 Electron caller；W02 after-smoke 与 protected presence；不删除日志/用户资产 | W12 Desktop diagnostics；W13/W16 cutover |
| 发布准备 | GHCR api/mcp/web + same-tag product policy | W02/W03 non-publishing engineering artifacts；保留 Draft/promotion source policy | W11 exact before/after package；container trigger absent；formal desktop policy present；不创建 tag/Release、不改 GitHub | W15/W16 continuity、Draft、physical、promotion |

`VAL-ELECTRON-CUTOVER-001` 保留为以上能力在 final cleaned bytes 上的聚合声明门禁，而不是
所有早期 slice 的统一前置。source、mock、Vite dev server、legacy Docker smoke 或 CI build
都不能替代 W02、slice after-smoke、W03 或最终 packaged/physical gate。

W02/W03 不创建 release tag、artifact upload、Draft 或 Release；采用显式 engineering-only
identity/profile，updater unavailable/no-network。`container-images.yml` 的删除由 release slice
验证，远端 GHCR package 保留。正式 GitHub controls、credentials、Draft/physical/promotion 只在
final cutover/absence 后执行。

## 4. 严格改动范围

### 4.1 `remove`：对应 slice 门禁通过后完整删除

| Path / contract | 删除内容 | 对应 replacement |
| --- | --- | --- |
| `docker-compose.yml` | `api`、`mcp`、`web` services、ports、volumes、healthchecks | packaged Main/sidecar/worker/renderer |
| `docker/api.Dockerfile`、`docker/mcp.Dockerfile`、`web/Dockerfile` | 产品 container build | DMG runtime staging |
| `web/nginx.conf` | browser Web hosting、`/api` reverse proxy 与 health endpoint | packaged renderer + typed bridge |
| `backend/.dockerignore`、`mcp/.dockerignore`、`web/.dockerignore` | 只服务 Docker build 的配置 | 无；删除 build surface |
| `backend/requirements.txt`、`backend/requirements-dev.txt` | Docker/旧 bootstrap 的重复依赖入口 | `backend/pyproject.toml` + `backend/uv.lock` |
| `.github/workflows/container-images.yml` | multi-arch build、GHCR login/push、SemVer tags | `.github/workflows/desktop-*.yml` |
| `mcp/**` | Python legacy HTTP/stdio gateway、依赖和说明 | `desktop/companion/**` + Main bridge |
| `host_runner/**` | legacy spool runner 与测试 | `desktop/src/main/providers/**` + Backend attempt ledger |
| `backend/app/main.py` | `app.main:app` public/source uvicorn 全局入口 | `backend/app/cli.py api --uds ...` |
| `install.sh`、`install.command`、`scripts/lcf` | legacy 安装、Compose 管理、Host Runner 安装 | DMG + Main lifecycle |
| `scripts/dev-native.sh` | 三服务 browser/TCP native mode | Electron source/dev launch |
| `scripts/{smoke-test,demo-seed,reindex,backup,restore}.sh` | 端口/REST/Compose 运维 | Desktop E2E、rebuild、current-format backup/recovery |
| `scripts/windows-ollama-setup.ps1` | 非目标 Windows/legacy external model setup | bundled macOS QMD/model manager |
| `examples/requests.http`、`examples/mcp/client-config.json` | public REST/HTTP MCP 示例 | typed bridge/Desktop companion E2E fixtures |
| GHCR container packages 的**发布合同** | 后续不再 build/push/support `*-api`、`*-mcp`、`*-web` | desktop GitHub Release |

上表最后一行只停止发布和支持，不授权删除远端已有 package。远端 package 删除需要单独的
显式批准、精确 package/version 清单和可恢复性评估。

### 4.2 `retain`：Electron 直接依赖，不得作为 legacy 删除

| Path / contract | 保留理由 |
| --- | --- |
| `desktop/**` | Main/preload/trust boundary、packaging、provider、QMD、MCP companion、release |
| `web/src/**`（下表明确列出的 mixed 文件除外）、`web/index.html`、`web/package-lock.json`、`web/tsconfig*`、`web/vitest.config.ts` | Electron renderer 的 canonical source/build/test 输入；不得因目录名是 `web` 整体删除 |
| `backend/app/{desktop_session,desktop_retrieval,desktop_provider_api}.py` | private UDS、broker、provider attempt 的 desktop adapter |
| `backend/app/{__init__,db,facts,locks,queue,retrieval,schemas,service,source,utils,validation,version,wiki,provider_attempts,dulwich_support}.py` | Electron 复用的领域、数据和基础工具层；下表明确列出的 mixed symbol 仍须拆分 |
| `backend/packaging/**`、`backend/pyproject.toml`、`backend/uv.lock` | bundled Python sidecar 构建与 provenance |
| `runtime/**` | sidecar/QMD/renderer/update 的版本、锁和 manifest schema |
| `.github/workflows/desktop-ci.yml`、`desktop-release.yml` | Electron source/candidate/promotion |
| `tools/*sidecar*`、`tools/check_*` | packaging 与治理工具；handbook builder 另按 mixed surface 拆分 |
| `guide-site/**` | 项目说明站点，不是 legacy 产品 Web runtime；内容需更新但不因 Electron 收敛删除 |
| `docs/adr/**`、`docs/development/evidence/**`、Git history | 决策与证据历史不可重写；允许明确标记 historical/retired |
| Application Support/Caches/Logs/Keychain 和任何用户 data/import/backup/volume | 源码退役没有删除用户资产的权限 |

保留整行不代表每个兼容分支永久保留；它表示必须先按下一节拆分，不能删除整条路径。

### 4.3 `split`：先抽离共享能力，再删除 legacy 分支

| Path / surface | 保留 | 删除/重写 | 完成判定 |
| --- | --- | --- | --- |
| `web/src/api.ts` | normalization、typed request/response、desktop bridge call | `VITE_API_BASE`、URL拼接、`fetch`/Abort browser transport、browser错误 | bridge 缺失时 fail closed；无网络 fallback |
| `web/src/desktopBridge.ts` | versioned preload contract、runtime capability validation | “非 desktop 返回 undefined 后转 HTTP”的兼容语义 | renderer 只能在有效 Electron bridge 下工作 |
| `web/src/App.tsx`、组件 | Electron UI、queue/review/model/rebuild/MCP/update | browser-only provider、Host Runner 文案、runtime branches | packaged UI 全能力；无 legacy mode switch |
| `web/src/*.test.ts*` | renderer security、normalization、desktop behavior | “keeps browser/Docker…” 等兼容断言 | 测试改为 bridge-required/fail-closed |
| `web/package.json` | `build`、`typecheck`、`test` 及 Electron renderer 所需依赖 | 面向独立浏览器服务的 `dev`/`preview --host 0.0.0.0`；如保留 source preview，必须仅用于受控 Electron renderer 开发且不构成产品入口 | clean install/build/test 通过；没有 public browser server 合同 |
| `web/vite.config.ts`、`vite-env.d.ts` | renderer build/dev | `/api -> :8000` proxy、`VITE_API_BASE` | desktop build/audit 不再需要 public API |
| `backend/app/cli.py` | Main 传入的 private UDS、token、data/runtime roots 和 sidecar startup | legacy/public listener 入口，以及 Host Runner `runner_dir` 注入 | packaged Main 只能启动 UDS；CLI 无 TCP/runner 参数 |
| `backend/app/factory.py` | Main/sidecar 所需 route/domain adapter | CORS、public TCP/browser assumptions、未被 Main allowlist 使用的 admin route | UDS integration + Main allowlist 覆盖 |
| `backend/app/config.py` | desktop data/QMD/provider settings | ports、CORS、legacy imports/env、Host Runner spool settings | desktop settings仅来自 Main argv/受控配置 |
| `backend/app/generation.py` | shared generation schema/validation（若仍被 desktop 调用） | `HostCliSpoolGenerator` 与 spool request/response | Desktop generation only uses attempt/supervisor path |
| `backend/app/desktop_generation.py` | Desktop attempt orchestration、bounded timeout、job/attempt identity 和 commit CAS | 对 Host Runner spool schema/目录/heartbeat 的依赖；不得仅按 `runner_*` 名称批量删除 | 先把仍属 Desktop 的 `runner_timeout_seconds` / `runner_id` 重命名为 provider timeout/job identity，再证明无 spool owner |
| `backend/app/retrieval.py` | `collection_name`、lexical search、token/snippet 公共逻辑 | direct/system `QmdRetriever`、subprocess 与 legacy cache/config discovery | Desktop retrieval 只经 Main broker；lexical fallback 回归通过 |
| `backend/app/facts.py` | AST/regex facts、source refs 与安全过滤 | system Universal Ctags subprocess/discovery | 无系统 ctags 的 packaged quality/evidence gate 通过 |
| `backend/app/service.py`、`schemas.py` | domain operations、desktop provider/settings | legacy provider order、heartbeat、browser/mock/ollama product paths（若无测试需求） | caller inventory 证明无 Electron 引用后删除 |
| `backend/app/db.py` | current Electron schema、attempt/job/data | 只为 legacy provider/migration 服务的列和 converter | 新 pre-1.0 schema/新 data root，不静默覆写旧 DB |
| `runtime/version.json` | Electron app/protocol/schema/runtime 版本 | `runnerTask`、`runnerSchema` 等只服务 Host Runner spool 的合同 | version sync 仍通过且无 legacy contract |
| `tests/backend/**` | domain、UDS、Dulwich、provider attempt、packaging tests | Host Runner、public TCP、browser/legacy compatibility fixtures | retained code coverage不降低；legacy-only fixture为零 |
| `Makefile` | Electron、sidecar、QMD、renderer、handbook、source CI targets | install/up/down/dev-api/dev-mcp/dev-web/legacy ops、mcp/host_runner CI | `make help` 只有 Electron/dev/governance 表面 |
| `scripts/macos-bootstrap.sh` | 若仍需 source developer bootstrap，则迁移为明确 desktop-dev setup | Docker/Compose、legacy `.env`、mcp/host_runner/native three-service setup | 不作为最终用户安装入口；无 Docker 依赖 |
| `.env.example` | 仅保留确有 source build/test 消费者的非敏感示例 | ports、GHCR、Compose、Host Runner、browser API、legacy model/provider 配置 | 每个变量由 `rg` 找到 desktop/source owner；否则删除 |
| `.github/dependabot.yml` | GitHub Actions、`/web` renderer、`/desktop` npm updates | 仅当 legacy package 被删除时移除其 ecosystem entry | 所有 directory 存在且仍被 CI 使用 |
| `.github/PULL_REQUEST_TEMPLATE.md` | task/REQ/ADR/ITER/VAL、数据安全、验证和 release disposition | `Legacy compatibility` 承诺字段 | 改为 legacy retirement disposition、breaking scope 与 external-data side effects |
| `tools/build_handbook.py` | handbook 生成器、章节顺序、链接/版式合同 | 内嵌的 Docker/Ollama/GHCR/旧安装与 Compose health 文案 | 生成源与产物均通过 active-doc absence gate；builder tests/link check 通过 |
| `guide-site/app/**`、`guide-site/tests/**` | Sites build/hosting 与 Electron guide | Docker/HTTP MCP/localhost 使用说明和对应断言 | guide-site test/build 通过；不再出现 legacy quickstart |
| `docs/15-github-actions-ghcr.md` | 保留编号 15 的章节槽位 | 在同一变更中移除 GHCR/same-tag 内容并改名为 desktop Actions/release 章节，同时更新索引与 handbook builder | `docs/00-*`–`18-*` 编号集连续；current 文档无 GHCR 发布合同 |
| `README.md`、`TODO.md`、`CONTRIBUTING.md`、`SECURITY.md`、`docs/README.md`、`docs/00-*`–`18-*`、`docs/development/{contributor-handbook,desktop-release}.md`、component README、`guide-site/README.md`、`tools/README.md` | Electron 用户/开发/安全/发布说明与当前项目导航 | legacy quickstart、ports、GHCR、HTTP examples、迁移/兼容承诺和可执行 container/handbook release 步骤 | link/handbook check；current docs 无双运行面；历史内容仅在逐文件 allowlist |
| `AGENTS.md`、`.agents/skills/lcf-desktop-development/**` | 通用信任边界、source/package 验证和 traceability 路由 | 旧“migration 后再决定”与全局 cutover-before-any-removal 前置 | future agent 遵循 ADR-0015/0016、work plan、ITER-0008；skill validation 通过 |

`split` PR 必须在描述中列出每个删去 symbol 的 Electron caller search。不能用“没有看到引用”
代替 `rg`、typecheck、unit/integration 和 packaged evidence。

## 5. 明确不在范围内

本计划不授权：

- 删除、移动、压缩或修改本机/外置卷/Docker volume/GHCR 中的既有用户数据或资产；
- 重写 Git history、删除 Accepted ADR/evidence 或伪装历史上不存在 legacy；
- 把 private UDS sidecar 暴露为新的 TCP 服务；
- 把 filesystem、argv、token、socket、credential、updater 或任意 IPC 暴露给 renderer；
- 重写全部 Python 领域逻辑为 TypeScript；
- 删除 Context7 两个工具的名称、输入和结果语义；
- 借 legacy 退役顺带升级无关依赖、重新设计 UI、改变签名根、启用 automatic update apply；
- 宣称旧 Docker data/backup 可导入，或宣称它们已被清理；
- 删除远端 GHCR package、GitHub Release 或本地 Docker artifact。此类破坏性操作须另立任务。

## 6. 分阶段实施与 gates

### Phase 0 / W01：治理与 source baseline（本 Work）

- 接受 ADR-0016；保留 ADR-0015/R12 历史；
- 固定 W01–W16 execution rank 和新 REQ/TODO/VAL；
- 更新 TODO、roadmap、traceability、status、iteration、skills 与 runbooks；
- 不删除代码、不实现 package、不运行 uninstall、不改 GitHub、不生成凭据、不创建 tag/Release。

退出：`VAL-PRE1-SEQUENCE-001`、`VAL-GOV-001`、`VAL-CI-COVERAGE-001` 在 final PR head 为
`pass`；runtime/packaged/physical/settings/release gate 仍 `not-run`。

### Phase 1 / W02：最小 packaged smoke harness

实现与 formal release config 隔离的 engineering-smoke mode，至少验证 launch、renderer/preload、
Main → private UDS sidecar 的健康/一个领域请求、正常退出、无 orphan、无 public INET listener，
并绑定 exact commit/digest/inventory。显著标记 non-release；updater unavailable/no-network；禁止
production secret/pins、tag、upload、Draft/Release。

退出：`VAL-PACKAGED-SMOKE-001=pass`。完整 QMD/model/CLI/MCP/data/physical gate 可为 `not-run`。

### Phase 2 / W10–W11：独立 legacy slices

按以下唯一 ownership 执行，不把多个 destructive scope 混成一次大删除：

1. decouple：shared renderer/sidecar/provider caller inventory 与 split-first；
2. transport：public TCP/CORS/browser HTTP/legacy MCP；
3. provider：Host Runner/LaunchAgent/spool/direct/Ollama/Windows helper；
4. deploy：Docker/Compose/Nginx/install/operations；
5. release surface：container CI/GHCR publish/tag coupling；
6. docs/config/test：active legacy env、tests、Make targets 和用户文档。

每个 slice 在 baseline 和 exact head 分别构建 fresh package、运行相同 smoke，并运行 affected
replacement、focused/aggregate source、slice absence、protected-path presence 与 external-data
non-effect 检查。失败只回退该 slice。

退出：对应 slice VAL 独立为 `pass`；未触及能力继续 `not-run` 不阻断其他 slice。

### Phase 3 / W03：完整 engineering test package

从全部 W10/W11 gate 通过后的 cleaned tree 构建完整 engineering package，包含 renderer、bundled
Python、QMD worker、MCP companion、inventory/SBOM/notices 和工程测试入口。它继续禁止
production credential/pin/tag/upload/Draft/Release，不能提升 formal gate。

退出：`VAL-ENGINEERING-PACKAGE-001=pass`，evidence 绑定 cleaned commit 和 package digest。

### Phase 4 / W04–W12：工程能力与物理矩阵

在 cleaned engineering package 上完成 Desktop data/backup、model、Python/Dulwich/private UDS、
native QMD/retrieval、真实 Codex/Cursor、packaged MCP、local repository、diagnostics 和相关
physical/fault matrix。每个 gate 按自身最低环境记录；source/mock 不替代 physical。

退出：权威 [work plan](work-plan.md) 为 W04–W12 列出的必需 gate 均为 `pass`。

### Phase 5 / W13：Final cutover 与 aggregate absence

从 final cleaned commit 重新构建工程包，在同一 digest 上运行完整
`VAL-ELECTRON-CUTOVER-001` 与 `VAL-LEGACY-ABSENCE-001`。不得复用 W02、单 slice 或较早 W03
bytes；启动 smoke 不替代完整能力矩阵。

退出：两个 final gate 同时 `pass`，current docs 无受支持 legacy 命令，项目才可声明
Electron-only，并解锁 W14。

### Phase 6 / W14–W16：正式发行链

W14 配置 Environments/rulesets/Immutable Releases；W15 provision production credentials/trust
pins，并证明 W13 checkpoint → formal tag 的 diff 只含 allowlisted public pins/release metadata/
version，重跑 source/absence 后经 protected build 创建唯一 Draft；W16 在同一 Draft exact digest
上重新运行完整 cutover/absence，再完成物理审查、trusted-main promotion、公开 Release 与两个
真实单调版本的 `N-1 → N`。`VAL-RELEASE-CONTINUITY-001` 和 ADR-0014 的所有 fail-closed
条款不变。

## 7. VAL-LEGACY-ABSENCE-001：machine-checkable gate

以下仅是最低目标断言示例，并非完整实现。W10/W11 实施必须新增受版本控制的
`tools/check_legacy_absence.py`（或经 ADR/iteration 审核的等价脚本），由 `desktop-ci` 调用；
该脚本、固定 allowlist 与 exact commit 才是规范证据，本页示例不能替代它，也不能因示例漏项
放过 legacy surface。

### 7.1 必须不存在的路径

```bash
set -euo pipefail
for path in \
  docker-compose.yml docker \
  backend/.dockerignore backend/requirements.txt backend/requirements-dev.txt \
  backend/app/main.py \
  mcp host_runner \
  web/Dockerfile web/.dockerignore web/nginx.conf \
  install.sh install.command \
  scripts/lcf scripts/dev-native.sh scripts/smoke-test.sh \
  scripts/demo-seed.sh scripts/reindex.sh scripts/backup.sh \
  scripts/restore.sh scripts/windows-ollama-setup.ps1 \
  examples/requests.http examples/mcp/client-config.json \
  .github/workflows/container-images.yml; do
  test ! -e "$path" || { printf 'legacy path remains: %s\n' "$path" >&2; exit 1; }
done
```

### 7.2 产品与 CI 中必须为零的运行引用

历史 ADR/evidence 可保留文字，因此检查只覆盖 active product/build surfaces：

```bash
set -euo pipefail

! rg --pcre2 -n 'docker(?:\s+--(?:context|host)(?:=\S+|\s+\S+)|\s+--\S+)*\s+compose|docker-compose|ghcr\.io|packages:\s*write' \
  Makefile scripts backend web desktop runtime .github/workflows

! rg -n 'host_runner|HostCliSpoolGenerator|mcp_server|app\.main:app' \
  backend web desktop tests Makefile .github/workflows

! rg -n 'COMPOSE_(PROJECT_NAME|FILE|PROFILES)|DOCKER_(CONTEXT|HOST)|(^|[^A-Z])(API|MCP|WEB)_PORT|BACKEND_URL|BACKEND_TIMEOUT_SECONDS|MCP_(HOST|PORT|TRANSPORT)|LCF_(BIND_HOST|CORS_ORIGINS|IMAGE_SOURCE|IMAGE_TAG|GHCR_OWNER|API_IMAGE|MCP_IMAGE|WEB_IMAGE|RUNNER_DIR|HOST_RUNNER_TIMEOUT_SECONDS)|VITE_API_BASE|VITE_DEV_API_TARGET|http://(127\.0\.0\.1|localhost):(8000|8001|8080)' \
  .env.example scripts backend web desktop runtime Makefile .github/workflows

! rg -n 'fetch\(' web/src/api.ts
```

规范脚本还必须审计 active documentation（root README/CONTRIBUTING/SECURITY/TODO、编号文档、
component README、开发手册、guide-site 源和生成输出），阻止把 Compose、legacy installer、
localhost API/MCP 或 GHCR 重新写成可执行/受支持路径。Accepted/Superseded ADR、iteration 和
commit-bound evidence 只能通过逐文件、逐理由的版本化 allowlist 保留，不能排除整个 `docs/`。

若 Electron 实现合法使用通用单词 `fetch`（例如 update 下载），不得扩大 allowlist；应将 gate
收窄到已审计 symbol/path 并在变更 ADR/iteration 中解释。任何 allowlist 必须逐条含 owner、
理由和移除条件，不能写成忽略整个目录。

### 7.3 必须仍然存在并通过的 Electron 输入

```bash
set -euo pipefail
test -d desktop/src/main
test -d desktop/src/preload
test -d desktop/companion
test -d desktop/workers/qmd
test -d web/src
test -f web/package-lock.json
test -f backend/app/cli.py
test -f backend/app/factory.py
test -d backend/packaging
test -f .github/workflows/desktop-ci.yml
test -f .github/workflows/desktop-release.yml
```

最低回归命令由实施时的 active iteration 固定，至少包括：

```bash
python3 tools/check_version_sync.py
python3 -B tools/check_markdown_links.py
make ci-python
make ci-web
make desktop-ci
make renderer-stage
make renderer-audit
git diff --check
```

若这些 Make target 在收敛中改名，validation 记录必须写出等价 exact commands；不得通过删除
测试 target 把失败变绿。slice smoke、W03 engineering package 和 final
VAL-ELECTRON-CUTOVER-001 是不同证据，均须独立记录。

## 8. Compatibility、data safety 与 rollback

### 不提供的兼容

- 不保证 `make install/up/down`、`scripts/lcf` 或 `install.command` 继续存在；
- 不保证 `localhost:8000/8001/8080`、REST schema 或 HTTP MCP transport；
- 不保证 `.env`、`.lcf/runtime.env`、Compose service、image tag、GHCR package；
- 不保证 Host Runner spool、legacy provider settings 或旧 browser UI；
- 不保证旧 Docker/alpha data/backup 可以被新 Electron 导入；
- 不提供 alias、proxy、双写、deprecation window 或 LTS branch。

### 始终保留的数据安全边界

- 退役代码只改仓库，不运行 `docker compose down -v`、`docker volume rm`、`rm -rf data`、
  GHCR delete 或类似操作；
- 旧数据不可读时 fail closed，并告知其位置/版本不受支持；不得把它当空库覆盖；
- 新格式需要不同 schema 时使用新 versioned root 或显式 reset/export 流程；
- Electron 当前数据的 backup/restore 只需保证当前格式，不构成 legacy migration 承诺；
- 卸载默认保留 Application Support，任何“彻底删除”必须由用户单独明确触发。

### 回滚边界

删除合并前可通过 Git revert 恢复源码。删除合并后若仍需访问旧部署，用户只能固定到删除前的
commit/image 并操作数据副本；项目不保证新 Electron 写入后的数据能由旧版本读取。不得为了
“快速回滚”让 legacy 与 Electron 同时写同一数据库，也不得自动重建已删除的容器/volume。

## 9. 每个退役 PR 的必填证据

1. 关联的 remove/retain/split 行与稳定 REQ/VAL；
2. Electron replacement caller inventory 和门禁状态，或符合上文限制的
   `no-replacement / unsupported` disposition；
3. baseline commit/package digest 与 `VAL-PACKAGED-SMOKE-001` evidence；
4. exact changed paths；证明未触及用户数据、Keychain、远端 package、GitHub Release/secret/settings；
5. breaking change 清单和不提供兼容/迁移的说明；
6. after-slice commit、fresh package digest、相同 smoke、focused/aggregate source、slice absence 与
   protected-path presence；
7. exact commands、环境、结果和脱敏 artifact；
8. `git diff --check`、relative link check、对应 slice gate；
9. 未触及的 packaged/physical 项写 `not-run` 和阻塞条件，不能用 source CI 替代；
10. rollback point：删除前 commit，以及旧数据只读保留说明。

只有 active iteration、traceability、TODO、status、roadmap 和用户文档同时更新，且
final `VAL-ELECTRON-CUTOVER-001` 与 `VAL-LEGACY-ABSENCE-001` 在同一 commit/package digest 有
证据，才能关闭 legacy retirement umbrella task。单 slice pass 不等于 aggregate pass。
