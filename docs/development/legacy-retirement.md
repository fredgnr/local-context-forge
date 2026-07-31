# Electron-only legacy retirement plan

> 状态：`planned`。本页是 [ADR-0015](../adr/0015-electron-only-legacy-retirement.md)
> 的严格实施范围，不是删除已经发生或门禁已经通过的声明。

## 1. 目标、坐标与强制规则

本计划落实两个稳定需求：

- **REQ-ELECTRON-ONLY-001**：Electron 是唯一受支持的产品运行与发布面；完整替代后删除
  Docker、browser Web、public loopback API、legacy HTTP MCP、Host Runner、container/GHCR。
- **REQ-PRE1-BREAKING-001**：项目仍处于 pre-1.0，允许不兼容删除，不提供 legacy shim、
  自动迁移、弃用期或长期兼容分支；不兼容绝不等于可以静默删除用户数据。

对应门禁：

- **VAL-ELECTRON-CUTOVER-001**：packaged M4 真机上的能力替代门禁；
- **VAL-LEGACY-ABSENCE-001**：删除后的 machine-checkable absence 与 Electron 回归门禁。

强制执行顺序：**inventory → split（只解耦，不提前删除 capability）→ packaged replacement
evidence → remove → documentation/release cleanup → aggregate absence gate**。禁止使用
`rm -rf web backend`、按目录名猜测用途，或在
没有 capability replacement evidence 时提前删除。

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

所有行的 replacement gate 都有证据并使聚合 `VAL-ELECTRON-CUTOVER-001=pass` 后，才能删除
任一 legacy owner。实现可以按行拆分为多个准备/解耦 PR，但 packaged 聚合门禁之前只允许
抽离 Electron 依赖、增加测试和停止新调用，不允许删除旧 capability、文件或兼容分支。

| Capability | Current legacy owner | Electron replacement | 删除前最低证明 |
| --- | --- | --- | --- |
| 安装/启动/状态 | `install*`、`scripts/lcf`、Compose | signed/self-signed DMG、Main lifecycle、desktop diagnostics | packaged 安装/首启/重启/退出；无外部 runtime |
| UI | Nginx + browser URL `:8080` | `web/src/**` staged renderer + `lcf:` protocol | packaged renderer、CSP/导航/无 Node 权限 |
| 管理 API | loopback TCP FastAPI `:8000` | typed preload request + Main validation + private UDS sidecar | renderer 无 TCP fallback；负向 IPC/UDS auth |
| 仓库导入 | browser URL/import roots | Main picker opaque grant + Backend复验 | home/volume/private repo packaged gate |
| 任务/审核/发布 | browser → REST | renderer → Main → sidecar domain service | submit/queue/review/publish/query E2E |
| provider | Host Runner spool/LaunchAgent | Main provider supervisor + persisted attempt CAS | real Codex；consented Cursor；commit 后不 replay |
| 检索/embedding | Docker QMD / external setup | bundled QMD worker + model manager | model download/validate/switch/rebuild、offline/failure |
| MCP | Python HTTP/stdio gateway `mcp/**` | bundled stdio companion → Main `mcp.sock` | real Codex MCP onboarding、两个 Context7 工具回放 |
| 数据路径 | repo-relative/bind mount/volume | Application Support/Caches/Logs/temp | fresh/restart/current-format backup/restore |
| 备份/恢复 | `scripts/backup.sh`、`restore.sh` | Electron 当前格式 backup/recovery surface | 当前格式 round-trip；不要求 legacy archive import |
| 运维/诊断 | shell doctor/log/smoke/reindex | Desktop UI/doctor/support bundle/rebuild | packaged diagnostics、脱敏、故障恢复 |
| 发布准备 | GHCR api/mcp/web + same-tag product policy | non-publishing desktop test candidate、Draft/promotion source policy 与冻结的 tag control | 不创建 tag/Release；验证 desktop release source policy，并为 cutover test candidate 记录 package/runtime inventory、exact digest 与 tag freeze。正式签名、完整 update/release asset set、Draft、物理审查与 promotion 属于 E05 后 final-bytes absence/release gate |

VAL-ELECTRON-CUTOVER-001 是以上 packaged 证据的聚合门禁。source、mock、Vite dev server、
Docker smoke 或 CI build 不能替代要求 packaged/physical 的行。

本门禁不会创建 release tag。删除前 `container-images.yml` 仍存在，因此无法也不要求在此时
证明“tag 无 container trigger”；该断言只能由 E05 删除 workflow 后的静态/CI gate 证明。
真实 Draft/physical/promotion 又依赖 final removal bytes 和 `VAL-LEGACY-ABSENCE-001`，由独立
release tasks 执行。这样既不放宽删除前的 packaged 能力门槛，也不形成互相等待的发布死锁。
Phase 2 使用的是不发布的 cutover/test candidate，可采用受控 ad-hoc/测试自签 identity；它必须
可安装、可审计并绑定 exact digest，但不冒充 protected formal signing 或 release asset proof。

## 4. 严格改动范围

