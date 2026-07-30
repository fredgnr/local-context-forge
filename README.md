# Local Context Forge

面向代码库的本地 Context7 替代方案：把源码持续编纂为**可审查、可追溯、可版本化的 API Wiki**，再通过与 Context7 同名的 MCP 工具交给 Codex 或其他编码 Agent。

它不是“把代码切块后做一次向量搜索”。核心链路是：

```text
immutable source snapshot
        │
        ▼
deterministic facts + source refs
        │
        ▼
LLM-generated proposal (Markdown + JSON)
        │
        ▼
schema + exact evidence-range/source SHA/path/line gate + human review
        │
        ▼
Git-backed API Wiki ──► post-publish lint ──► QMD / lexical retrieval
        │
        ▼
resolve-library-id + query-docs
```

## 适合这套设备的分工

| 设备 | 常驻职责 | 推荐模型 |
| --- | --- | --- |
| M4 Pro MacBook · 24 GB | 常驻控制面、宿主 CLI runner、Git、SQLite、QMD、MCP、Web | 默认 Codex CLI；EmbeddingGemma 300M Q8；Cursor CLI 仅作备用 |
| Windows · 32 GB + RTX 4060 | 可选的局域网生成节点 | Ollama `qwen3.5:9b` |

快照、Wiki、SQLite 与索引都留在本机。远程 Git 导入会访问显式允许的代码托管站；
可选 Codex provider 也会访问 OpenAI。Windows 的 Ollama 端口只应对 Mac 的固定局域网
IP 开放，不能暴露到公网。

## 一条命令启动

要求：macOS 已安装并选好 Docker Desktop 或 Colima 的 Docker context、Git、`curl`、
`tar`、`jq`、Python 3.9+ 与 `rsync`。可先运行
`./scripts/macos-bootstrap.sh --check` 做只读检查；clean macOS 推荐先安装
Homebrew，让 bootstrap 安装缺失或过旧的 Python、`jq` 与 `rsync`。Windows 已安装 NVIDIA 驱动。
首次下载镜像和模型不计入下面的时间。

先确认 Docker Desktop 或 Colima 的 Docker context 已经选好；安装器不会偷偷切换
context。推荐先在 Mac 上完成 `codex login`。没有 Codex/Cursor 也可以安装：首次默认安装会
明确降级为 `mock` 演示模式，之后登录 CLI 再重新选择 provider。然后：

```bash
unzip local-context-forge-complete.zip
cd local-context-forge
./install.sh
```

不想输入命令时，也可以解压后双击 `install.command`；它调用同一安装器，并在失败时
保留窗口显示修复提示。不要使用 `sudo`：Docker context、LaunchAgent 与 CLI 登录都属于当前
macOS 用户。

`install.sh` 会完成预检、生成权限为 `600` 的 `.lcf/runtime.env`、按需安装当前用户的
LaunchAgent host runner、构建并启动 Compose、等待 health、运行 doctor/smoke，
最后打开 Web。`mock`/`ollama` 不启动 host runner。重复运行不会覆盖数据；断电留下且没有存活
owner 的 deploy lock 会被安全清理。

```bash
./scripts/lcf status
./scripts/lcf doctor
./scripts/lcf logs
./scripts/lcf stop
./scripts/lcf start
./scripts/lcf down        # 删除容器但保留数据
./scripts/lcf backup
./scripts/lcf uninstall   # 保留 data/imports/backups
```

仓库的 GitHub Actions 会同时构建 `linux/arm64` 与 `linux/amd64`，并把 API、MCP、Web
发布到 GHCR。默认安装仍从当前 checkout 本地构建，因此不要求 Registry 登录。希望跳过本地
构建时，先让当前 Docker context 登录私有 GHCR，再运行：

```bash
read -s CR_PAT
printf '%s' "$CR_PAT" | docker login ghcr.io -u fredgnr --password-stdin
unset CR_PAT
./install.sh --images ghcr --image-tag main
```

PAT 只需要 classic `read:packages`；不要把它写进仓库、`.env` 或 `.lcf/runtime.env`。
版本发布可把 `main` 换成精确的 `0.1.0`，提交锁定部署可使用流水线生成的
`sha-<12位提交前缀>`。完整标签、Colima 和权限说明见
[GitHub Actions 与 GHCR](docs/15-github-actions-ghcr.md)。

高级用户可指定已有 runtime、provider 与端口：

