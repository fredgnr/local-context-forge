# 运维、升级与性能

> **适用范围：legacy Docker/Web。** Electron 桌面版使用不同的数据目录、进程和更新模型，
> 参见[部署与运维](18-deployment-operations.md)。对 `./install.sh` 创建的实例，生命周期命令
> 必须通过下方 `lcf_managed` 调用 `scripts/lcf`。脚本会读取安装时记录的 Docker context、
> Compose project root 和 mode-`0600` 的 `.lcf/runtime.env`，但当前不会自行隔离优先级更高的
> shell/Compose 变量。本页出现的裸 `docker compose` 命令只适用于明确配置好的未托管开发
> checkout，不能直接复制到已安装实例。实现缺口见 `TODO-LEGACY-CONTROL-001`。

## all-in-one 生命周期

先在受管实例的仓库根目录定义 clean-environment 入口；它只保留 Docker/CLI 定位所需的
`HOME`、`PATH`，清除 `COMPOSE_PROJECT_NAME`、`COMPOSE_*`、`LOCAL_*`、`LCF_*`、端口和镜像
覆盖：

```bash
LCF_CONTROL_BIN="$(pwd -P)/scripts/lcf"
lcf_managed() {
  env -i \
    HOME="$HOME" \
    PATH="$PATH" \
    "$LCF_CONTROL_BIN" "$@"
}
```

本页所有 `lcf_managed` 示例都要求先执行这段定义。日常操作：

```bash
lcf_managed status
lcf_managed doctor
lcf_managed logs
lcf_managed stop
lcf_managed start
lcf_managed restart
lcf_managed down
lcf_managed backup
```

不要在 Docker Desktop 与 Colima 共存时绕过该入口对另一个 context 执行
`docker compose down`。控制命令不会切 context，也不会删除 volume/data。

Host runner 由当前用户的
`~/Library/LaunchAgents/dev.local-context-forge.host-runner.plist` 管理，日志位于
`.lcf/logs/`，状态位于 `data/runner/heartbeat.json`。Heartbeat 过期时运行：

```bash
lcf_managed doctor
tail -n 200 .lcf/logs/host-runner.err.log
lcf_managed restart
```

`stop` 保留容器，`down` 删除容器但不带 `-v`；二者都会停止 host runner 并删除派生的旧
heartbeat，下一次 `start` 必须等待新 heartbeat，避免假健康。`lcf_managed uninstall` 只移除
容器和 LaunchAgent，默认保留 `data`、`imports`、`backups` 和 `.lcf`。

切换 provider 使用幂等安装器：

```bash
lcf_managed install --provider codex_cli --no-open
lcf_managed install --provider cursor_cli --no-open
lcf_managed install --provider mock --no-open
```

显式 CLI 模式会先验证安装与登录。`mock`/`ollama` 会卸载 host runner LaunchAgent；切回 CLI
模式会按当前绝对 CLI 路径重新创建。首次未指定 provider 且没有可用 CLI 时才自动使用 mock，
已有安装或显式 `--provider auto` 不会因暂时掉登录而偷偷改变 provider。

## 日常检查

```bash
lcf_managed status
lcf_managed doctor
```

