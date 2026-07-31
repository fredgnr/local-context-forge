# 开发者手册

本文是新贡献者的完整入口。根 [CONTRIBUTING.md](../../CONTRIBUTING.md) 只保留快速清单；
系统设计、当前状态和剩余任务分别见：

- [系统设计](../17-system-design.md)
- [状态快照](status.md)
- [详细 TODO](todo.md)
- [需求—决策—验证矩阵](traceability.md)

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

缺少任一工具时，先按该工具的官方安装方式补齐。`./scripts/macos-bootstrap.sh --native`
会准备 native browser 开发环境，但不是 Electron 开发机、正式 bundle 或 CI 工具链安装器。
正式 bundle 的 Python 3.13.14 和 Node 22.23.2 由 release workflow 的锁定供应链负责，不应
替换本节的 source 工具。

## 2. 必读顺序

1. 根 [AGENTS.md](../../AGENTS.md)；
2. [开发索引](README.md)和[状态快照](status.md)；
3. [迭代索引](iterations/README.md)与活动
   [ITER-0002](iterations/0002-bundled-runtimes.md)；
4. 你的改动对应的 R07–R11 记录；
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
| `web/src/` | React renderer 与 browser UI | Web tests/build、desktop bridge |
| `backend/app/` | Domain、SQLite、queue、source、Wiki、query | Backend tests、schema/data impact |
| `backend/packaging/` | PyInstaller、locks、notices | macOS staging、SBOM/native closure |
| `mcp/` | **legacy** HTTP/stdio gateway | legacy API/MCP tests，不是 desktop companion |
| `host_runner/` | **legacy** 宿主 CLI spool | legacy provider/security |
| `docker/`、`docker-compose.yml` | **legacy** containers | container CI、migration compatibility |
| `scripts/` | legacy deploy/backup/restore/native dev | shell safety、real context/data |
| `runtime/` | 跨层版本、schema、public trust locks | version sync、packaging fail-closed |
| `docs/adr/` | Accepted decisions | 架构历史，不是完成证据 |
| `docs/development/` | 状态、迭代、证据、TODO | 每个 scoped change |
| `guide-site/` | 已部署使用说明站点源码 | 独立 build/test/deploy；当前不在主 source aggregate |

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

### 4.1 Native API/MCP/Web

用于不经过 Electron 的领域/UI 开发：

```bash
./scripts/macos-bootstrap.sh --native
make dev-native
```

该脚本使用仓库根 `.venv` 和 `.native` QMD。它是 native browser 配置，不等同于 desktop
private UDS。

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

### 4.3 Legacy Docker/Web

需要验证旧部署时优先：

```bash
LCF_CONTROL_BIN="$(pwd -P)/scripts/lcf"
lcf_managed() {
  env -i HOME="$HOME" PATH="$PATH" "$LCF_CONTROL_BIN" "$@"
}

lcf_managed install
lcf_managed doctor
lcf_managed status
```

开发中的临时 Compose 可以使用：

```bash
docker compose config --quiet
docker compose up -d --build
./scripts/smoke-test.sh
```

但已配置的受管实例必须通过上面的 `lcf_managed` 使用 `scripts/lcf`。当前脚本会读取 Docker
context 和 `.lcf/runtime.env`，却未自行清除优先级更高的 shell/Compose 变量；直接调用仍可能
选错 project/data/port。详见[部署总手册](../18-deployment-operations.md#22-安装)。

### 4.4 正式打包

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
| QMD worker | worker test file | `npm --prefix desktop/workers/qmd test` |
| MCP companion | MCP Desktop tests | `make desktop-ci`；packaged gate仍 `not-run` |
| Provider | attempt/discovery/process tests | Backend + Desktop + Web |
| Local source | localSource + source_security | Backend + Desktop + Web |
| Update/release | update/release policy focused | Desktop + Backend policy + YAML/shell audit |
| Legacy Docker | relevant Backend/Web/shell | `docker compose config --quiet` + smoke |
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
make ci-web
make desktop-ci
```

当前缺口：`make ci-source` 不运行 QMD worker tests，也不运行 `guide-site` tests。涉及这些
路径时必须显式运行：

```bash
npm --prefix desktop/workers/qmd ci
npm --prefix desktop/workers/qmd test

npm --prefix guide-site ci
npm --prefix guide-site test
```

使用前先核对 `guide-site/package.json` 的实际 script；不要凭本页假设不存在的命令。

### 6.2 单独治理检查

```bash
python3 tools/check_markdown_links.py
python3 tools/check_version_sync.py
git diff --check
```

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

大型追加纵切可以像 R07–R11 一样建立子记录，但父迭代仍是状态权威。

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
- desktop release 的 tag 路径只能到 Draft；相同 tag 的独立 GHCR workflow 可能已公开镜像；
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

Legacy → desktop migration 是独立事务，不得被普通 DB schema migration 偷偷代替。

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
git diff --check
python3 tools/check_markdown_links.py
python3 tools/check_version_sync.py
```

再按改动运行 focused + aggregate。CI 必须在最终 head 上重新通过；head 变化后旧 approval/
evidence 不能自动代表新 bytes。

## 12. 常见陷阱

1. **把 `make install` 当 desktop**：它进入 legacy Docker。
2. **把 source mode 当 DMG**：它借用开发机 runtime。
3. **把 `mcp/` 当 desktop companion**：前者是 legacy gateway。
4. **把 `make test` 当全量**：它不覆盖 Desktop/QMD/Host Runner/governance。
5. **忘记 QMD worker**：当前不在 `make ci-source`。
6. **混用 venv**：native bootstrap 用根 `.venv`，Electron CI/source 用 `backend/.venv`。
7. **裸 Compose 管理已安装实例**：可能用错 context/env/data。
8. **移动 release tag**：immutable policy 下不可恢复；tag 同时影响 container/desktop。
9. **把 Draft 当公开授权**：它只是物理测试候选。
10. **自动 fallback provider**：commit 后绝对不能换 CLI 重放。
11. **把 QMD failure 当 publish failure**：published page 仍有效，query lexical fallback。
12. **直接覆盖 legacy 数据**：迁移事务尚未完成。
13. **改写 Accepted ADR**：使用 superseding ADR 保留历史。
14. **记录“当前工作树 pass”**：必须绑定 commit/Actions。

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
