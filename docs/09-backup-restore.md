# 备份与恢复

## 备份范围

必须保持一致的运行状态：

- `/data/metadata.sqlite3`：library、job、proposal、发布指针等 SQLite 状态。
- `/data/jobs`：不可变 job 输入与 validation 报告；必须和 SQLite job 行处于同一时间点。
- `/data/wiki/<slug>/.git`：每个库的发布文档审计副本与历史。
- `/data/sources`：所有已发布页面引用的不可变源码快照。
- `/data/facts`：证据与增量更新基础。
- `/data/proposals`：尚未发布的审核工作。
- `/data/locks`：不承载业务数据的跨进程 advisory lock 文件；Windows 上可能含一个 byte-range
  lock 占位 byte。文件可重建且“存在”不表示有人持锁，但保留它们能维持完整数据树；真正的锁
  状态不会跨进程或恢复延续。

可重建：

- `/data/qmd/config` 与 `/data/qmd/native-config`：collection 注册信息会进入归档，Docker 与
  native 配置彼此独立。
- 根级 `/data/tmp`、`/data/qmd/cache` 与 `/data/qmd/native-cache`：脚本明确排除；模型缓存与
  向量索引可重建。

项目配置与凭据：

- 项目根目录 `.env` 不在 `/data` 备份范围；若另行备份，应进入单独的加密 secret 存储。
- Codex `auth.json`、服务凭据与部署 SSH key 本来就不得放入 `/data`。
- `imports/` 是宿主只读入站区，不进入 Git/release/数据备份；`/data/sources` 已保存固化快照。
- 源码快照必须按 `source_sha` 完整保存，备份脚本不会按文件名递归删除 `.env`、`*.key` 等仓库内容，否则会破坏不可变快照。evidence 层会按常见敏感名称排除，但尚无内容级 secret 扫描，所以整个备份必须按“可能包含私有源码/secret”的最高敏感级别处理。

## 备份前 drain

Compose API 正在运行时，备份脚本会先 fail-close 真正中断的 running/cancelling，再进入应用层
drain。`active_count` 只统计正在执行/取消中的 worker job；只要非零就拒绝备份。
`queued_count` 可以非零，因为 queued 是 SQLite 持久状态，会连同 request 一致归档并在恢复后
继续。脚本不会等待活动任务完成，也不能阻止同步 publish/delete。操作者仍应停止发起写请求，
等待同步请求返回，并可用下面命令预检：

```bash
curl --fail-with-body -X POST \
  http://127.0.0.1:8000/api/admin/jobs/recover-orphans |
  jq
curl --fail-with-body -X POST \
  http://127.0.0.1:8000/api/admin/ingest/drain |
  jq
curl --fail http://127.0.0.1:8000/api/jobs/active |
  jq -e '.active_count == 0'
```

最后一条检查输出 `true` 且退出码为 0 才通过；未通过就等待 job 到终态后再运行备份。`/api/jobs/active`
不受历史 job 列表的 200 条上限影响。当前默认是单 API 进程；若自行部署多个 replica，脚本的单个
`LCF_API_URL` 不能替你 drain 整个集群，必须让每个实例进入 drain，并通过受控运维入口确认共享
数据树没有 writer。

不要让备份脚本去“终止一个快完成的 job”。脚本给 Compose graceful stop 的预算默认是 3,600 秒，
可用正整数 `LCF_BACKUP_STOP_TIMEOUT_SECONDS`（导出环境变量或 `.env`）调整；长预算的目的仍是
让同步 publish/QMD 写入有机会结束，不会替你等待 active worker。正常流程在 active=0 后才停
服务，因此 queued 安全保留。异常强杀时，queued 仍会继续；只有当时已经 running/cancelling 的
任务会在下次启动按 owner lock fail-closed 为 `stage=orphaned`。它们可能已调用 CLI 或留下
`proposed/failed/partial` version，不能盲目自动续跑。

若只做了上面的手工预检而决定不备份，可恢复接受 ingest：

```bash
curl --fail-with-body -X POST \
  http://127.0.0.1:8000/api/admin/ingest/resume |
  jq
```