```bash
./install.sh --runtime colima --provider auto \
  --web-port 8080 --api-port 8000 --mcp-port 8001
```

`auto` 优先使用已安装且已登录的 Codex。只有 Codex 在调用前预检为未安装或未登录
时才选择 Cursor；Codex 开始执行后的超时、非零退出或坏 JSON 不会再调用 Cursor，
避免一次任务消耗两份额度。

显式切换 provider 时重复运行安装器即可：

```bash
./install.sh --provider codex_cli --no-open
./install.sh --provider cursor_cli --no-open
./install.sh --provider mock --no-open
```

显式 CLI/`auto` 模式在没有可用登录时会失败；只有首次未指定 provider 且没有可用 CLI 时自动
落到 mock，不会悄悄调用可能计费的服务。

打开：

- Web 审核台：<http://localhost:8080>
- OpenAPI：<http://localhost:8000/docs>
- API 健康检查：<http://localhost:8000/api/health>
- MCP：<http://localhost:8001/mcp>

在 Windows PowerShell 中准备生成服务：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\windows-ollama-setup.ps1 `
  -MacAddress 192.168.1.20 `
  -InstallOllama `
  -RestartOllama
```

把 `192.168.1.20` 换成 Mac 的固定 IPv4。脚本只接受单个 RFC1918 地址或
`100.64.0.0/10` 隧道地址；会拒绝公网、IPv6、CIDR、loopback、multicast、
`255.255.255.255` 与 `Any`。随后把 Mac 的 `.env` 中
`OLLAMA_BASE_URL` 改为 Windows 的固定局域网地址，例如：

```dotenv
OLLAMA_BASE_URL=http://192.168.1.50:11434
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_NUM_CTX=16384
OLLAMA_NUM_PREDICT=4096
```

完整步骤与防火墙边界见 [硬件与双机部署](docs/03-hardware-deployment.md) 和 [快速开始](docs/04-quickstart.md)。

Compose 内的 QMD 可以在 Apple Silicon 上运行，但通常不能直接使用 Metal。完成首次验收后，如需更快的 embedding / rerank，可切换 Mac 原生控制面：

```bash
./scripts/macos-bootstrap.sh --native
make dev-native
```

必须先停止 Compose API，不能让原生 API 与容器 API 同时写同一个 `data` 目录。运行模式切换
完成后，在 Web 的“系统设置”选择全局 embedding 模型并提交重建；任务进入同一持久 FIFO。
profile ready 前查询自动使用 lexical fallback。`make qmd-embed*` 仅保留为高级诊断入口，
target 名称本身不会替你切换 runtime。

## 从代码库生成 Wiki

登记仓库：

```bash
created="$(curl --fail --silent --show-error \
  -X POST http://localhost:8000/api/libraries \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "sample-sdk",
    "source": "https://github.com/owner/repo.git"
  }')"
LIBRARY_ID="$(jq -er '.id' <<<"$created")"
printf 'library=%s\n' "$LIBRARY_ID"
```

启动采集。默认 `auto_publish=false`，所以模型输出只能进入待审提案：

```bash
curl --fail --silent --show-error \
  -X POST "http://localhost:8000/api/libraries/${LIBRARY_ID}/ingest" \
  -H 'Content-Type: application/json' \
  -d '{"ref":"main","provider":"ollama","auto_publish":false}'
```

也可以先用 `provider=mock` 验证完整流程，不需要任何生成模型。本地目录默认
禁用；Compose 只把 `./examples` 和 `./imports` 以只读方式列入 allowlist，避免 API
读取宿主任意路径。若本地 source 仍带 Git 元数据，路径必须正好是仓库顶层；不能把 monorepo
子目录直接当作 Git source。普通独立仓库的本地 `.git` 目录可以导入；linked worktree/
`.git` pointer、非普通 `.git/config`、`commondir`、alternate object store 或任何逃出仓库根的
Git metadata/object path 都会拒绝。`git archive` 还会拒绝 submodule、Git LFS pointer，以及
NFC + casefold 后冲突的路径。遇到这些情况，先在宿主完整 checkout、更新 submodule、smudge
LFS，再把所需 worktree/子树复制到 `imports/` 中一个**不含父 `.git`**的目录，以普通目录和
`ref=HEAD` 导入。批准提案后，后端会：