若安装时保留默认端口，可额外做只读端点探测：

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8001/health
curl --fail http://127.0.0.1:8080/healthz
```

当前 `/api/health` 是进程存活检查，并报告 QMD 的 `enabled/available`；它不会做 SQLite 写入、Wiki Git、Ollama 或端到端 query 探测。Compose 的 `healthy` 因此只代表对应 HTTP 进程可响应。生产监控应另加 synthetic query、SQLite integrity/空间、最近 job 失败率和 Ollama 探测，不能把 liveness 当完整 readiness。

不要因为 Windows Ollama 关机就重启整个知识库；只需要在生成任务前恢复它。

## 日志

```bash
lcf_managed logs
```

该命令显示 Host Runner 日志路径，并使用已记录的 context/env 跟随 Compose 日志；`Ctrl-C`
只退出日志跟随，不停止服务。需要单服务或时间范围过滤时，先阅读
[部署与运维中的高级诊断](18-deployment-operations.md#29-高级诊断与裸-compose)，再显式传入
同一个 context、project directory、env file 和 Compose 文件。

原生一键开发模式会在启动时打印一个
`${TMPDIR:-/tmp}/lcf-dev-native.XXXXXX/` 目录，并把 `api.log`、`mcp.log`、`web.log` 留在那里；
停止服务不会自动删除。把该路径记入故障单，复核后按源码敏感级别和保留策略清理，不要长期把
debug 日志留在共享 `/tmp`。

日志应包含 request/job/proposal ID，不应包含：

- Authorization header、API key、Codex token。
- 含用户名或密码的 Git URL。
- 完整 evidence pack 或私有源码。
- Windows 共享凭据。

生产环境设置轮转和保留期。问题排除后删除临时 debug 级日志。

## Job 运维

### FIFO、取消与重试

SQLite 持久 FIFO 默认单并发。先从受管安装记录中只读取并校验实际 API 端口；不要 `source`
整个 `.lcf/runtime.env`：

```bash
LCF_API_PORT_ACTUAL="$(
  awk -F= '
    $1 == "API_PORT" && $2 ~ /^[0-9]+$/ && $2 >= 1024 && $2 <= 65535 {
      print $2
      exit
    }
  ' .lcf/runtime.env
)"
if [ -z "$LCF_API_PORT_ACTUAL" ]; then
  printf '%s\n' 'Invalid or missing API_PORT in .lcf/runtime.env' >&2
  exit 1
fi
LCF_API_BASE="http://127.0.0.1:${LCF_API_PORT_ACTUAL}"
```

未托管部署没有这份权威记录；必须从它自己的受控配置构造 `LCF_API_BASE`。后续所有 API
命令复用该变量。先看系统与任务：

```bash
curl --fail "${LCF_API_BASE}/api/system/status" | jq
curl --fail "${LCF_API_BASE}/api/jobs/JOB_ID" | jq
```

`queued` 返回从 1 开始的 `queue_position`；API/主机重启不会丢队列，dispatcher 恢复后继续
按 `queue_seq` claim。取消/重试使用 Web，或：

```bash
curl --fail-with-body -X POST \
  "${LCF_API_BASE}/api/jobs/JOB_ID/cancel" | jq

curl --fail-with-body -X POST \
  "${LCF_API_BASE}/api/jobs/JOB_ID/retry" | jq
```

queued 立即 cancelled；running 先变 cancelling，并在 snapshot/facts/generation/publish 等安全
检查点终止。失败/取消且尚无 proposal 副作用时 `retryable=true`，retry 创建新的
`retry_of/attempt` 行；旧 job 不改写。系统不盲目自动 retry，避免重复消耗 Codex/Cursor 额度。

按阶段定位：

- `control`：job 控制 JSON 缺失、损坏或不可读；fail closed，不会改用 library 当前 source。
- `queued`：等待持久 worker；重启后继续。
- `claim`：queued job 已被 worker 原子认领。
- `lock`：同一 library 已有 ingest。
- `snapshot`：Git 网络、ref、不支持 URL、allowlist、磁盘。
- `facts`：ctags、文件权限、超大仓库/二进制。
- `generation`：Ollama 网络、模型、显存、结构化输出。
- `proposal`：写入 proposal/sidecar/SQLite。
- `publish`：ingest job 的 Git Wiki、SQLite publish 与 QMD update 阶段，仅
  `auto_publish=true` 会进入；人工最后一页批准也会执行整版激活/QMD update，但发生在独立
  publish HTTP 请求中，不会回写旧 ingest job 的 stage。
- `embedding`：全局 QMD profile rebuild；不调用 LLM。
- `cancelling/cancelled`：正在等待安全检查点/已取消。
- `orphaned`：中断时处于 running/cancelling 的 worker owner 已消失；fail closed。
- `completed` / `failed`：终态；validation 细节在 `data/jobs/<job-id>.validation.json`（若有）。

schema/source-ref validation 发生在 `generation` 与 `proposal` 之间；失败后直接 failed。Wiki
内链在 publish 后 lint 报告 warning，示例执行尚未实现。

### 异常退出后的恢复

`queued` 是可恢复状态，启动后继续。只有中断时已经 `running/cancelling` 的任务可能调用过 CLI
或写入部分产物，因此新 API 会检查 owner runtime lock，把真正失去 owner 的行标为
`failed/orphaned`：

```bash
curl --fail "${LCF_API_BASE}/api/jobs/active" | jq
curl --fail "${LCF_API_BASE}/api/jobs?limit=200" |
  jq '[.[] | select(.stage == "orphaned")]'