脚本自己触发的 drain 会在失败 cleanup 时自动 resume；正常备份会停止再启动 API，新实例默认
恢复接受 ingest。

## 创建备份

```bash
./scripts/lcf backup
```

这是 `scripts/backup.sh` 的统一运维入口。脚本要求 `curl`、Python 3.8+、`rsync`、`tar` 以及
`shasum`/`sha256sum` 之一；默认写到
`./backups/`，文件名包含 UTC 时间。`BACKUP_DIR` 必须位于加密、访问受控的文件系统：脚本会把
包含完整私有源码的**未压缩 staging** 建在该目录内，使 staging 与最终 archive/checksum 位于
同一文件系统。容量规划要同时覆盖一份完整 data staging、压缩 archive、checksum 和操作余量，
不能只按 `.tar.gz` 大小准备空间。脚本：

1. 获取备份锁。
2. 若 Compose API 正在运行，先恢复中断的 running/cancelling、drain 新任务并要求
   `active_count=0`；queued 可随备份保存，否则拒绝归档并自动 resume。
3. 短暂停止 Compose 的 API/MCP writer；若安装了 `lsof` 且发现原生 API 监听或数据库仍被打开，
   则拒绝继续。原生模式不能使用这套在线 drain，必须先人工等待终态并停止原生服务。
4. 用 `rsync` 建立同盘敏感 staging，再完整归档一致的 SQLite、job/lock、Wiki、snapshot、facts
   与 proposal；只排除明确可重建的
   根级 `tmp`、`qmd/cache` 与 `qmd/native-cache`，保留快照内安全 symlink/hardlink。
5. 在 `BACKUP_DIR` 先生成隐藏的 archive/checksum `.partial` 文件，把 manifest（版本、时间、
   包含/排除项）放入 archive，并把两个文件权限设为 `0600`。
6. fsync 两个 partial 与目录，先 rename checksum、再 rename archive 为最终名称，随后再次
   fsync `BACKUP_DIR` 的目录项（文件系统不支持目录 fsync 时跳过）。这样中断最多留下可识别的
   partial 或孤立 sidecar，不会发布一个没有 sidecar 的正式 archive；这仍不能替代文件系统、
   控制器与介质自身的断电保障。

指定路径：

```bash
BACKUP_DIR=/Volumes/Encrypted/LCF \
  ./scripts/backup.sh
```

若 Compose 未运行且系统安装了 `lsof`，脚本会拒绝仍有原生 API listener 或打开
`metadata.sqlite3` 的情况；没有 `lsof` 时无法提供这层检测。不要绕过检查在写入时复制
SQLite/Wiki。脚本不提供加密；`0600` 只限制同机其他账号，不能代替 FileVault、BitLocker、
加密卷或离机加密。

`LOCAL_DATA_DIR` 和 `BACKUP_DIR` 都可由导出的环境变量或项目 `.env` 配置。若数据根位于外置盘，
脚本归档的是该实际目录，而不是固定的 `./data`；确认备份目录不在数据目录内部。
`LOCAL_DATA_DIR` 是 Compose/备份使用的宿主路径，容器内仍是 `/data`。当前
`scripts/dev-native.sh` 固定使用项目 `./data`，不会读取这个宿主映射变量；外置数据根应使用
Compose，或先显式改造并验证 native helper，避免同时写出两套数据树。

## 校验

```bash
ARCHIVE=./backups/lcf-backup-20260728T120000Z.tar.gz
shasum -a 256 -c "${ARCHIVE}.sha256"
tar -tzf "$ARCHIVE" | sed -n '1,40p'
```

备份完成不等于可恢复。至少每月在另一目录做一次演练。

恢复脚本默认**强制要求**相邻 `.sha256`。它必须只有一个非空记录、包含合法 SHA-256，并且记录的
basename 必须精确等于所选 archive；缺失、格式不符或摘要不匹配都会停止。只有 archive 已通过
另一套独立、可信的认证机制时，操作者才能显式豁免：

```bash
./scripts/lcf restore \
  --archive /trusted/lcf-backup.tar.gz \
  --target ./data \
  --allow-missing-checksum
```

