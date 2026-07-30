# 安装与快速开始

## 前提

Compose 路径：

- macOS 14+（Apple Silicon 推荐）
- Docker Desktop 与 Compose v2
- Git
- `curl`、`tar`、`jq`、Python 3、`rsync`
- 首次 QMD 模型下载所需网络
- 可选：Windows 11 + Ollama + NVIDIA 驱动

推荐先安装 Homebrew，再由 bootstrap 安装缺失的 `jq`、Python 3 与 `rsync`。原生路径还需要
Homebrew、Node.js 22+、Homebrew SQLite、Python 3.11+ 与 Universal Ctags。只检查、不安装：

```bash
./scripts/macos-bootstrap.sh --check
```

## 1. all-in-one 初始化（推荐）

```bash
./install.sh
```

这一个入口完成预检、私有配置、按需安装 macOS host runner LaunchAgent、Compose build/up、
health、doctor/smoke 并打开 Web。它不安装第三方 CLI、不切换 Docker context、
不复制/mount 登录凭据，且只监听 loopback。首次未指定 provider 且没有已登录
Codex/Cursor 时会明确进入 `mock` 演示模式，仍可完成部署。完整阶段与高级参数见
[M4 Pro all-in-one 部署](14-all-in-one-macos.md)。

仅做旧式手工 bootstrap 时仍可运行：

```bash
./scripts/macos-bootstrap.sh --check
./scripts/macos-bootstrap.sh
```

检查关键安全默认值：

```dotenv
LCF_BIND_HOST=127.0.0.1
WEB_PORT=8080
API_PORT=8000
MCP_PORT=8001
LCF_QMD_HYBRID_ENABLED=true
```

## 2. 查看状态

```bash
./scripts/lcf status
./scripts/lcf doctor
```

正常状态：

```text
api    healthy
mcp    healthy
web    healthy
```

首次构建会按 requirements 的兼容范围安装 Python 包，并固定 QMD 为 `2.5.3`；可复现发布还应保存
lockfile/镜像 digest。没有可用的全局 embedding profile 时，查询使用内置 lexical fallback；
这不阻塞仓库采集、审核和发布。模型选择与向量重建由 Web 的“系统设置”统一管理。

## 3. 导入演示仓库

```bash
./scripts/demo-seed.sh
```

脚本创建一个小型、无外部依赖的 Python 示例库，调用 `mock` ingest，并为演示目的自动发布确定性
文档骨架。成功发布后可幂等重复运行：它会复用 library、按 Compose/native 修正 source；若
`1.0.0` 已经发布，就跳过不可变 ingest 并继续做 query 验证。它不会自动修复前次失败留下的
proposed/partial/rejected 同版本，也不应并发运行。真实仓库默认应保持
`auto_publish=false` 先审核。

为避免同一个 branch/标签在不同 commit 上互相污染，显式版本会物化为例如 `1.0.0+git.3ac10e1f42ab`。API 用原始 `1.0.0` 查询时会解析到该基线最新的物化版本；job/default_version 响应会显示精确值。

查询 job：

```bash
curl --fail http://127.0.0.1:8000/api/jobs/JOB_ID | jq
```

也可以从 Web UI 查看进度、提案、lint 与发布操作。

## 4. 运行冒烟测试

```bash
./scripts/smoke-test.sh
```

它检查：

- Web、API、MCP health；
- library 列表；
- 若 demo 已由上一步创建，则验证它的 query API 基本返回结构；否则明确 skip；
- 容器状态。

脚本不删除用户数据，也不会自动批准真实仓库提案。

## 5. 导入自己的仓库

### 本地仓库

容器只能看到显式 allowlist 的只读 mount。先把可信仓库放入 `./imports`；Compose 将它挂为
`/imports`，并按操作系统 path separator 设置
`LCF_LOCAL_SOURCE_ROOTS=/examples:/imports`。创建 library 时使用容器路径，例如
`"source":"/imports/widget"`。默认不允许 `/data`、宿主任意路径或未列出的本地目录。

若目录中存在父 Git worktree 元数据，source 必须正好是 `git rev-parse --show-toplevel` 返回的
仓库顶层；monorepo 的 package 子目录不能直接作为本地 Git source。普通独立仓库的 standalone
`.git` 目录可用；linked worktree/`.git` pointer、非普通 `.git/config`、`commondir`、alternate
object store 和任何越界 metadata/object path 会拒绝。Git 固化路径还会拒绝：

- mode `160000` 的 submodule（`git archive` 不会展开它）；
- Git LFS pointer（不把 pointer 当真实源码）；
- 两个路径经 NFC normalization + casefold 后碰撞；
- 越界链接、特殊文件、重复路径和最终 snapshot 限额。

需要分析 monorepo 子树、submodule 或 LFS 内容时，先在宿主完整 checkout：

```bash
git -C /path/to/repo submodule update --init --recursive
git -C /path/to/repo lfs pull
rsync -a --exclude=.git /path/to/repo/ ./imports/widget-materialized/
```

若只要 monorepo 的一个 package，就把最后一条的 source 换成该子目录。目标必须是一个不含父
`.git` 元数据的独立 allowlist 目录；随后以普通目录 source 和 `ref=HEAD` ingest。不要用关闭
检查来换取“成功”。

`imports/` 已进入 `.gitignore`，也不应进入 release zip；它只是只读入站区。LCF 的一致性备份保存 `/data/sources` 中已经固化的快照，不重复归档宿主 `imports/` 原仓库。

示例请求：

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "widget",
    "slug": "acme-widget",
    "source": "/imports/widget"
  }' \
  http://127.0.0.1:8000/api/libraries
