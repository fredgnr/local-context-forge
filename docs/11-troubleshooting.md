# 排错手册

## 一键收集非敏感状态

```bash
docker compose ps
docker compose logs --since=10m --no-color api mcp web
curl -sS http://127.0.0.1:8000/api/health | jq
curl -sS http://127.0.0.1:8001/health | jq
curl -sS http://127.0.0.1:8080/healthz
docker compose exec api qmd status
```

分享日志前搜索并删除 token、私有 URL、用户名与源码正文。

## Compose 构建失败

### QMD / npm

症状：Node 版本不足、native module/SQLite 错误。

检查：

```bash
docker compose build --no-cache api
```

镜像应使用 Node 22+，安装 Linux SQLite 运行库与构建依赖。不要在宿主的 `node_modules` 和容器之间复用。

### Python dependency

```bash
docker compose build --progress=plain api mcp
```

确认 `backend/requirements.txt`、`mcp/requirements.txt` 存在，且 MCP SDK 固定在已验证的 1.x 版本。2.x 升级要先做兼容测试。

## Web 能打开但 API 报错

```bash
curl --fail http://127.0.0.1:8000/api/health
docker compose exec web wget -qO- http://api:8000/api/health
```

- 第一个失败：API 未启动或端口冲突。
- 第一个成功、第二个失败：Compose network/DNS。
- 两个成功但浏览器失败：nginx `/api/` proxy、缓存或 base URL。

Vite 的 `VITE_API_BASE` 是构建期变量；修改后要重建 Web。

## MCP unhealthy

```bash
curl --fail http://127.0.0.1:8001/health
docker compose logs --since=10m mcp
docker compose exec mcp \
  python -c 'import urllib.request; print(urllib.request.urlopen("http://api:8000/api/health").read())'
```

检查：

- `MCP_TRANSPORT=streamable-http`
- `MCP_HOST=0.0.0.0`（容器内）
- `MCP_PORT=8001`
- `MCP_PATH=/mcp`
- `BACKEND_URL=http://api:8000`

宿主端仍只绑定 127.0.0.1。

若 health 正常但 `query-docs` 提前超时，先检查旧 `.env` 是否还保留了较小值；当前
`BACKEND_TIMEOUT_SECONDS` 默认 660 秒，只控制 MCP gateway → FastAPI 的 HTTP 等待，高于冷
hybrid 查询的 600 秒后端上限；它不会延长 Codex/IDE 作为 MCP host 的 tool deadline。Codex 还要
在 `~/.codex/config.toml` 独立配置：

```toml
[mcp_servers.local-context-forge]
url = "http://127.0.0.1:8001/mcp"
tool_timeout_sec = 660.0
```

先按本文“QMD 首次查询慢”直连 API warm-up；修改 gateway timeout 后要
`docker compose up -d --force-recreate mcp` 才会生效。

## ingest 失败

### Git ref 不存在

```bash
git ls-remote --heads --tags REPO_URL
```

使用完整 tag/branch/commit。私有仓库不要把 token 放到命令历史；优先本地预 clone。

### 本地 Git 不是仓库顶层

症状包含 `A local Git source must be the repository top level`。LCF 用
`git rev-parse --show-toplevel` 解析真正根目录；不能把 monorepo 的 package 子目录直接登记为
Git source。若只分析子树，把它复制到 allowlist 中一个不含父 `.git` 的独立目录，再以普通目录和
`ref=HEAD` ingest。

若错误提到 standalone `.git`、linked worktree、gitdir、commondir、alternate object store 或
metadata/object path escapes，说明本地 Git 元数据会间接访问授权根之外。普通独立 `.git` 目录
可以导入；其他布局先完整物化 worktree，再导出为不含父 `.git` 的普通目录。LCF 还会清理父进程
继承的全部 `GIT_*` 覆盖，不能用 `GIT_DIR`/`GIT_OBJECT_DIRECTORY` 绕过这个边界。

### submodule、LFS pointer 或便携路径碰撞

Git archive 不会替你 materialize submodule/LFS，并会拒绝两个成员经 NFC + casefold 后相同。
在宿主完整 checkout、运行 `git submodule update --init --recursive` 与 `git lfs pull`，然后把
所需 worktree/子树复制到不含父 `.git` 的 `imports/` 目录。不要关闭校验，也不要把 LFS pointer
当源码。

### 仓库太大

- 使用明确 ref。
- 检查最终 snapshot 的文件数/总字节限制；远端 clone 临时对象传输目前没有同等硬限。
- 排除 vendor、build、model、fixture 二进制。
- 拆成多个 library，而不是无限提高限制。

### ctags 不支持语言

事实抽取会退化。检查：

```bash
docker compose exec api ctags --version
docker compose exec api ctags --list-languages
```

正常调用固定包含 `--options=NONE --links=no`，不会读取仓库/用户 options 或跟随链接。不要为支持
某个语言而向被分析仓库加入可执行 ctags 配置；应在受控镜像中升级 Universal Ctags 并回归测试。

仍可用 README/tests/examples 建 Wiki，但 API 完整性应标记为 degraded。

## Ollama 连接失败