1. 写入 Markdown 与 typed JSON sidecar；
2. 更新 `index.md` 与 `log.md`；
3. 创建 Git commit，并以 SQLite 物化页作为运行时权威；逐页批准只写暂存物化；
4. 全部提案均批准且没有 rejected 后，才原子激活版本、切为 default 并刷新 QMD；
5. 允许 MCP 查询到新版本。

Web 的“重新采集”不会静默沿用旧参数：必须显式选择 provider、ref 和一个新的 version label；
已物化的 source/version 不原地刷新。`./scripts/demo-seed.sh` 对**已成功发布**的 demo 可重复
执行：会复用 library、修正当前运行方式的 source，若 `1.0.0` 已发布就跳过不可变 ingest，并
继续做查询验证；它不会自动修复前次留下的 proposed/partial/rejected 同版本，也不应并发运行。

## 接入 MCP

Docker 默认启动 streamable HTTP：

```bash
codex mcp add local-context-forge \
  --url http://localhost:8001/mcp
codex mcp list
```

Hybrid 冷启动可能接近 API 的 600 秒内部上限。请同时在
`~/.codex/config.toml` 中确认：

```toml
[mcp_servers.local-context-forge]
url = "http://127.0.0.1:8001/mcp"
tool_timeout_sec = 660.0
```

MCP 暴露：

- `resolve-library-id(libraryName, query)`
- `query-docs(libraryId, query)`

它们刻意采用 Context7 的工具名；具体返回值包含本地 library ID、版本、source SHA 和源码引用。stdio 配置和其他客户端示例见 [API 与 MCP](docs/06-api-and-mcp.md)。

## Codex CLI：能否使用 ChatGPT 额度？

可以，但要区分场景。OpenAI 官方文档说明 Codex CLI 本地工作同时支持 ChatGPT 登录和 API key：

- **受信任的个人本机、交互式分析**：可以使用 `codex login`，消耗对应 ChatGPT/Codex 用量。
- **共享服务、CI/CD、多人或长期无人值守自动化**：API key 是官方建议的默认方式。
- **不要**把个人 `~/.codex/auth.json` 放进镜像、仓库或多人可访问的服务。

all-in-one 模式不会把 `~/.codex`、Cursor 凭据或 Docker socket 挂进容器。Compose
worker 把 bounded typed evidence 放入 `data/runner/inbox`，macOS LaunchAgent 在新的
临时目录调用宿主 CLI，再通过原子 rename 返回结果。runner 不接受任意 command、
prompt 或 path 参数。Codex 使用 ephemeral/read-only/ignore-rules；Cursor 永远不加
`--force`。两者只产出结构化提案，仍没有 Wiki 发布权限。

这不是 macOS 用户级文件保密沙箱：宿主 CLI 仍具有当前登录用户的读取能力。默认模式
只适用于本人、本机、loopback 单用户；高安全源码应使用专用 macOS 账号或
evidence-only VM。