```

`default_version` 是发布成功后由系统维护的**物化版本指针**，不是初始 branch/tag。要分析的 ref 与版本基线放在后续 ingest 请求中。

若仓库是私有的，优先在宿主机提前 clone，再用只读 mount；不要把长期 Git token 写入 URL、`.env` 或 job payload。

### Git URL

当前远端入口只接受不含 userinfo、query/fragment 的 `https://` 443，明确拒绝
`http://`、`ssh://`、`git://` 和 `git@...`；默认 exact-host allowlist 是
`github.com,gitlab.com,bitbucket.org`，通过 `.env` 的
`LCF_REMOTE_SOURCE_HOSTS` 调整。Git 子进程禁用交互凭据、system/global 配置、hooks 与 HTTP
重定向；最终 snapshot 默认最多 100,000 个成员/2 GiB。私库请先在宿主安全地 clone 到
`imports/`。hostname allowlist 与最终展开限额仍不是完整 SSRF/流量防线；生产部署还应阻断：

- `file://` 与本地任意路径；
- loopback、link-local、云元数据地址；
- 重定向到内网的地址。

## 6. 审核与发布

```bash
# 查看某个 library 的提案
curl --fail "http://127.0.0.1:8000/api/libraries/LIBRARY_ID/proposals"

# 明确确认后发布
curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/api/proposals/PROPOSAL_ID/publish"

# 发布后检查 index/sidecar/source refs 与 Wiki links
curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/api/libraries/LIBRARY_ID/lint"
```

`lint` 只检查已发布 Wiki，不验证 pending proposal。发布前从 Web UI 查看 proposal 正文预览、metadata 与 `source_refs`；当前 UI 不是 base-vs-proposal diff。不要把“lint 通过”视为“内容一定正确”。

人工 publish 是**逐页批准、整版激活**：每个已批准页面先进入该物化版本的 Git/SQLite
暂存层；只有全部 proposal 都 published 且没有 rejected 时，最后一次批准才原子更新
`default_version`。任一拒绝会让版本保持 `rejected/partial`，默认、alias、global query 与
MCP 都不会返回它。`auto_publish=true` 使用同一整批可见性门；中途失败保留 `partial`
诊断页，但不会替换旧默认。这里的“原子”只指 SQLite 可见性指针，不是假装 Git 与 SQLite
组成跨介质 ACID 事务。

## 7. 查询

```bash
curl --fail-with-body \
  -H 'Content-Type: application/json' \
  -d '{
    "library_id": "/local/acme-widget",
    "query": "How do I create a client with a custom timeout?",
    "version": "v1.4.0",
    "limit": 5
  }' \
  http://127.0.0.1:8000/api/query | jq
```

要启用完整 hybrid，在 Web 的“系统设置”选择 embedding 模型并提交“重建全局索引”。该操作会
创建持久 FIFO 中的 `embedding_rebuild` job；可在任务页查看排队位置、取消或在失败后重试。
系统会注册完整的已发布 corpus，并以目标模型执行一次全局 `qmd embed -f`。成功前
`embedding.hybrid_ready=false`，查询继续走 lexical fallback；不会混用旧模型向量。

索引重建只读取已发布 Wiki 并更新 QMD，**不会调用 Codex/Cursor，也不消耗 LLM 额度**。只有
“重新采集仓库”才会重新生成 Wiki 提案并消耗所选 provider 的额度。`scripts/reindex.sh` 和
`make qmd-embed*` 仅保留给资深用户做同步诊断，不是日常模型切换入口。

## 8. MCP 客户端

Streamable HTTP endpoint：

```text
http://127.0.0.1:8001/mcp
```

Codex CLI 示例：

```bash
codex mcp add local-context-forge \
  --url http://127.0.0.1:8001/mcp
```

再检查 `~/.codex/config.toml`，给冷 hybrid 查询留出比 API 内部 600 秒更长的工具预算：

```toml
[mcp_servers.local-context-forge]
url = "http://127.0.0.1:8001/mcp"
tool_timeout_sec = 660.0
```

或使用 stdio（原生 bootstrap 会以 editable package 安装 console script；把绝对路径替换为你的 checkout）：

```json
{
  "mcpServers": {
    "local-context-forge": {
      "command": "/ABSOLUTE/PATH/local-context-forge/.venv/bin/local-context-forge-mcp",
      "args": [],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "BACKEND_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

工具调用示例见 [HTTP API 与 MCP](06-api-and-mcp.md)。

## 9. 切换到 Windows Ollama

先按 [硬件与部署](03-hardware-deployment.md) 配好防火墙。然后：

```bash
sed -n '/OLLAMA_/p' .env
docker compose up -d --force-recreate api
curl --fail http://127.0.0.1:8000/api/health
```

创建 ingest 时把 `"provider":"ollama"` 放在 JSON body 中；provider 是每次任务的选择，不是全局环境变量。

Web 上对已存在库执行“重新采集”时，也必须显式填写 provider、ref 和一个**新的** version label；
UI 不会隐式复用旧值，也不能原地覆盖已物化 source/version。

从 API 容器验证 Windows：

```bash
docker compose exec api \
  sh -lc 'curl --fail "$OLLAMA_BASE_URL/api/tags"'
```

不要用 shell 历史传递密钥；Ollama 局域网模式默认也不提供用户级鉴权。

## 10. 停止

```bash
docker compose stop
```

删除容器但保留 `./data`：

```bash
docker compose down
```

不要随意使用 `docker compose down -v`；虽然本项目默认使用 bind mount，但未来配置可能含 named volume。删除或清空 `./data` 前先运行备份。