```

若怀疑启动恢复未执行，可显式重扫：

```bash
curl --fail-with-body -X POST \
  "${LCF_API_BASE}/api/admin/jobs/recover-orphans" |
  jq
```

`preserved_jobs` 包括所有 queued 与仍有活 owner 的执行中任务；`recovered_jobs` 只是把未知
副作用的执行中任务终态化。优先根据 `retryable` 使用 retry；已有 proposal/partial 时先审核
残留产物，再创建新 version ingest。不要直接编辑 SQLite。

### 并发

一台 4060 建议生成并发 1。publish 与 QMD update 也建议单写者。可以并行运行只读 query，但大量 hybrid query 会争用模型内存。

## QMD 索引

```bash
docker compose exec api qmd collection list
docker compose exec api qmd status
```

只有 `LCF_QMD_HYBRID_ENABLED=true` 且全局 embedding profile 为 ready、模型与 corpus
revision 一致时 API 才使用 `qmd query`。其他状态统一使用内置 lexical fallback。

整版激活后的 publish 会更新全局 corpus revision，使 embedding profile stale。此时查询自动
lexical fallback；在 Web 创建全局 rebuild 成功前不会使用旧 revision 的向量。
所有 collection
registration、update、embed、remove 和 rebuild 共享同一个跨进程 writer lock，避免两个 API
进程或运维命令同时改 QMD；锁 60 秒拿不到时会报告 `qmd-busy`，不要绕过锁直接并发写。

日常使用 Web“重建索引”或 API，把全局 rebuild 放入 FIFO：

```bash
curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d '{}' \
  "${LCF_API_BASE}/api/rebuilds" | jq
```

它只枚举 fully published Wiki，注册完整 corpus 并 `embed -f`；review/rejected/partial 不进入
公开检索。索引重建不调用 LLM，不消耗 Codex/Cursor；Web 的“重新采集仓库”才会生成新提案并
消耗额度。`scripts/reindex.sh` 是高级同步诊断入口，不能绕过 QMD writer lock 直接运行 qmd。

### 全局模型 profile

`.env.example`、安装器生成的 `.lcf/runtime.env` 与 Compose/native helper 都明确固定：

```dotenv
QMD_EMBED_MODEL=hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
```

Web 默认从 curated presets 选择模型；高级用户也可填写严格校验的
`hf:org/repo/file.gguf` 标识，不能填写 HTTP endpoint。API 以 runtime settings revision
防止并发覆盖。切换模型会
更新 desired model 并把状态标为 stale，随后必须创建 rebuild job。模型、向量空间和 corpus
revision 都是全局 profile；即使 UI 从某个 library 发起，实际 rebuild 仍覆盖全部 published
corpus。只有 rebuild 成功且 corpus 未在期间变化，active model/indexed revision 才原子前移。
此前查询 lexical fallback。

Compose 使用宿主 `data/qmd/config`、`data/qmd/cache`（容器内 `/data/qmd/...`）；native 使用
`data/qmd/native-config`、`data/qmd/native-cache`。`make qmd-embed` 与
`make qmd-embed-native` 都只是请求当前 `LCF_API_URL`，target 名称不会切换 runtime。先关闭另一种
API，只启动目标 runtime，再重建；不能拿 Compose 注册配置配 native 路径，也不能让两者同时写
同一数据树。

### Hybrid warm-up 与超时

冷启动可能下载/加载 embedding、reranker 与 query-expansion 模型。先完成 embed，再绕过短超时
客户端直接调用 API 做一次 warm-up：

```bash
LIBRARY_ID=/local/acme-widget
curl --fail-with-body --max-time 650 \
  -H 'Content-Type: application/json' \
  -d "$(jq -n \
    --arg library_id "$LIBRARY_ID" \
    '{library_id:$library_id,query:"create client timeout",limit:1}')" \
  "${LCF_API_BASE}/api/query" |
  jq '{engine, hits: (.results | length)}'