官方依据：[Codex authentication](https://learn.chatgpt.com/docs/auth)、[Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)。本项目的决策与风险说明见 [Codex CLI 集成](docs/07-codex-cli.md)。

## 目录

```text
backend/          FastAPI、SQLite、事实提取、生成器、验证、Git Wiki、检索
host_runner/      macOS Codex/Cursor spool runner 与 fake CLI 契约测试
mcp/              Context7-compatible MCP gateway
web/              React + TypeScript 知识图谱工作台
guide-site/       本说明站的可复制命令与图文页面源码（不含部署 ID）
docker/           API / MCP 镜像定义
scripts/          macOS、Windows、演示、备份、恢复、冒烟测试
.lcf/             私有运行时配置、LaunchAgent 日志与安装状态（安装后生成）
examples/         可离线采集的示例代码库
tests/            后端流水线、版本隔离、安全边界与 MCP 格式化测试
docs/             设计、部署、API、运维、安全与排错手册
tools/            可选的 legacy PDF 构建器与嵌入式 CJK 字体
output/pdf/       legacy/可选 PDF 输出；本轮交付不要求生成
```

运行时所有可变状态集中在 `/data`。`metadata.sqlite3` 是运行时目录与状态权威，
`wiki` 是已审核知识的 Git 审计副本，`sources`/`facts` 是编译输入，只有 `qmd`
cache/index 属于可删除重建的派生层。详见 [数据模型](docs/05-data-model.md)。

## 设计来源与取舍

- [Karpathy 的 compiling wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)：采用持久 Wiki、raw/wiki/schema 三层、ingest/query/lint 与 Git 历史。
- [Context7](https://github.com/upstash/context7)：保留客户端消费契约，不复制托管采集平台。
- [docs-mcp-server](https://github.com/arabold/docs-mcp-server)：作为抓取与索引参考，不让临时检索结果承担知识本体。
- [QMD](https://github.com/tobi/qmd)：为 ready 的全局 profile 提供向量、重排与查询扩展。
  本项目固定 `@tobilu/qmd@2.5.3`；模型未建、stale 或不可用时回退到确定性 lexical search。

方案详解见 [Karpathy 方案如何改变本设计](docs/02-karpathy-wiki.md)。

## 当前实现边界

- Ollama/Codex 生成采用 **bounded single-pass**：模型 JSON 总量默认硬限 100 KB；
  超大型 monorepo 请先按 package 拆成多个 library。模块化 map-reduce 是明确的下一阶段，
  本版本不假装已经实现。
- 查询以 SQLite 页面表为运行时物化层；Git Wiki 是可审计、可恢复制品。手工 `git revert`
  不会自动刷新 SQLite/QMD，需通过新提案重新发布或恢复同一份完整备份。
- library create/delete、ingest、publish/reject 已使用同一主机可见的文件锁与 SQLite
  状态门。任务进入 SQLite 持久 FIFO，由单并发 worker 原子 claim；`queued` 在 API/主机重启
  后继续排队，只有中断时处于 `running/cancelling` 的任务会 fail-closed 为 `orphaned`。
  Job 响应包含 queue position、cancel/retry 能力；重试会创建带 `retry_of/attempt` 的新任务，
  不篡改旧审计记录。备份 drain 停止新任务并等待活动 worker 归零；已排队任务可随备份恢复。
  所有 QMD collection 注册、刷新、删除和重建共享一个跨进程 writer lock。
  当前产品边界是 loopback 上的受信任单用户；它没有认证、library ACL 或 Markdown 响应字节
  上限，HTTP `limit` 与超时并不是共享服务的响应体保证。SQLite FIFO 是单主机单 worker
  设计；多主机/多人仍需分布式 lease/lock、auth/TLS/ACL、速率和总响应大小限制。
- 远端导入只接受无 userinfo、无 query/fragment、443 端口的 HTTPS，并默认精确允许
  `github.com,gitlab.com,bitbucket.org`；可用 `LCF_REMOTE_SOURCE_HOSTS` 显式调整。
  Git 禁用交互凭据、system/global 配置与 HTTP 重定向，并清理调用进程继承的全部 `GIT_*`
  覆盖后只写入受控值；最终快照默认限制为 100,000 个成员/
  2 GiB。尚未实现 DNS/IP 固定、Git 对象/网络传输总量硬上限，所以写 API 仍只适合
  受信任的 localhost 单用户。
- source-ref gate 会把每个提案绑定到该次生成器**实际可见**的 evidence/symbol 行范围，
  同时验证同一 snapshot 的 SHA、普通文件、非敏感路径与行范围；它仍不能证明引用行在语义
  上蕴含页面声明。人工审核仍是事实正确性的必要步骤。
- `auto_publish=true` 会逐页写入可恢复 Git/SQLite 记录，但只有全部页面成功后才激活
  `default_version`。中途失败会留下 `partial` 版本供诊断，不能通过默认版本/MCP 路径误用；
  它不是跨 Git 与 SQLite 的全局 ACID 事务。
- 人工 review 使用同样的可见性屏障：批准页会进入暂存物化，最后一篇批准后才整版激活；
  任一 rejected 会让该版本保持不可查询。已物化的同一 source/version 不在原地刷新，
  修订时应使用新 version label。

## 安全默认值

- 仓库内容一律视为不可信数据；生成器看不到正式 Wiki 写权限。
- 同一 Git SHA 的 source snapshot 不覆盖写。
- 本地 Git source 必须是仓库顶层的 standalone `.git` 目录；linked worktree/gitdir pointer、
  非普通 config、commondir 与 alternate/越界 object store 都拒绝。归档还拒绝 submodule、
  LFS pointer 与 casefold/NFC 冲突。需要这些内容时先物化为不含父 `.git` 的 allowlist 普通
  目录，不能靠放宽归档检查。
- Universal Ctags 固定使用 `--options=NONE --links=no`，不读取仓库/用户 options，也不跟随
  链接。Wiki Git 每次操作都会忽略 system/global 配置并把本地 config 重写为最小无
  hooks/fsmonitor/attributes/credential 配置；恢复仍只接受可信备份，checksum 不是来源认证。
- 提案必须通过 schema、实际可见 evidence range、source path、line range、敏感路径、
  symlink 与 stale SHA 的一致性检查；发布后的全局 lint 再报告 typed index、sidecar、
  重复页和断链。它们都不能替代人工事实审阅。
- 容器内旧式 Codex provider 默认禁用；all-in-one 通过 bounded spool 调用宿主
  LaunchAgent。Ollama、host runner 和 MCP 均只用于受信任的本机/本地网络。
- 删除 library 默认只删元数据；`purge=true` 还会尽力清理该库的快照、facts、Wiki、
  proposal/job 文件与已知 QMD collection，并逐项报告失败。它不是 SSD、备份、宿主快照
  或模型缓存的 secure erase。
- `backup.sh` 把未压缩 staging 放在操作者指定的加密 `BACKUP_DIR` 同一文件系统，因此该卷需
  同时容纳完整 staging、压缩归档、checksum 与余量；Compose stop 预算默认 3,600 秒，可用
  `LCF_BACKUP_STOP_TIMEOUT_SECONDS` 调整。归档与 sidecar 先写隐藏 `.partial`，fsync 后再在
  同目录 rename。恢复默认强制要求相邻 `.sha256`；只有对已用独立机制认证的归档，才可显式
  使用 `--allow-missing-checksum` 豁免。恢复在目标同级同盘 staging 校验/展开，最后原子 rename；
  替换前的原目录会进入 quarantine，最终 rename 失败时脚本会回滚它。QMD cache 不作为唯一备份。
- embedding 模型是全局 runtime setting；更换模型会把全局 embedding 状态标为 stale，并通过
  FIFO 创建 `embedding_rebuild`。成功重建并原子更新 active model/corpus revision 前，查询
  自动使用 lexical fallback，不会混用新旧模型向量。索引重建只处理已发布 Wiki/QMD，**不调用
  LLM，也不消耗 Codex/Cursor 额度**；“重新采集仓库”才会重新生成提案并消耗 CLI/模型额度。
  `scripts/reindex.sh [--embed]` 是高级运维入口：从 SQLite 只枚举 fully published 版本，先恢复
  QMD collection registration，再统一 update/embed；`--embed` 固定使用 QMD `-f`。默认
  `QMD_EMBED_MODEL=hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf`。
  Web/API 优先提供 curated preset；高级用户也可填写严格校验的
  `hf:org/repo/file.gguf`，不接受 HTTP endpoint。library scope 只影响请求来源，
  向量空间仍是全局 profile，
  rebuild 会注册完整 published corpus。不能混用 Compose 与 native 的 QMD config/cache。

上线或采集私有仓库前，请完整阅读 [威胁模型](docs/10-security.md)。

## 验证

```bash
make test
make build
./scripts/smoke-test.sh
```

后端测试使用临时目录和确定性 mock provider，不要求下载模型。Web 使用 TypeScript
typecheck 和生产构建。`make test` 需要先运行
`./scripts/macos-bootstrap.sh --native` 安装根 `.venv` 与 Web 依赖；只做 Compose 验收时
直接运行 smoke 即可。先运行 `demo-seed.sh` 创建并发布演示库；`smoke-test.sh`
本身只做只读 health/list/query 与容器状态检查，不会创建数据或调用真实模型。

## 文档导航

1. [总体说明](docs/00-overview.md)
2. [架构](docs/01-architecture.md)
3. [Karpathy Wiki 改进](docs/02-karpathy-wiki.md)
4. [硬件与部署](docs/03-hardware-deployment.md)
5. [快速开始](docs/04-quickstart.md)
6. [数据模型](docs/05-data-model.md)
7. [API 与 MCP](docs/06-api-and-mcp.md)
8. [Codex CLI](docs/07-codex-cli.md)
9. [运维](docs/08-operations.md)
10. [备份恢复](docs/09-backup-restore.md)
11. [安全](docs/10-security.md)
12. [排错](docs/11-troubleshooting.md)
13. [模型选择](docs/12-model-selection.md)
14. [替代方案对比](docs/13-alternatives.md)
15. [M4 Pro all-in-one 部署](docs/14-all-in-one-macos.md)

## 许可证

项目自身代码见 [LICENSE](LICENSE)。第三方模型、CLI 和依赖各自适用其许可证与服务条款；本项目不重新分发模型权重。
