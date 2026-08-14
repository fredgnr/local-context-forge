# 开发者手册

本文是新贡献者的完整入口。根 [CONTRIBUTING.md](../../CONTRIBUTING.md) 只保留快速清单；
系统设计、当前状态和剩余任务分别见：

- [系统设计](../17-system-design.md)
- [状态快照](status.md)
- [详细 TODO](todo.md)
- [需求—决策—验证矩阵](traceability.md)

> Electron source 是唯一受支持的开发运行面。仓库中的 native browser、Docker/Compose、
> public HTTP、Host Runner 和 legacy MCP 只用于静态 retirement inventory；不要运行它们建立
> 新实例。实际删除受 ADR-0015/0016、[W01–W16 work plan](work-plan.md) 与严格路径矩阵约束：
> W01 修复 candidate 的 PR/source、independent acceptance、accepted merge 与 canonical-main
> source 已全部闭环；W02 static assembly/bundle audit 已运行，但 assembled App 未启动，packaged
> launch/runtime 仍为 `not-run`。
> 只有 W02 完整 packaged smoke 通过后才可按独立 slice 删除，final cutover/absence 留到 W13。

## 1. Checkout 后先建立坐标

在运行安装器、测试或修改文件前：

```bash
git status --short --branch
git rev-parse HEAD
git branch --show-current
```

记录：

- repository/remote；
- exact commit；
- branch；
- dirty/untracked 状态；
- OS、architecture、Python/Node 版本。

不要把 dirty checkout 的“当前工作树通过”写成可复现证据。证据必须绑定 commit 或 Actions
run；未提交内容只能标作本地临时观察。

### 1.1 干净 macOS 的工具链前置

仓库的源码目标不会自动安装全部开发工具。推荐对齐 source CI：

| 工具 | 推荐版本/约束 | 用途 |
| --- | --- | --- |
| Xcode Command Line Tools | 当前 macOS 可用版本 | `make`、编译基础与系统 SDK |
| Python | 3.12；Backend 最低 3.11 | Backend、治理脚本和 source sidecar |
| uv | `0.11.29` | 与 `.github/workflows/desktop-ci.yml` 一致的 Python 安装 |
| Node.js | 24 | Web/Desktop source CI |
| npm | 随 Node 24、服从 lockfile | Web、Desktop、QMD worker、guide-site |

在安装依赖前运行：

```bash
xcode-select -p
python3 --version
uv --version
node --version
npm --version
make --version
```

缺少任一工具时，先按该工具的官方安装方式补齐。不要使用待删除的
`./scripts/macos-bootstrap.sh --native` 准备 Electron 开发环境。
正式 bundle 的 Python 3.13.14 和 Node 22.23.2 由 release workflow 的锁定供应链负责，不应
替换本节的 source 工具。

## 2. 必读顺序

1. 根 [AGENTS.md](../../AGENTS.md)；
2. [开发索引](README.md)和[状态快照](status.md)；
3. [迭代索引](iterations/README.md)与活动
   [ITER-0002](iterations/0002-bundled-runtimes.md)；
4. 你的改动对应的 R07–R13 记录与 [W01–W16 work plan](work-plan.md)；
5. [追踪矩阵](traceability.md)；
6. 所有相关 Accepted ADR；
7. 与目录最接近的 `AGENTS.md`/`AGENTS.override.md`；
8. 对应项目 skill。

Desktop、renderer、Python sidecar、QMD、MCP、打包或测试：

```text
.agents/skills/lcf-desktop-development/SKILL.md
```

ADR、迭代、需求、证据、发布状态：

```text
.agents/skills/lcf-change-traceability/SKILL.md
```

变更架构、安全、数据迁移、打包或发布决定时，先新增 superseding ADR。不要为了让当前实现
看似合理而改写已经 Accepted 的历史 ADR。

## 3. 仓库与组件地图

