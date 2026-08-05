# Contributing

Local Context Forge 的唯一目标产品面是 Electron desktop；仓库暂时还包含待解耦、待删除的
legacy Docker/browser/public-HTTP 代码。legacy 文件只用于 removal inventory 和回归定位，
不构成可选择的开发、部署或发布模式。开始前先读：

1. [AGENTS.md](AGENTS.md)
2. [项目状态](docs/development/status.md)
3. [开发者手册](docs/development/contributor-handbook.md)
4. [活动迭代](docs/development/iterations/0002-bundled-runtimes.md)
5. [详细 TODO](docs/development/todo.md)

当前结论是 **W01 remediation in progress / PR merge blocked / public release NO-GO**。旧 PR #20
candidate 的 technical source 虽为 `pass`，independent acceptance 是 `fail`，canonical activation
为 `not-eligible`。修复 candidate 的 PR/source、independent acceptance、canonical-main source 与
canonical activation 必须分开；Source CI 不能证明 DMG、签名、真实 Codex/QMD、干净用户或
跨版本更新。

## 开发机前置检查

源码开发不会自动安装工具链。推荐用与 CI 一致的 Python 3.12、Node 24 和
`uv==0.11.29`；Backend 声明的最低 Python 是 3.11。macOS 还需要 Xcode Command Line
Tools（提供 `make` 等基础工具）。先运行：

```bash
xcode-select -p
python3 --version
uv --version
node --version
npm --version
make --version
```

若任一命令缺失，先按该工具的官方安装方式补齐；不要把 legacy
`scripts/macos-bootstrap.sh` 当成完整的 Electron 开发机 bootstrap。正式打包使用另一组固定
runtime，详见[开发者手册](docs/development/contributor-handbook.md#5-工具链版本矩阵)。

## Electron-only 源码开发

Electron source：

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

不要使用 `make dev-native`、`scripts/macos-bootstrap.sh --native`、`make install`、
`install.sh`、`scripts/lcf` 或裸 Compose 建立新的开发/测试实例。这些入口属于
[legacy retirement manifest](docs/development/legacy-retirement.md) 的 `remove` / `split`
范围。removal PR 必须遵循 [ADR-0016](docs/adr/0016-pre1-incremental-retirement-engineering-package.md)
和 [W01–W16 work plan](docs/development/work-plan.md)：W01 修复 candidate 的三个 PR/source
technical gate 全部通过、exact final head 获得 independent acceptance、被验收 candidate 合入
canonical `main`，且 resulting exact main 的 source run 成功后，才建立 W02 packaged smoke；再按
slice 做 caller inventory、split、before/after package、
absence 与 protected presence。shared/必需 Electron capability 要有 replacement；纯 legacy-only
unsupported capability 可使用受限 no-replacement disposition。W13 才运行工程 checkpoint 的最终
聚合 cutover/absence；formal Draft 还需独立 continuity 复验。在任何阶段都不得操作用户现有
container、volume、data、backup 或远端 GHCR package。

## 变更规则

- 从 [TODO](docs/development/todo.md) 认领 task ID 和 owning component。
- 阅读活动 iteration 和所有相关 Accepted ADR。
- Desktop/跨进程变更使用仓库的 desktop development skill；证据/ADR/状态变更使用
  change traceability skill。
- 保持 immutable snapshot、proposal-before-publish、source refs 和 revision gate。
- Renderer 不获得任意文件、进程、网络、凭据、更新或原始 IPC 能力。
- Provider commit 后不 replay、不从 Codex 自动切 Cursor。
- MCP 保持只读两个工具；管理能力属于 UI/Main/API。
- 不提交 credential、auth cache、private source、model、index、backup 或 user data。
- 架构、安全、数据迁移、打包或发布决定变化时新增 superseding ADR，不改写历史决定。
- 同一 PR 更新活动 iteration、traceability、状态、TODO 和受影响用户/组件文档。

## 验证

先跑 focused tests，再跑受影响 aggregate：

```bash
make ci-source
make ci-python
make ci-qmd-worker
make ci-web
make desktop-ci
```

`ci-qmd-worker` 使用精确 Node 22.23.2；依赖安装禁用 lifecycle scripts，测试阶段隔离
HOME/XDG/tmp、拒绝外部网络/子进程，并拒绝模型文件生成。model scan 只覆盖 isolated
`HOME`、`XDG_CACHE_HOME`、`XDG_CONFIG_HOME`、`XDG_DATA_HOME` 和 `TMPDIR`；它明确不扫描
repository worktree 或 global tmp。它只证明 QMD source tier，不能提升 native/model/packaged
gate。

`guide-site/**` is excluded from `make ci-source` and Desktop source CI；机器声明见
`.github/ci/source-coverage.json`。本 checkout 缺少可验证的 hosting identity 和独立
commit-bound pipeline，因此站点保持 `external-blocked` / unvalidated，不能冒充已覆盖。

文档与版本：

```bash
python3 tools/check_markdown_links.py
python3 tools/check_version_sync.py
python3 -B tools/check_ci_coverage.py
python3 -B tools/check_w01_evidence.py
python3 -B tools/check_pre1_work_plan.py
python3 -B -m unittest discover -s tools/tests -p 'test_*.py'
git diff --check origin/main HEAD
```

Legacy 解耦/删除变更还必须执行实施时固定的 affected Electron 回归（或合格 pure-legacy
unsupported disposition）、fresh before/after packaged smoke、slice absence 与 protected
presence。最终 W13 才运行 aggregate
`tools/check_legacy_absence.py`（创建前为 `not-run`）和完整 M4 cutover。不要再用 Docker smoke
证明目标产品正确；它只能证明已弃用运行面仍可运行，不能解除删除门禁。

记录 exact command、commit、环境、pass/fail/skip 和所有 `not-run`。证据格式见
[evidence README](docs/development/evidence/README.md)。Mock/source 不得替代 packaged/
physical gate。

## Pull request

使用仓库 PR 模板，并说明：

- task/REQ/ADR/ITER/VAL；
- user-visible behavior；
- data/schema/migration；
- security/privacy；
- tests 和 exact results；
- `not-run` 与解除条件；
- failure injection/rollback；
- QMD rebuild；
- source merge 与 public release disposition。

最终 head 发生变化后重新运行 CI。目标 release tag 只服务 desktop Draft → physical review →
trusted-main promotion。当前 `container-images.yml` 尚未删除，因此在
W11 release slice、W13 final gates、W14 controls 和 W15 credentials/pins 完成前禁止创建新
release tag；
不得把现存的双触发行为解释成受支持的 container 发布合同。