```

确认 FIFO 中的 embedding rebuild completed 且 `/api/system/status` 返回
`embedding.hybrid_ready=true` 后再 warm-up。期望 `engine=qmd-hybrid`；若为 `lexical`，
检查 desired/active model、corpus/indexed revision、job error、QMD cache 与 hybrid 环境开关。

不同入口有独立超时：

- Web 普通 API 请求默认 30 秒，但 query 明确为 660 秒，publish 明确为 1,860 秒。
- Web nginx 的 proxy read/send timeout 均为 1,860 秒。
- MCP 默认 `BACKEND_TIMEOUT_SECONDS=660`。
- Codex MCP 客户端还需在 `~/.codex/config.toml` 为该 server 设置
  `tool_timeout_sec = 660.0`。
- API 内部 hybrid QMD 子进程最长等待 600 秒，显式 reindex/embed 最长等待 1,800 秒；失败会降级或在 reindex
  结果中报告。

普通 publish 不在请求内承担 1,800 秒 embed；它会推进 corpus revision，让 profile stale，
后续查询 lexical fallback，直到排队的 rebuild 完成。
Web publish 与 nginx 的 1,860 秒覆盖 collection show/remove/add 与 update 的累计上限；
query/MCP 的 660 秒略高于 hybrid 的 600 秒。生产前应先完成全局 rebuild 并通过直连 API
warm-up，避免第一次查询承担模型加载。若旧安装的 `.lcf/runtime.env` 仍保留较小 MCP
timeout，或你调整了后端上限，先备份该文件，只修改
`BACKEND_TIMEOUT_SECONDS=<正整数秒>`，确认文件权限仍为 `0600`，再重启受管实例：

```bash
chmod 600 .lcf/runtime.env
lcf_managed restart
```

Codex 配置应为：

```toml
[mcp_servers.local-context-forge]
url = "http://127.0.0.1:8001/mcp"
tool_timeout_sec = 660.0
```

Web 的 30/660/1,860 秒与 nginx 的 1,860 秒目前不是运行时环境变量；要改变它们需要修改前端/
nginx 配置并重建 Web。提高客户端超时不能修复缺失 collection，也不能替代预生成 embedding。

## 模型服务检查

从 Mac：

```bash
curl --fail "http://WINDOWS_PRIVATE_IP:11434/api/tags"
```

从 API 容器：

```bash
docker compose exec api sh -lc \
  'curl --fail "$OLLAMA_BASE_URL/api/tags"'