| 路径 | 责任 | 典型改动影响 |
| --- | --- | --- |
| `desktop/src/main/` | Electron 信任边界、进程、路径、更新、MCP、provider | Desktop tests、packaging、trust gates |
| `desktop/src/preload/` | 类型化最小 facade | IPC contract、Web bridge、负向测试 |
| `desktop/src/contracts.ts` | 跨 renderer/Main 类型 | Main/preload/Web 同步 |
| `desktop/companion/` | 内置 stdio MCP | SDK contract、packaging、MCP lifecycle |
| `desktop/workers/qmd/` | Node/QMD index/search/embed | worker tests、native staging、model gates |
| `desktop/scripts/` | staging/audit/release | tamper、manifest、release policy |
| `web/src/` | Electron React renderer；browser HTTP fallback 待拆 | Web tests/build、desktop bridge |
| `backend/app/` | Domain、SQLite、queue、source、Wiki、query | Backend tests、schema/data impact |
| `backend/packaging/` | PyInstaller、locks、notices | macOS staging、SBOM/native closure |
| `mcp/` | **deprecated / remove** Python HTTP/stdio gateway | 不得与 `desktop/companion/` 混淆 |
| `host_runner/` | **deprecated / remove** 宿主 CLI spool | 先证明 Main provider 已替代 |
| `docker/`、`docker-compose.yml` | **deprecated / remove** containers | 由 ITER-0008/W11 slice 删除 |
| `scripts/` | 混合；legacy deploy/backup/restore/native dev 待删除 | 逐文件按 retirement manifest 处理 |
| `runtime/` | 跨层版本、schema、public trust locks | version sync、packaging fail-closed |
| `docs/adr/` | Accepted decisions | 架构历史，不是完成证据 |
| `docs/development/` | 状态、迭代、证据、TODO | 每个 scoped change |
| `guide-site/` | hosting identity 与当前部署均未验证的说明站点源码 | 独立 build/test/checkpoint deployment；当前 external-blocked，不在主 source aggregate |

理解 desktop 的推荐代码阅读顺序：

1. `web/src/desktopBridge.ts`
2. `desktop/src/preload/index.ts`
3. `desktop/src/contracts.ts`
4. `desktop/src/main/index.ts`
5. `desktop/src/main/ipc.ts`
6. `desktop/src/main/sidecar.ts`
7. `backend/app/factory.py`
8. `backend/app/service.py`
9. 再进入 provider/QMD/MCP/local-source/update 专题模块。

## 4. 运行模式

### 4.1 Native API/MCP/Web（unsupported inventory）

该路径属于 `split` / `remove` 范围，不是可选开发模式。不要运行
`scripts/macos-bootstrap.sh --native` 或 `make dev-native`；需要定位 owner 时使用 `rg`、调用者
清单和 focused tests，不能启动 public listener 代替 Electron source 验证。

### 4.2 Electron source mode

```bash
make ci-python-install
npm --prefix web ci
npm --prefix web run build
make renderer-stage
npm --prefix desktop ci

LCF_RENDERER_DIR="$(pwd)/web/dist" \
LCF_SIDECAR_BIN="$(pwd)/backend/.venv/bin/lcf-service" \
npm --prefix desktop run start:source
```

这条路径使用 `backend/.venv`。Main 不从 PATH 发现 sidecar。没有显式、受审计的 source QMD
配置时，QMD fail closed 并使用 lexical。

### 4.3 Legacy Docker/Web（deprecated historical）

> 不要新建或扩展此运行面。只允许静态 caller/path inventory；
> `TODO-LEGACY-CONTROL-001` 已被取代。实际删除必须遵循
> [strict retirement manifest](legacy-retirement.md)。

不要调用 `scripts/lcf`、`install.sh`、`docker compose up` 或 `smoke-test.sh`。这些命令会改变
本机/container 状态，既不是“只读盘点”，也不能证明 Electron replacement。若维护者必须访问
既有旧实例，应在固定旧 commit 和数据副本上自行承担风险；当前开发流程不提供操作 runbook。

### 4.4 工程打包与正式打包

W02 engineering smoke 目前只完成 exact Draft head 的 static `.app` directory assembly/bundle
audit；pre-pack frozen sidecar staging smoke 已成功，但 assembled App 未启动、sidecar 未从 bundle
启动，完整 packaged launch/runtime gate 仍为 `not-run`。W03 engineering test package 也尚未
实现。两者必须明确 non-release，不用 production credential/pins，不由 tag 触发、不上传、不创建
Draft/Release，updater unavailable/no-network。W02 只支撑 slice feedback；W03 从 cleaned tree
构建并支撑 W04–W12。两者都不能提升 formal gate。

普通开发者不要把本地 `dist:mac` 当成正式发行。正式流程只能由
`.github/workflows/desktop-release.yml` 执行。详见
[Release runbook](desktop-release.md)。

## 5. 工具链版本矩阵

