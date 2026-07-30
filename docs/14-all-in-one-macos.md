# M4 Pro 24 GB：all-in-one 部署

## 最短路径

准备好 Docker Desktop 或 Colima。推荐在 Mac 上完成：

```bash
codex login
codex login status
```

这不是安装控制面的硬前提：首次未指定 provider 且没有已登录的 Codex/Cursor 时，安装器会清楚
提示并进入 `mock` 演示模式。mock 可验证部署、队列、审核和查询，但不生成生产级 Wiki。

解压后只运行：

```bash
./install.sh
```

不想输入命令时，解压后双击 `install.command` 即可；它会运行同一个安装器，并在
失败时保留终端窗口显示下一步。缺少 Python 3 或 `jq` 且已安装 Homebrew 时，安装器会
自动补齐；Docker runtime 与第三方 CLI 仍需用户明确安装。

不要用 `sudo` 运行：安装器会拒绝 root。Docker context、`~/Library/LaunchAgents` 与已登录 CLI
都属于当前图形用户，用 sudo 会指向错误的账号边界。

安装器不会自动安装 Codex/Cursor，不会读取或复制 token，不会 mount
`~/.codex`、Cursor 配置或 Docker socket，也不会更改当前 Docker context。

## 安装阶段

1. 检查非 root 的 Darwin/arm64、内存、至少 10 GiB 磁盘余量、Python 3.9+、Git、curl、tar、
   `rsync` 与 `jq`；
2. 读取当前 Docker context，只启动该 context 对应的 Docker Desktop 或已有
   Colima profile；
3. 检测 Codex/Cursor 的绝对路径，并用各自的 `status` 命令检查登录状态；
4. 原子生成 mode `600` 的 `.lcf/runtime.env`；
5. 创建 mode `700` 的 `data`、`imports`、`backups` 与 runner spool；
6. `auto`/`codex_cli`/`cursor_cli` 模式生成并校验
   `~/Library/LaunchAgents/dev.local-context-forge.host-runner.plist`；
7. CLI 模式启动 host runner 并等待本次启动产生的新 heartbeat；`mock`/`ollama` 确认
   LaunchAgent 已卸载；
8. Compose build/up，等待 API、MCP、Web health；
9. 运行 smoke test、保存安装状态并打开 Web。

重复执行会保留现有 runtime 设置，不会删除源码快照、Wiki、SQLite、imports 或
backups。失败时恢复之前的 runtime env/LaunchAgent 并尽力恢复原服务；数据目录从不
参与部署回滚。断电或 `SIGKILL` 留下的 deploy lock 记录 owner PID；owner 不再存活时，下次
安装会自动清理空的旧锁，意外文件则 fail closed，要求人工检查。

## Docker Desktop 与 Colima

自动模式使用 `docker context show` 返回的当前 context。若 Docker Desktop 已安装但
daemon 未启动，安装器会打开 Docker.app 并等待；若当前 context 是已有 Colima，
会执行 `colima start`，但不修改 CPU、内存和磁盘。

同时安装两种 runtime 时，先由用户明确选择：

```bash
docker context ls
docker context use colima       # 或 desktop-linux
./install.sh --runtime colima   # 或 docker-desktop
```

不静默切换 context 可以避免把镜像、容器或数据落到错误 VM。新建 Colima profile 的
M4 Pro 24 GB 起点可以是 6 CPU、8 GiB 内存、80 GiB 磁盘；安装器不修改已有 profile。

## Host runner spool

runner 使用同一个 `data` bind mount 中的目录通信：

```text
data/runner/
├── inbox/       worker 原子提交请求
├── working/     LaunchAgent 已 claim 的请求
├── outbox/      成功或失败响应
├── failed/      被拒绝/失败的原始请求
└── heartbeat.json
```

唯一任务类型是 `wiki_v1`。请求顶层只接受：

- `id`
- `task`
- `provider`：`auto`、`codex_cli` 或 `cursor_cli`
- `evidence` JSON object
- `output_schema` JSON object
- 可选 `model`
- `timeout_seconds`，范围 30–3600 秒

未知字段（包括 `command`、`path`、自定义 prompt）、超大文件、symlink、坏 JSON、
越界 timeout 都拒绝。CLI 工作目录只包含 `evidence.json` 与 `schema.json`，输出会
再次按 schema 验证。

`auto` 的规则刻意保守：

1. Codex binary 存在且 `codex login status` 成功：使用 Codex。
2. Codex 在任务开始前不存在或未登录：可改用已安装的 Cursor。
3. Codex 一旦开始执行，任何失败都直接结束本任务，不再 fallback。

第三条避免超时或响应丢失时重复消费两套订阅额度。每个 response 都记录
`requested_provider`、`effective_provider` 与 `fallback_reason`。

