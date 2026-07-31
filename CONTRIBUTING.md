# Contributing

Local Context Forge 同时包含 Electron desktop、Python domain、React renderer、QMD/MCP 和
legacy Docker。开始前先读：

1. [AGENTS.md](AGENTS.md)
2. [项目状态](docs/development/status.md)
3. [开发者手册](docs/development/contributor-handbook.md)
4. [活动迭代](docs/development/iterations/0002-bundled-runtimes.md)
5. [详细 TODO](docs/development/todo.md)

当前结论是 **source merge GO / public release NO-GO**。Source CI 不能证明 DMG、签名、
真实 Codex/QMD、干净用户或跨版本更新。

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

## 选择开发模式

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

Native API/MCP/Web：

```bash
./scripts/macos-bootstrap.sh --native
make dev-native
```

Legacy Docker/Web：

```bash
LCF_CONTROL_BIN="$(pwd -P)/scripts/lcf"
lcf_managed() {
  env -i HOME="$HOME" PATH="$PATH" "$LCF_CONTROL_BIN" "$@"
}

lcf_managed install
lcf_managed doctor
lcf_managed status
```

`make install`/`install.sh` 不是 Electron 安装器。当前 `scripts/lcf` 尚未自行隔离调用者
shell/Compose 覆盖；受管 legacy 实例使用上述最小环境入口，不要用直接调用或裸 Compose
绕过已记录的 Docker context 和 `.lcf/runtime.env`。详见
[部署总手册](docs/18-deployment-operations.md#22-安装)。

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
make ci-python
make ci-web
make desktop-ci
```

QMD worker 当前不在 `make ci-source`：

```bash
npm --prefix desktop/workers/qmd ci
npm --prefix desktop/workers/qmd test
```

文档与版本：

```bash
python3 tools/check_markdown_links.py
python3 tools/check_version_sync.py
git diff --check
```

Legacy 变更还需：

```bash
docker compose config --quiet
./scripts/smoke-test.sh
```

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

最终 head 发生变化后重新运行 CI。Release tag 是统一产品事件：同一个 `vX.Y.Z` 会触发
container SemVer 和 desktop Draft，不能作为只发布一个组件的随意 tag。