| 范围 | Python | Node | 备注 |
| --- | --- | --- | --- |
| Backend package | `>=3.11` | — | `backend/pyproject.toml` |
| Source CI | 3.12 | Node 24 | GitHub Actions |
| Source dependency install | Python 3.12 + `uv==0.11.29` | Node 24 + npm lockfiles | 先通过 1.1 的 preflight |
| Native bootstrap | 可用 Python + `node@22` | 22 family | 开发辅助，不是 release provenance |
| Bundled Python | 3.13.14 | — | 固定 archive/hash |
| Bundled QMD | — | 22.23.2 | QMD 2.5.3、arm64 native addon |
| Electron dev | — | npm lock + Electron 43.2.0 | source tooling |

不能因为 source CI 使用 Node 24 就把 bundled QMD 的 Node 22.23.2 改成浮动版本。Runtime
升级必须更新 lock、manifest、SBOM/notices、native closure 和相关 ADR/证据。

## 6. 变更类型与最小验证

先跑最窄 focused test，再跑受影响 aggregate。

| 改动 | Focused | Aggregate/额外门禁 |
| --- | --- | --- |
| Python domain/API/DB | 对应 `tests/backend/test_*.py` | `make ci-python` |
| Renderer/UI | 对应 Web vitest | `make ci-web` |
| Main/preload/contracts | 对应 Desktop vitest | `make desktop-ci` + Web bridge tests |
| QMD worker | worker test file | `make ci-qmd-worker`（Node 22.23.2、无 lifecycle script、test network/model trap） |
| MCP companion | MCP Desktop tests | `make desktop-ci`；packaged gate仍 `not-run` |
| Provider | attempt/discovery/process tests | Backend + Desktop + Web |
| Local source | localSource + source_security | Backend + Desktop + Web |
| Update/release | update/release policy focused | Desktop + Backend policy + YAML/shell audit |
| Legacy split/removal | caller/path + affected replacement，或受限 pure-legacy unsupported disposition | W01 PR/source + independent acceptance + accepted merge + canonical-main source + W02 baseline；fresh before/after package smoke；focused/aggregate；slice absence + protected presence；不运行 Docker smoke |
| Engineering package | explicit non-release profile + inventory | W03 cleaned tree；production trust/tag/upload/Draft/Release 禁止 |
| Docs only | link checker、diff check | 无需伪跑 packaged gate |
| Version/manifest | version sync + audit scripts | packaging gate |
| Schema/data | migration focused tests | backup/restore/migration evidence |

### 6.1 Source aggregate

```bash
make ci-source
```

等价主范围：

```bash
make ci-python
make ci-qmd-worker
make ci-web
make desktop-ci
```

机器可读范围由 [source coverage manifest](../../.github/ci/source-coverage.json) 冻结，并由
`tools/check_ci_coverage.py` 反向核对 Make 与 workflow。QMD 实际在 `ci-source` 和现有 Python
source job 中执行，避免新增未受 required-check 约束的可选 job；唯一允许的 skip 是
`better-sqlite3` 未在 source checkout 构建。

QMD model scan 只覆盖 runner 创建的 isolated `HOME`、`XDG_CACHE_HOME`、`XDG_CONFIG_HOME`、
`XDG_DATA_HOME` 与 `TMPDIR`。machine result 必须明确
`repository_worktree_scanned=false`、`global_tmp_scanned=false`；0 个 model/cache delta 不表示整个
runner/filesystem 已扫描。

`guide-site/**` is excluded from `make ci-source` and Desktop source CI；它不是“已覆盖”。当前
tracked checkout 缺 `guide-site/.openai/hosting.json`，也没有仓库拥有、绑定 exact commit 的
独立 build/test/checkpoint-deployment 结果，所以机器 disposition 为 `external-blocked` /
unvalidated。恢复 exact Sites identity 前不得猜 identity、部署或把 legacy guide tests 改写为
W01 pass。

### 6.2 单独治理检查

```bash
python3 tools/check_markdown_links.py
python3 tools/check_version_sync.py
python3 -B tools/check_ci_coverage.py
python3 -B tools/check_w01_evidence.py
git diff --check 1786255b55dd1a78659ed92235893876175a0722 HEAD
```

W01 historical checker 只验证 versioned immutable coordinates 与 cross-field consistency，不读
当前 Git ancestry，也不限制 future product descendant。当前 exact head 由 workflow payload 与
独立 provenance artifact 绑定。PR/branch canonical activation 必须 `blocked`；canonical-main
source result 也不能替代 external independent acceptance。