Windows：

```powershell
Get-Process ollama -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 11434 -State Listen
Get-NetFirewallRule -DisplayName "Local Context Forge - Ollama*"
ollama list
```

Mac：

```bash
ping WINDOWS_PRIVATE_IP
curl --fail http://WINDOWS_PRIVATE_IP:11434/api/tags
```

容器：

```bash
docker compose exec api \
  curl --fail http://WINDOWS_PRIVATE_IP:11434/api/tags
```

常见原因：

- Ollama 没有在设置环境变量后重启。
- Windows 网络被设成 Public，而规则只允许 Private。
- Mac DHCP 地址变化，不再匹配 firewall RemoteAddress。
- Windows IP 变化，`.env` 仍是旧地址。
- VPN/防火墙阻断跨网段。

不要为排错把规则永久改为 Any；临时测试后也必须收紧。

## Ollama OOM 或很慢

```powershell
nvidia-smi
ollama ps
```

按顺序处理：

1. 并发降到 1。
2. 把 `LCF_MAX_MODEL_EVIDENCE_BYTES` 降到约 18–24 KiB，并相应降低 `LCF_MAX_MODEL_PAYLOAD_BYTES`；不要误改只控制持久 facts 的 `LCF_MAX_EVIDENCE_BYTES`。
3. 上下文降到 8K。
4. 选更小/更低量化模型。
5. 关闭占显存程序后重启 Ollama。

模型在系统 RAM offload 能运行不代表速度适合批量任务。

## 模型输出不是合法 JSON

- 当前 job 只保留脱敏错误，不持久化 raw model output；在受控、短期、按源码敏感级别保护的调试环境复现，避免把完整输出写进普通日志。
- 确认 generator 使用结构化输出/明确 schema。
- 缩小单次页面任务。
- 降低自由叙述，禁止 Markdown code fence 包住 JSON。
- 最多做有限次数 repair；仍失败就进入人工状态。

不要用正则“抠出一个看似 JSON 的片段”后直接发布。

## source_ref 验证失败

原因可能是：

- 模型编造路径/行号。
- evidence 与 snapshot sha 不一致。
- 文件在生成期间被覆盖（说明不可变约束失效）。
- 行号超出 snapshot 中该文件的实际范围。

处理：拒绝 proposal，检查 `source_sha`、snapshot 文件与 evidence manifest。当前会验证每条
引用属于该 provider 生成时实际可见的 evidence/symbol 行范围，也会检查 snapshot SHA、路径、
敏感文件、symlink 与行号；但还没有逐引用 content hash 或语义级 claim-support 校验。不要把
“引用来自允许 evidence”直接等同于“声明已被这些行证明”，也不要简单关闭现有引用检查。

## QMD 首次查询慢

首次全局重建会下载/加载 embedding GGUF；第一次 hybrid 查询还可能加载 reranker 与
query-expansion 模型。先查看系统状态：

```bash
curl --fail http://127.0.0.1:8000/api/system/status |
  jq '.embedding'
```

若 `hybrid_ready=false`，在 Web 的“系统设置”提交全局索引重建，或用 API：

```bash
curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d '{}' \
  http://127.0.0.1:8000/api/rebuilds | jq
```

重建是持久 FIFO job，可在任务页查看排队位置；API/主机重启不会丢失 queued job。系统会注册
完整的 published corpus，并执行全局 `qmd embed -f`。确保当前 runtime 的 cache 可写且磁盘
足够。不要直接运行 QMD write CLI，它会绕过全局 writer lock。Docker on macOS 可能走 CPU；
追求性能可使用原生模式。

索引重建不调用 Codex/Cursor，不消耗 LLM 额度；只有重新采集仓库才会生成新提案。重建成功且
`hybrid_ready=true` 后，再用直连 API warm-up：

```bash
LIBRARY_ID=/local/acme-widget
curl --fail-with-body --max-time 650 \
  -H 'Content-Type: application/json' \
  -d "$(jq -n \
    --arg library_id "$LIBRARY_ID" \
    '{library_id:$library_id,query:"create client timeout",limit:1}')" \
  http://127.0.0.1:8000/api/query |
  jq '{engine, hits: (.results | length)}'
```

预期 `engine` 是 `qmd-hybrid`。若仍是 `lexical`，先检查 desired/active model、
corpus/indexed revision 和最近 rebuild job 的错误，不要只提高 timeout。Web query 与 MCP
backend timeout 都是 660 秒，API 内部 hybrid QMD 上限为 600 秒；这些不是同一层设置。

## QMD 查询无结果

先区分“没有已发布内容”和“全局 profile 未就绪”：

```bash
curl --fail http://127.0.0.1:8000/api/libraries | jq
curl --fail http://127.0.0.1:8000/api/system/status |
  jq '.embedding'
```

- library/version 没有 fully published 页面：回到审核页完成整版发布。
- `status=stale/failed` 或 revision 不一致：修复错误后重试原 rebuild job，或提交新的全局重建。
- `hybrid_ready=false`：系统按设计使用 lexical fallback，不是数据丢失。
- lexical 也无结果：核对 library/version 和查询中的精确 API 符号。