该 flag 会打印 warning；它不是“遇到旧备份自动继续”的兼容模式。

相邻 `.sha256` 只能发现意外损坏，不是签名、MAC 或来源证明；攻击者若能同时替换 archive 和
checksum，校验仍会通过。只恢复自己创建、来自可信受控介质的备份。恢复脚本仍会在解压前限制成员
类型、路径和链接边界，拒绝 setuid/setgid，并忽略 archive owner；普通执行位会保留，以维持源码
快照语义。

## 恢复

恢复脚本要求 `tar`、`awk` 与 Python 3.8+；shell 部分保持 macOS 自带 Bash 3.2 兼容，不依赖
`wait -n` 等新 Bash 功能。Python 先校验 manifest、成员、展开大小、路径与链接，再按“目录 →
普通文件 → symlink → hardlink”提取，并在文件系统支持时 fsync 常规文件与 staging 目录。默认
最多接受 500,000 个 archive 成员、最多 100 GiB 常规
文件展开总量；成员数上限是固定保护，大小上限可用导出的
`LCF_RESTORE_MAX_BYTES`（整数 bytes）调整。这个变量不会从 `.env` 读取，不要在未核实磁盘空间与
备份来源时盲目提高。任何位于 service-owned `.git` 路径内的 symlink/hardlink 都会被拒绝。

展开 staging 使用目标目录的**同级目录**（例如 `.data.restore-stage.XXXXXX`），所以即使 target
位于外置加密卷，最终 `mv` 仍在同一文件系统内原子 rename。目标盘需要同时容纳展开 staging 与
现有 target/quarantine。最终 rename 与 chmod 后，脚本还会在支持时 fsync target 及父目录。
若最终 rename 失败且 target 尚不存在，cleanup 会把原 quarantine 移回原路径；脚本不会声称
跨介质事务、quarantine 与新 target 的双路径原子提交，或断电后的全局 ACID。

恢复是破坏性操作。`--target` 与 Makefile 的 `TARGET` 都是必填项，且必须是宿主机映射到容器
`/data` 的真实路径，不是容器路径 `/data`。默认 `.env` 的目标是 `./data`：

在执行 restore 前先人工停止 native API/MCP/QMD writer。校验 checksum 后、创建 staging
之前，脚本会拒绝仍在运行的 Compose API/MCP，并在安装 `lsof` 时拒绝默认/配置端口上的 API
listener 或打开的目标 `metadata.sqlite3`；它仍不能识别所有自定义端口、容器或瞬时 QMD 进程。

```bash
docker compose down
make restore \
  ARCHIVE=./backups/lcf-backup-20260728T120000Z.tar.gz \
  TARGET=./data
docker compose up -d
./scripts/smoke-test.sh
```

若 `.env` 使用 `LOCAL_DATA_DIR=/Volumes/Encrypted/LCF/data`，则显式使用同一个宿主路径：

```bash
docker compose down
make restore \
  ARCHIVE=./backups/lcf-backup-20260728T120000Z.tar.gz \
  TARGET=/Volumes/Encrypted/LCF/data
```

相对 `TARGET` 从项目根解析。脚本不会替你从 `.env` 推断恢复目标，这个显式门用于避免恢复到错误
磁盘。需要覆盖默认 100 GiB 上限时，可在一次命令上导出，例如
`LCF_RESTORE_MAX_BYTES=214748364800 make restore ...`；这只提高到 200 GiB，不改变固定成员数上限。

默认拒绝覆盖非空 target。若确实要替换：

```bash
./scripts/restore.sh \
  --archive ./backups/lcf-backup-20260728T120000Z.tar.gz \
  --target ./data \
  --replace \
  --yes
```

`--replace` 会先把现有 target 移到同级带时间戳的 quarantine 目录，不直接永久删除；确认恢复
成功后再人工处理。quarantine 与恢复数据同等敏感，且不会自动清理。先完成完整核验、记录保留
决定，再按组织流程处理；不要在脚本中用宽泛递归删除命令清理它。