```

第二条命令使用单引号，确保 `$OLLAMA_BASE_URL` 在容器内展开；不要改成宿主 shell 先展开的双引号。
若宿主可访问而容器不可访问，检查 Docker Desktop 网络、Windows 防火墙 RemoteAddress 和 Windows IP 是否变化。

## 升级流程

当前 legacy 路径没有通过端到端恢复演练的一键原地升级合同。已安装实例不要直接执行
`git pull && docker compose up`；先按[部署与运维](18-deployment-operations.md#27-legacy-升级)
记录版本/镜像摘要、完成一致性备份，并在数据副本演练。下面的裸 Compose 命令只展示未托管
开发 checkout 的验证动作。

1. 阅读 changelog 与 schema/migration 说明。
2. 停止发起 publish/delete 等同步写请求并等待返回，再运行 `./scripts/backup.sh`；脚本会自动
   recover orphan、drain 新 ingest，并在仍有活动 job 时拒绝归档。
3. 记录当前镜像摘要与 Git commit。
4. 拉取/切换目标版本。
5. 在测试数据副本执行：

   ```bash
   docker compose build --pull
   docker compose up -d
   ./scripts/smoke-test.sh
   ```

6. 检查现有 library/query、proposal 全文/metadata/source refs、post-publish lint，并手工调用 MCP 工具。
7. 如果 embedding 模型变化，安排 re-embed 窗口。

不要用浮动 `latest` 依赖作为可重复生产部署的唯一依据；本项目 Dockerfile 固定关键工具版本，升级时主动修改。

## 回滚

应用回滚与数据回滚分开：

- 仅代码/镜像回滚：切回旧版本并重建，不改 `/data`。
- schema 已迁移：旧程序可能不能读新数据，需要从升级前备份整体恢复。
- 某次页面内容错误：创建并发布修正 proposal；当前不要只做 Git revert，因为 API/runtime 正文来自 SQLite，且没有 Git→SQLite reconcile。
- 需要恢复整批发布状态：停止 writer，并恢复同一 manifest 中匹配的 SQLite、Wiki 与快照，不能拼接时间点。
- QMD 坏掉：删除/重建派生索引，不单独回滚 SQLite 或 Wiki。

## 磁盘容量

```bash
du -sh data/metadata.sqlite3 data/jobs data/locks data/sources data/facts data/proposals data/wiki data/qmd
df -h .
```

上面也是当前受管安装器唯一支持的数据布局：checkout 内的 `data/`。安装器没有
`--data-dir`，重跑时会把路径写回 checkout。旧的手工外置数据实例属于未托管配置；不要在其上
重跑安装器，也不要拿容器内 `/data` 去检查 Mac 磁盘。该缺口由
`TODO-LEGACY-CONTROL-001` 跟踪。

当前没有内置 retention/garbage-collection 命令。安全清理原则：

1. 可直接重建的 `data/qmd/cache`/索引可优先处理。
2. `data/jobs` validation 文件与 `data/proposals` 文件必须和 SQLite job/proposal 状态及审计保留策略协调，不能只按目录年龄删。
3. 未被任何 version/page 引用的 snapshot/facts 才能删除；当前没有 reachability 工具，应先做只读清单、备份和人工复核。

不要按目录年龄直接删除 `sources`；老 Wiki 可能仍引用它。

## 删除与应用层清理

```bash
LIBRARY_ID=acme-widget
curl --fail-with-body -X DELETE \
  "${LCF_API_BASE}/api/libraries/${LIBRARY_ID}?purge=true"
```

不带 `purge=true` 时只删除 SQLite 中的 library 及其级联元数据，便于保留磁盘审计材料。
带 `purge=true` 时，服务会在删除元数据前收集关联 job、proposal 与 version，然后尽力删除
该库的 `sources`、`facts`、Git Wiki、proposal/job 控制文件和已知 QMD collection。响应中的
`removed_paths`、`missing_paths`、`failed_paths` 与 `qmd_collections` 是本次清理报告；只要
其中出现失败，就应在仍持有响应和备份清单时人工复核。

`secure_erase` 固定为 `false`：这是应用层清理，不会覆盖 SSD block，也不会删除 Time Machine、
卷快照、外部备份、日志或模型服务缓存。处理高敏仓库时，使用加密卷、设备级密钥销毁和组织的数据
保留流程；不要把 `purge=true` 当作取证级擦除。

## 性能指标

最少记录：

- snapshot/facts/generation/proposal/publish 各阶段耗时（当前需从 job 时间/日志补充采集）。
- 每页 evidence 字节、输入/输出 token（若 provider 可提供）。
- proposal 首次通过率与人工拒绝原因。
- QMD query p50/p95、fallback 比率、top-k 命中率。
- 引用有效率、示例通过率、过期页面数。
- Windows GPU 使用与 OOM 次数。

不要只优化“生成速度”。持续知识库更关键的指标是：正确页面被找到、声明有证据、版本不串、更新可审阅。

## 定期任务建议

- 每日：health、备份结果、失败 job。
- 每周：Git remote/ref 变化检测、按需重新 ingest、QMD status。
- 每月：恢复演练、磁盘/保留策略、安全更新。
- 每次发布：lint、smoke、Wiki Git commit、备份标记。

自动 ingest 可以定时；自动 publish 应非常谨慎，至少限于低风险变更和完整验证通过的库。