### 4.1 `remove`：替代门禁通过后完整删除

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
| `AGENTS.md`、`.agents/skills/lcf-desktop-development/**` | 通用信任边界、source/package 验证和 traceability 路由 | 旧“migration 后再决定”前置与 legacy compatibility 测试矩阵 | future agent 只遵循 ADR-0015/ITER-0007；skill validation 通过 |

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

### Phase 0：Scope freeze（本轮）

- 接受 ADR-0015；
- 将每个候选 path 标记为 `remove` / `retain` / `split`；
- 更新 TODO、roadmap、traceability、status 与 iteration；
- 不删除代码、不运行 uninstall、不创建/删除 tag/package/volume。

退出：文档链接通过；所有 legacy removal task 指向稳定 REQ/VAL；状态仍为 `planned`。

### Phase 1：Electron capability closure

- 补齐 renderer/Main/private UDS 的 submit、review、queue、query、settings、model switch、rebuild；
- 完成 Main provider supervisor 的真实 Codex/Cursor 门禁；
- 完成 bundled QMD/model 和 bundled stdio MCP；
- 完成当前 Electron 数据的 backup/recovery 与 diagnostics；
- 移除 Electron 内部对 Host Runner、public TCP 和 browser fallback 的运行依赖，但暂不删
  legacy 文件或分支，便于逐项对照和最终聚合验证。

退出：所有 capability replacement 的 source/integration 子门禁通过；packaged gate仍可为
`not-run`，因此不得进入 destructive removal。

### Phase 2：Packaged cutover evidence

在 clean M4/macOS 用户、无外部运行时条件下执行 VAL-ELECTRON-CUTOVER-001：

1. 安装、首启、重启、退出和 crash recovery；
2. public/local/private repository、提交、队列、审核、发布、查询；
3. embedding 下载/验证/切换、重建、离线和失败恢复；
4. real Codex 默认、受控 Cursor fallback 和 uncertain attempt；
5. bundled MCP onboarding、`resolve-library-id`、`query-docs`；
6. 当前格式 backup/restore、磁盘不足、corrupt input、旧 alpha data fail-closed；
7. 对 Electron 及其全部 child PID 采集进程树与 `lsof`/socket 证据，证明没有任何 INET
   listening socket；如未来确需 listener，必须由新的 Accepted ADR 给出精确进程/地址/端口
   allowlist。另做静态检查证明没有 `8000`、`8001`、`8080` 或可变 public listener 配置，
   且未调用 Docker、系统 Python/Node/Git/ctags。合法的 updater 出站连接不等于 listener。

退出：VAL-ELECTRON-CUTOVER-001=`pass`，证据绑定 exact commit 与 candidate digest。

### Phase 3：Code and deployment retirement

- 先提交 `split` 变更并保留 Electron tests；
- 再删除 `remove` 路径；
- 移除 Make/CI/package/dependency/documentation 引用；
- 不执行 legacy uninstall，不操作外部数据/volume/package；
- 退役 PR 必须明确写出 breaking changes 和 “no migration/no compatibility” 边界。

退出：forbidden-path/transport/release/docs 各子检查本地 `pass`，Electron source/package 回归
`pass`；只有 Phase 4 全部完成后才把聚合 `VAL-LEGACY-ABSENCE-001` 标为 `pass`。

### Phase 4：Release surface cleanup

- 禁用并删除 container workflow 后，确认 tag 只触发 desktop Draft path；
- 更新 protected Environment/runbook 中所有 same-tag/GHCR 说明；
- 保留 ADR-0014 的 desktop Draft → physical review → trusted-main promotion；
- 发布说明告知不再支持 Docker/browser/API/HTTP MCP，且不会自动删除旧数据。
- 从最终 removal commit 构建新 candidate，在该 exact digest 上重跑 Phase 2 的完整核心 packaged
  capability matrix；不得复用删除前候选证据，也不得用启动 smoke 代替。

退出：VAL-LEGACY-ABSENCE-001=`pass`；current docs/handbook 无受支持 legacy 命令；项目状态才可
改为 Electron-only。公开 Release 仍须满足独立 release/physical gates。

## 7. VAL-LEGACY-ABSENCE-001：machine-checkable gate

以下仅是最低目标断言示例，并非完整实现。Phase 3 必须新增受版本控制的
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
测试 target 把失败变绿。packaged/physical VAL-ELECTRON-CUTOVER-001 仍是独立必需证据。

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
2. Electron replacement caller inventory 和门禁状态；
3. exact changed paths；证明未触及用户数据、远端 package、GitHub Release/secret/settings；
4. breaking change 清单和不提供兼容/迁移的说明；
5. exact commands、环境、commit、结果和脱敏 artifact；
6. `git diff --check`、relative link check、absence gate；
7. packaged/physical 项若未运行，必须写 `not-run` 和阻塞条件，不能用 source CI 替代；
8. rollback point：删除前 commit，以及旧数据只读保留说明。

只有 active iteration、traceability、TODO、status、roadmap 和用户文档同时更新，且
VAL-LEGACY-ABSENCE-001 有 commit-bound evidence，才能关闭 legacy retirement umbrella task。