整个流程只用于你创建并控制的备份。checksum 能发现意外损坏，但攻击者可以同时替换 archive 与
sidecar；恢复器的路径/类型检查也不能把不可信备份变成可信来源。

## 恢复后检查

```bash
docker compose ps
curl --fail http://127.0.0.1:8000/api/health
docker compose exec api qmd status
```

然后：

1. 列出 library 与版本。
2. 查询至少一个旧版本与一个最新版本，并确认响应 `engine`。
3. 检查 proposal 与 job 状态。恢复后 queued 会由持久 FIFO 继续；只有备份中原本
   running/cancelling 且 owner 已不存在的行会 fail-closed。查看：

   ```bash
   curl --fail http://127.0.0.1:8000/api/jobs/active |
     jq
   curl --fail "http://127.0.0.1:8000/api/jobs?limit=200" |
     jq '[.[] | select(.stage == "orphaned")]'
   ```

   queued 会保持排队并在 worker 启动后继续。旧 owner 不存在的 running/cancelling 会原子变为
   `failed/orphaned`；若仍显示幽灵执行中行，可手工重扫：

   ```bash
   curl --fail-with-body -X POST \
     http://127.0.0.1:8000/api/admin/jobs/recover-orphans |
     jq
   ```

   `preserved_jobs` 包括 queued 与仍有活 owner 的任务。`recovered_jobs` 只表示未知副作用的
   执行中任务已终态化；根据 `retryable` 重试，或检查 snapshot/proposal/version 后创建新的
   version ingest。不要直接改 SQLite。
4. 检查 Wiki Git：

   ```bash
   DATA_TARGET=./data
   find "$DATA_TARGET/wiki" -type d -name .git -prune -print |
     while IFS= read -r git_dir; do git --git-dir="$git_dir" fsck; done
   ```

   外置数据根时把 `DATA_TARGET` 设为本次显式 restore target。

5. 检查全局 embedding 状态，并从 fully published corpus 排队重建：

   ```bash
   curl --fail http://127.0.0.1:8000/api/system/status | jq '.embedding'
   curl --fail-with-body -X POST -H 'Content-Type: application/json' \
     -d '{}' http://127.0.0.1:8000/api/rebuilds | jq
   ```

   rebuild job 通过当前 API 枚举 `versions.status=published`、注册完整 Wiki corpus，再做全局
   `embed -f`；不索引 review/rejected/partial，也不调用 LLM。完成前 query lexical fallback。
   不要直接运行 qmd 绕过 writer lock；高级排错才使用 `scripts/reindex.sh`。

## 3-2-1 策略

- 3 份副本：工作数据 + 本地加密备份 + 异机备份。
- 2 种介质：Mac 内置盘与外置盘/NAS。
- 1 份离机：加密后存放；确认源码许可允许。

Windows Ollama 的模型文件可重新下载，通常不需要进入 LCF 备份。若保存自定义量化模型，单独记录模型 digest 与 Modelfile。

## 灾难场景

### 只有 Wiki Git

仍可恢复已发布 Markdown/JSON，但 `reindex.sh` 依赖 SQLite 中的 fully published version 清单，
不能只凭 Wiki 自动恢复全部 SQLite/QMD 注册。UI 的 job/proposal 元数据与源码引用验证会不完整。
应把服务置为只读，直到重新 ingest source 或完成经过副本验证的专用恢复。

### 只有 SQLite

不够。SQLite 中的路径/commit 不能替代 Wiki 和源码文件。必须从另一备份恢复匹配的数据树。

### SQLite 与 Wiki 时间点不同

选择同一备份 manifest 的整组文件恢复。不要手工把不同时间点拼在一起。当前 API/runtime 读取 SQLite page 正文，Git 是审计副本，而且没有现成 reconcile 工具；若无法取得一致备份，应先只读隔离并开发/验证专用恢复工具，不直接编辑数据库或假设 Git revert 会生效。

### 密钥疑似进入备份

先吊销/轮换，不要只删除备份。确认所有副本、远端、日志和校验清单的处理策略；必要时按组织事件响应流程上报。