## Cursor 边界

Cursor CLI 当前仍是 beta，print/headless 模式具备 Agent 工具能力。LCF 使用
`cursor-agent -p --output-format json`，并且绝不加 `--force`。这仍不是强隔离；
高安全项目不要把 Cursor 设成自动备用。

## 生命周期

```bash
./scripts/lcf status
./scripts/lcf doctor
./scripts/lcf logs
./scripts/lcf restart
./scripts/lcf stop
./scripts/lcf start
./scripts/lcf down
```

`stop` 保留容器；`down` 删除容器但不删除 bind-mounted 数据。停止 runner 时会删除旧 heartbeat，
下次启动必须等到新的 heartbeat 才通过 doctor。

## 更换生成 provider

重复运行安装器是受支持的切换方式：

```bash
./install.sh --provider codex_cli --no-open
./install.sh --provider cursor_cli --no-open
./install.sh --provider mock --no-open
./install.sh --provider ollama --no-open
```

显式 `codex_cli`、`cursor_cli` 或 `auto` 在没有相应登录时会停止并保留原配置，不会静默改成
mock。只有**首次、未指定 provider** 且没有可用 CLI 时自动选择 mock。切到 mock/Ollama 会卸载
LaunchAgent；切回 CLI 会重新写入绝对 binary 路径并等待 provider heartbeat。

## 备份与恢复

在线创建一致备份：

```bash
./scripts/lcf backup
```

脚本会 drain 新任务，拒绝仍在 running/cancelling 的任务，短暂停止 API/MCP，备份 SQLite、
Wiki、snapshot、facts、proposal 与 queued request，然后恢复服务。备份包含完整私有源码，必须
放在 FileVault 或其他加密介质；`.lcf/runtime.env`、CLI 登录和 `imports/` 不在数据备份中。

恢复前停止服务，并把现有数据移入可回退的 quarantine：

```bash
./scripts/lcf stop
./scripts/lcf restore \
  --archive ./backups/lcf-backup-YYYYMMDDTHHMMSSZ.tar.gz \
  --target ./data \
  --replace
./scripts/lcf start
./scripts/lcf doctor
```

restore 默认要求相邻 `.sha256`，不会直接删除旧 data；详细边界见
[备份与恢复](09-backup-restore.md)。

卸载服务但保留全部数据：

```bash
./scripts/lcf uninstall
```

该命令执行 Compose `down`（不带 `-v`）、卸载当前用户 LaunchAgent，并保留
`data`、`imports`、`backups` 与 `.lcf`。它还删除派生 heartbeat，但不删除 runner 中的请求/
结果审计。要重新启用，直接再次运行 `./install.sh`；若要彻底删除保留数据，先单独备份，再由
用户明确处理这些目录。

## 高级安装参数

```bash
./install.sh \
  --runtime docker-desktop \
  --provider codex_cli \
  --web-port 18080 \
  --api-port 18000 \
  --mcp-port 18001
```

可用值：

- runtime：`auto`、`docker-desktop`、`colima`
- provider：`auto`、`codex_cli`、`cursor_cli`、`mock`、`ollama`
- `--images build|ghcr`：从当前 checkout 构建，或拉取 GHCR 多架构预构建镜像
- `--image-tag TAG`：GHCR 标签，默认 `main`；稳定部署建议精确 semver 或 `sha-*`
- `--ghcr-owner OWNER`：GHCR 用户/组织，默认 `fredgnr`
- `--skip-build`：使用已有镜像
- `--no-open`：部署完成不自动打开浏览器

私有 GHCR 模式必须先让当前 Docker context 登录 `ghcr.io`；凭据进入 Docker credential
store，不进入 runtime env。详见 [GitHub Actions 与 GHCR](15-github-actions-ghcr.md)。

所有端口仍绑定 `127.0.0.1`。本版本没有认证/ACL/TLS；不要通过修改 bind host
直接暴露到局域网或公网。

## Doctor

`./scripts/lcf doctor` 只读检查 runtime env 权限、记录的 Docker context、
API/MCP/Web health、host runner heartbeat 与 CLI provider 状态；mock/Ollama 还会确认
LaunchAgent 没有加载。Heartbeat 不包含用户名、邮箱、token、套餐或完整 CLI 输出。

LaunchAgent 的 plist 与日志目录仅当前用户可读写；容器只看到有界 JSON spool，看不到
`~/.codex`、Cursor 配置、API key 或 Docker socket。runner 请求不接受任意 command/path/prompt，
CLI 在临时目录执行。它仍与当前 macOS 用户拥有相同账号权限，因此不要把 loopback Web/API
暴露给不受信任用户。