资深用户可用 `docker compose exec api qmd status` 与 `qmd collection list` 做只读诊断，但不要
手工运行 `qmd update/embed`，也不要猜带 hash 的 collection 名。Compose/native 使用独立
config/cache；只让实际提供 query 的一种 runtime 运行。

### 更换 QMD 模型后仍像旧模型

默认 URI 是：

```dotenv
QMD_EMBED_MODEL=hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
```

不要通过临时 `export` 或直接编辑 QMD config 切换模型。Web 的“系统设置”会更新全局 desired
model，并立即把 profile 标为 stale；随后提交“重建全局索引”。也可先
`GET /api/settings` 取得 revision，再用带 `expected_revision` 的 `PATCH /api/settings`，最后
`POST /api/rebuilds`。只有 rebuild 成功且目标模型/corpus revision 仍匹配时，active model 才会
切换；此前查询保持 lexical fallback。

若界面仍显示旧模型，检查是否有并发设置修改导致 revision 冲突，以及 rebuild job 是否失败或
被取消。不要把 Compose 的 `data/qmd/config`/`cache` 与 native 的
`native-config`/`native-cache` 混用。

## Apple Silicon native QMD 编译错误

```bash
./scripts/macos-bootstrap.sh --native
PATH="$(brew --prefix node@22)/bin:$PATH" \
  ./.native/node_modules/.bin/qmd status
```

确认终端、Node 与 native addon 都是 arm64：

```bash
uname -m
node -p process.arch
```

避免在 Rosetta 和 arm64 之间复用 global npm 目录。

## 端口冲突

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:8001 -sTCP:LISTEN
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

在 `.env` 修改宿主端口，例如 `WEB_PORT=18080`，容器内部端口不变。

## SQLite locked

检查是否有 Docker 与原生服务同时写同一个 data：

```bash
docker compose ps
ps aux | grep -E '[u]vicorn|[m]cp_server|[q]md'
```

停止重复 writer。不要手工删除 WAL/SHM 文件。若持续异常，停止服务后备份并运行 SQLite integrity check。

## 恢复后页面在、查询不在

当前 API/runtime 正文来自 SQLite page 记录，Git Wiki 是审计副本，QMD 是派生索引。先确认 SQLite、Wiki 来自同一 backup manifest；然后重建索引：

```bash
curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d '{}' \
  http://127.0.0.1:8000/api/rebuilds | jq
```

在任务页检查重建 job；确认 `embedding.hybrid_ready=true` 后再运行 smoke test。重建期间查询
继续走 lexical，且该操作不调用 LLM。

如果只恢复或 `git revert` 了 Wiki，查询不会随之变化；当前没有自动 reconcile。应恢复同一备份的完整数据树，或通过新 proposal/publish 产生一致状态。

## 恢复后任务状态

job request 与 FIFO 顺序都在 SQLite 中。恢复后 `queued` 会继续排队；只有备份或中断时已经被
worker claim、处于 `running/cancelling` 且 owner lock 不再存活的任务，才会 fail closed 为
`status=failed, stage=orphaned`：

```bash
curl --fail http://127.0.0.1:8000/api/jobs/active | jq
curl --fail "http://127.0.0.1:8000/api/jobs?limit=200" |
  jq '[.[] | select(.stage == "orphaned")]'
```

若仍有幽灵 `running/cancelling`，显式重扫：

```bash
curl --fail-with-body -X POST \
  http://127.0.0.1:8000/api/admin/jobs/recover-orphans |
  jq
```

`preserved_jobs` 包括 queued 与 owner lock 仍被活 worker 持有的任务，不要抢占。
`recovered_jobs` 只表示未知副作用的执行中行已终态化，不表示工作成功。对任务详情中
`retryable=true` 的 failed/cancelled job，使用任务页“重试”或
`POST /api/jobs/{job_id}/retry`；系统创建带 `retry_of` 的新 job，保留旧审计记录。若原任务已经
产出 proposal，先审核/清理该提案，不要盲目重复采集，也不要直接编辑 SQLite。

## 备份提示已有任务但实际没有

`BACKUP_DIR/.lcf-backup.lock` 是目录锁。脚本正常退出会删除它；`SIGKILL`、断电或进程崩溃可能留下
空目录。先确认没有备份进程、没有正在增长的临时 archive，而且路径确实是当前 `BACKUP_DIR`：

```bash
ps aux | grep '[b]ackup.sh'
ls -ld ./backups/.lcf-backup.lock
```

只有确认它是孤儿且为空时才用 `rmdir ./backups/.lcf-backup.lock`；自定义 `BACKUP_DIR` 时替换为
对应精确路径。不要用递归删除，也不要在另一个备份仍运行时移除锁。

## restore 报缺少 checksum

这是默认 fail-closed 行为，不是兼容性 bug。把创建备份时生成的同名
`ARCHIVE.tar.gz.sha256` 放回 archive 旁边。只有 archive 已经由签名、可信介质清单等独立机制认证
时才可显式加 `--allow-missing-checksum`；该 flag 只是豁免缺失 sidecar，不证明 archive 来源。