### 6.3 Packaged/physical

只有在对应最低环境运行过，才能记为 `pass`：

- clean macOS arm64；
- staged/bundled Python/Node/QMD；
- `/Applications` packaged App；
- 真实官方签名 Codex/Cursor；
- 真实模型下载；
- 真实 GitHub settings、secret isolation 和 Draft；
- 真实 `N-1 → N`。

Mock、fake store、source UDS、ad-hoc DMG 或 CI runner 不能替代这些条件。

## 7. 修改流程

### 7.1 定义范围

在开始前写清：

- 用户可见行为；
- 受影响 REQ；
- 相关 ADR；
- owning component；
- 数据/schema/迁移影响；
- 安全/隐私影响；
- 是否需要 QMD rebuild；
- 最低验证环境；
- 明确不做的内容。

### 7.2 更新迭代

每个 scoped change 都要更新活动 iteration：

- scope；
- tasks；
- acceptance；
- risk/rollback；
- validation log；
- changed files。

大型追加纵切可以像 R07–R12 一样建立子记录，但父迭代仍是状态权威。

### 7.3 更新追踪矩阵

行为链必须闭合：

```text
REQ → ADR → ITER/task → owned paths → VAL → evidence
```

以下变化必须更新 `traceability.md`：

- 新/变更需求；
- 新/替代 ADR；
- owner/path 变化；
- 验证 ID、最低环境、状态变化；
- evidence checkpoint。

### 7.4 Evidence

使用[证据规范](evidence/README.md)。至少记录：

- commit/tag/Actions run；
- OS/architecture/runtime；
- command；
- expected/actual；
- pass/fail/not-run；
- artifact digest；
- sanitized evidence location；
- failure injection/rollback；
- reviewer。

禁止：

- 把 dirty worktree 称为发布证据；
- 删除 skip 或把 skip 计入 pass；
- 为绿灯弱化 assertion；
- 上传 token、绝对私有路径、源码、auth cache、model 或用户数据。

### 7.5 文档同步

行为、设置、路径、恢复或限制变化时同一 PR 更新：

- 用户入口；
- [系统设计](../17-system-design.md)；
- [状态](status.md)；
- [TODO](todo.md)；
- 活动 iteration；
- traceability；
- component README；
- 必要的 Release notes。

避免在多个文档复制同一状态表；让它们链接 `status.md`。

## 8. 安全边界检查

### Renderer/Main

- renderer 不得获得 raw IPC、Node、filesystem、process、shell、updater 或任意 URL；
- preload 方法必须无歧义、typed、versioned；
- Main 必须复核 sender、payload、route、path、状态和大小；
- response/error 必须脱敏。

### Child process

- 不使用 shell；
- executable/argv 固定并做 identity 检查；
- 最小 env、bounded stdout/stderr、timeout/cancel、独立进程组；
- token/capability 不进 argv/env/disk/log；
- 只终止本次 PID；
- 非幂等结果未知时不 replay。

### Repository/data

- repository、Git metadata、Markdown、模型输出都不可信；
- 不执行 hook、filter、credential helper 或仓库代码；
- snapshot 不包含未提交 worktree；
- 路径、symlink、owner、mount、大小、file type 和 portable collision 均验证；
- 不把 private source、snapshot、backup、model cache、index 加入 Git。

### Release/update

- PR/fork/source job 不引用 release secret；
- W13 前不配置 production controls/credentials，也不创建 release tag/Draft；
- W11 删除前，相同 tag 的独立 GHCR workflow 可能公开镜像，因此当前禁止 tag；
- W15 formal desktop tag 路径只能到 Draft；
- W13 checkpoint → formal tag 只允许 public pins/release metadata/version diff；exact Draft 必须
  重新运行完整 cutover/absence，不能复用 engineering evidence；
- promotion 必须从 trusted `main`；
- fixed Release ID 和 candidate digest；
- public trust pins 入库，private material 永不入库；
- source/unprovisioned 必须 fail closed；
- manual Release page 不等于 signed updater success。

## 9. Schema 和迁移

数据库使用 `PRAGMA user_version`、schema version 和 migration lock；“只有
`CREATE TABLE IF NOT EXISTS`”已不是事实。

Schema 变更必须：

1. 增加 migration；
2. 定义 old → new、重复运行和并发启动；
3. 保留或明确拒绝 downgrade；
4. 更新 `runtime/version.json` 中 schema；
5. 添加 corrupt/interrupt/rollback 测试；
6. 更新 backup/restore 与 data count；
7. 记录是否触发 QMD stale/rebuild；
8. 不在生产数据上首次试验。

Legacy → desktop migration 已由 ADR-0015 取代，不开发 importer/converter。当前 Electron schema
migration 只能处理明确支持的 desktop layout；unknown/legacy layout 必须 fail closed，且不能
静默覆盖或删除旧数据。

## 10. 依赖与生成文件

- 使用 lockfile 和固定 action commit；
- production install 禁止隐式下载/构建；
- runtime staging、artifact、cache、model、index、user data 不入库；
- public schema/lock/policy/notices/build script 应入库；
- 修改 Python/Node/QMD/PyInstaller/Electron/native addon 时重跑 provenance、license、
  SBOM、Mach-O/dylib/RPATH 和 tamper tests；
- 不提交私有 update key、P12、password、credential bundle 或 Keychain export。

## 11. Commit 与 PR

建议一个逻辑变更一个 commit 或一组容易审查的 commits。PR 使用仓库模板，至少说明：

- task/REQ/ADR/VAL；
- before/after；
- user/data/security impact；
- tests 和 exact results；
- `not-run` 及原因；
- rollback；
- changed docs；
- QMD rebuild；
- release disposition。

PR 中不要写“all tests pass”，除非列出 aggregate 实际覆盖。明确指出 QMD worker、
guide-site、packaged 或 physical 是否未包含。

合并前：

```bash
git diff --check 3eff97d97b2de4484d568bab5ac96d63830c79ee HEAD
python3 tools/check_markdown_links.py
python3 tools/check_version_sync.py
python3 -B tools/check_ci_coverage.py
python3 -B tools/check_w01_evidence.py
python3 -B tools/check_pre1_work_plan.py
```

再按改动运行 focused + aggregate。CI 必须在最终 head 上重新通过；head 变化后旧 approval/
evidence 不能自动代表新 bytes。

## 12. 常见陷阱

1. **把 `make install` 当 desktop**：它进入 legacy Docker。
2. **把 source mode 当 DMG**：它借用开发机 runtime。
3. **把 `mcp/` 当 desktop companion**：前者是 legacy gateway。
4. **把 `make test` 当全量**：它不覆盖 Desktop/QMD/Host Runner/governance。
5. **绕过 QMD source runner**：直接 `node --test` 不具备 lifecycle/network/model fail-closed 证据。
6. **使用 native bootstrap**：它属于待删除 browser surface；Electron CI/source 用 `backend/.venv`。
7. **运行 Compose/legacy installer**：它们已 unsupported，且可能改变旧 data/volume。
8. **移动 release tag**：immutable policy 下不可恢复；container workflow 删除前禁止创建新 tag。
9. **把 Draft 当公开授权**：它只是物理测试候选。
10. **自动 fallback provider**：commit 后绝对不能换 CLI 重放。
11. **把 QMD failure 当 publish failure**：published page 仍有效，query lexical fallback。
12. **直接覆盖 legacy 数据**：不提供迁移；unknown/legacy layout fail closed 且不自动删除。
13. **改写 Accepted ADR**：使用 superseding ADR 保留历史。
14. **记录“当前工作树 pass”**：必须绑定 commit/Actions。
15. **把 W02/W03 engineering artifact 当正式候选**：它们禁止 tag/upload/Draft/Release，不能
    提升 secret/pack/install/release/update gate。

## 13. 新贡献者首个 PR 建议

1. 从 [TODO](todo.md) 选择无并发 owner 的 task；
2. 在 issue/PR 描述中声明 task ID 和范围；
3. 建立独立 branch；
4. 先跑 focused baseline；
5. 修改实现与同一份文档/traceability；
6. 运行 focused + aggregate；
7. 把无法运行的 gate 留作 `not-run`，不要伪造；
8. 开 Draft PR，等待 CI；
9. 处理 review 后重新验证最终 head；
10. 在最终 PR head 上同步任务状态、status、traceability 与 evidence，再重跑 CI；
11. 只有确需补记最终 merge commit 时，合并后才开一个小型 follow-up 文档 PR。

若不确定下一项，从[状态页的 ready now 列表](status.md#下一步工作分组)选择；标为
dependency-blocked 或 admin-blocked 的任务不能仅凭兴趣直接开工。
