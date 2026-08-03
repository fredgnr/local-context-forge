# 部署与运维总手册

本文记录 Electron、源码开发、历史 legacy Docker/Web 和正式 Release。legacy 小节已弃用，
仅为后续 removal 盘点保留，不再是一条可选择的受支持路径。
它回答“现在应该运行什么”，而不是把尚未通过的门禁写成安装教程。当前状态以
[项目状态快照](development/status.md)为准，详细桌面 UI 使用见
[Electron 完整指南](16-electron-desktop-guide.md)。

> **操作停止：** 不要执行本文 legacy 安装/Compose/localhost/GHCR 命令；它们只描述待删除
> owner。当前 container tag 双触发和未配置 trust locks 使所有新 release tag、Draft 与公开
> Release 均为 NO-GO。权威顺序是 W02 engineering smoke → W10/W11 slices → W03 engineering
> package → W04–W12 physical → W13 final gates → W14–W16 formal release；详见
> [work plan](development/work-plan.md)。

## 1. 先选择路径

| 你的目标 | 现在使用的路径 | 入口 |
| --- | --- | --- |
| 立即在本机稳定使用 | 暂停 | 等经过审查的 Electron DMG；当前没有受支持稳定发行 |
| 开发 Electron UI/Main/Python 合同 | Electron source mode | 本文第 3 节 |
| 后续验证 legacy slice / 工程能力 | 明确 non-release 的 W02/W03 package | 本文第 3.4 节；当前未实现 |
| 验证正式候选 | W15/W16 受保护 exact Draft + continuity/物理 M4 | 本文第 6–8 节 |
| 普通用户安装 Electron | 暂停 | 等经过审查的公开 DMG |
| 使用 Windows 4060 加速生成 | 不支持 | future remote-worker 需独立 ADR |

三个容易误用的入口：

- `./install.sh`、`install.command` 和 `make install` 都是 **legacy Docker/Web**，不是
  Electron；
- `npm --prefix desktop run start:source` 是开发模式，不是 all-in-one 包；
- `npm --prefix desktop run dist:mac` 是 ad-hoc `*-UNOFFICIAL` 构建，不是正式 Release。

不要让 desktop 与 legacy 同时写同一目录。不要把 legacy `./data` 直接覆盖到 Application
Support。

## 2. 历史路径 A：已弃用的 Legacy Docker/Web

> 本节命令不得用于新部署。它们将在 ITER-0008 的 W10/W11 slices 删除，只用于确认 removal scope；项目不提供
> 修复、迁移或兼容窗口，也不会自动清理用户已有 container/volume/data。

### 2.1 前置条件

需要：

- macOS 和本仓库 checkout；
- Docker Desktop，或 Docker CLI + Compose v2 + 已启动的 Colima；
- 当前 Docker context 已由用户选择；
- Git、curl、tar、rsync、Python 3.9+ 和 jq；
- 若使用 Codex/Cursor provider，相应 CLI 已安装并在当前 macOS 用户登录。

安装器不会切换 Docker context，不会安装第三方 CLI，不会把 `~/.codex`、Cursor 凭据或
Docker socket mount 进容器。首次没有可用 CLI 时可进入 mock demo；mock 不是生产 Wiki
生成器。

### 2.2 安装

当前 `scripts/lcf` 会从 `.lcf/runtime.env` 读取安装记录，但还没有清除调用者 shell 中优先级
更高的 Compose 插值变量，也没有固定 `COMPOSE_PROJECT_NAME`。残留的
`LOCAL_DATA_DIR`、`LCF_BIND_HOST`、端口、镜像或 `COMPOSE_PROJECT_NAME` 可能改变目标数据、
监听地址、镜像或 Compose project。该 legacy 缺口不再修复；控制脚本由
`TODO-LEGACY-REMOVE-DEPLOY-001` 删除，相关 provider/transport caller 分别由
`TODO-LEGACY-REMOVE-PROVIDER-001`、`TODO-LEGACY-REMOVE-TRANSPORT-001` 清理。

因此先在**受管实例的仓库根目录**定义一个只保留 `HOME` 和 `PATH` 的会话级入口；本章后续
`lcf_managed` 命令都依赖这个定义：

```bash
LCF_CONTROL_BIN="$(pwd -P)/scripts/lcf"
lcf_managed() {
  env -i \
    HOME="$HOME" \
    PATH="$PATH" \
    "$LCF_CONTROL_BIN" "$@"
}
```

它会清除 `COMPOSE_*`、`LOCAL_*`、`LCF_*` 和端口等调用者覆盖。需要自定义 Docker config 的
高级用户应单独审查绝对 `DOCKER_CONFIG` 路径后，把它作为唯一额外 allowlisted 变量加入
`env -i`；不要保留 `COMPOSE_*`。不要用 `sudo`。

首次安装：

```bash
lcf_managed install
```

高级选项：

```bash
lcf_managed install --help
```

例如使用 GHCR 镜像而非本地构建：

```bash
lcf_managed install \
  --images ghcr \
  --ghcr-owner fredgnr \
  --image-tag main
```

安装器：

1. 检查 Mac、资源、Docker/Compose、工具和端口；
2. 记录当前 Docker context；
3. 把非 secret 运行配置写入 mode-`0600` 的 `.lcf/runtime.env`；
4. 创建 mode-`0700` 的 `data/`、`imports/`、`backups/`；
5. 为 host runner 安装当前用户 LaunchAgent；
6. 启动 `api`、`mcp`、`web`；
7. 运行 health/smoke 后打开 Web。

默认监听：

| 服务 | 地址 |
| --- | --- |
| Web | `http://127.0.0.1:8080` |
| API/OpenAPI | `http://127.0.0.1:8000/docs` |
| MCP | `http://127.0.0.1:8001/mcp` |

### 2.3 日常控制

安装后使用上节定义的 clean-environment 包装器。`scripts/lcf` 会读取安装时记录的 context
和 `.lcf/runtime.env`，但**不会自行隔离调用者环境**，所以不要退回直接执行
`./scripts/lcf`：

```bash
lcf_managed status
lcf_managed doctor
lcf_managed start
lcf_managed stop
lcf_managed restart
lcf_managed logs
lcf_managed uninstall
```

`backup`/`restore` 还会把允许的调用者变量传给子脚本；默认使用 `lcf_managed` 会全部清除。
只有本章 2.5/2.6 明确列出的变量可在一次命令中重新加入。

`stop` 停止服务，`down` 移除容器但保留数据，`uninstall` 移除服务和 LaunchAgent但保留
`data/`、`imports/`、`backups/` 和 `.lcf/`。

除非你明确传入与 `.lcf/runtime.env` 相同的 env file 和已记录 context，不要用裸
`docker compose` 管理已安装实例。裸命令可能命中另一个 context、默认 `./data` 或启动第二
个 writer。

### 2.4 配置变更

已安装实例的权威配置是：

```text
.lcf/runtime.env
```

当前受管安装器只支持 checkout 内的固定 `data/`、`imports/` 和 `data/runner/`。它没有
`--data-dir`/`--imports-dir`，每次执行都会把这些路径写回 checkout。不要把手工改过的外置
`LOCAL_DATA_DIR` 称为受支持受管配置；尤其不要在这种实例上重跑安装器，否则可能启动一个新的
checkout 数据树。项目不再实现已 superseded 的 `TODO-LEGACY-CONTROL-001`；需要保留外置
active data 时，只能继续固定删除前版本并把实例视为明确记录、独立负责的未托管部署。W11
源码清理不得读取、迁移或删除该数据。

对标准受管布局，不要只修改项目根 `.env`。端口/provider/image 变更推荐重新执行安装器并传入
显式选项，例如：

```bash
lcf_managed install \
  --web-port 18080 \
  --api-port 18000 \
  --mcp-port 18001 \
  --no-open
```

然后运行：

```bash
lcf_managed doctor
lcf_managed status
```

`.lcf/runtime.env` 可能包含部署拓扑或内部地址，虽然不应包含 CLI credential，仍按私有配置
处理，不提交仓库、不粘贴到 issue。

### 2.5 备份

使用已经定义的 clean-environment 入口，避免遗留变量覆盖受管记录：

```bash
lcf_managed doctor
lcf_managed backup
```

若要指定外部加密备份目录，不要临时 `export`；在一次最小环境命令中只 allowlist 该变量：

```bash
env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  BACKUP_DIR=/absolute/encrypted/path \
  "$LCF_CONTROL_BIN" backup
```

backup 流程会：

- 阻止新 ingest；
- 检查活动任务；
- 暂停 writer；
- 复制数据和 manifest；
- 生成 tar.gz 与 SHA-256 sidecar；
- 恢复服务。

备份包含 snapshot、facts、proposal、SQLite、Wiki、jobs 和 QMD state，因此按“可能包含
私有源码与 secret material”的最高敏感级别保存。checksum 防意外损坏，不认证来源。

当前 backup **不完整包含部署重建信息**：

- `.lcf/runtime.env`
- `.lcf/install-state.json`
- LaunchAgent
- `imports/`

灾难恢复时应把它们作为独立、加密的运维记录备份，且不与公开 archive 混放。不要把 Codex/
Cursor auth cache 放入任何项目备份。

### 2.6 恢复

恢复是会切换 active data 的高风险操作。先：

1. 核对 archive 来源和 `.sha256`；
2. 确认目标是安装时实际 `LOCAL_DATA_DIR` 的宿主路径；
3. 退出 desktop App，确认没有另一套 writer；
4. 运行 `--help`、保存当前备份并再次核对精确 target。

入口：

```bash
lcf_managed restore --help
```

当前恢复器**没有 dry-run**；`--help` 不读取或写入数据。真正执行时先停止受管服务，再通过
clean-environment 入口使用明确的绝对 archive 和 target：

```bash
lcf_managed stop
lcf_managed restore \
  --archive /absolute/path/to/lcf-backup.tar.gz \
  --target /absolute/path/to/checkout/data \
  --replace
```

`--replace` 默认交互确认；自动化另加 `--yes` 会移动当前 active 数据并切换
恢复树；虽然脚本保留 quarantine，也必须经过二次核对。`--allow-missing-checksum` 会显式
放弃默认 checksum，只能在停止 writer、精确 target 和 archive 已由另一条可信渠道认证时追加。

恢复完成后：

```bash
lcf_managed start
lcf_managed doctor
lcf_managed status
```

再核对 library/page/job 数量、Wiki Git、source refs、corpus revision、QMD state 和一次只读
查询。详见[备份与恢复](09-backup-restore.md)。

### 2.7 Legacy 升级

当前没有经过完整验证的一键升级命令。不要直接在有活动任务时 `git pull && docker compose
up`。最低安全流程：

1. 记录当前 checkout commit、image digest、`.lcf/runtime.env` 和 Docker context；
2. `lcf_managed doctor`，等待 job 终态；
3. `lcf_managed backup` 并在另一位置校验 archive；
4. 评审目标版本的 schema、migration、release notes 和回滚说明；
5. 在独立 checkout 或明确 ref 准备目标版本；
6. 在目标 checkout 重新定义 `LCF_CONTROL_BIN`/`lcf_managed`，再用
   `lcf_managed install`，不要裸 Compose；
7. 运行 doctor、smoke 和数据计数；
8. 失败时停止新 writer，按该版本记录恢复旧 checkout/image/data。

在桌面迁移门禁完成前，不承诺 legacy 与 desktop 数据可原地互换。

### 2.8 Legacy 卸载

```bash
lcf_managed uninstall
```

它不是“彻底删除”：

- 保留 `data/`、`imports/`、`backups/`、`.lcf/`；
- 不删除镜像或 Docker 数据；
- Docker 不可用时，残留容器可能需要在原 context 中人工核对；
- 不提供 SSD secure erase。

删除保留数据是不可恢复动作，应先验证备份并显式确定精确目录。本项目不提供递归删除 home、
workspace 或未知 volume 的快捷命令。

### 2.9 高级诊断与裸 Compose

只有 `scripts/lcf` 没有提供所需的只读诊断时才使用裸 Compose。先在
`.lcf/runtime.env` 中人工核对 `LCF_DOCKER_CONTEXT`，不要直接 `source` 整个 env 文件；然后从
仓库根目录设置两个临时变量：

```bash
LCF_REPO_ROOT="$(pwd -P)"
LCF_CONTEXT="<从 .lcf/runtime.env 核对出的精确值>"

docker --context "$LCF_CONTEXT" compose \
  --project-directory "$LCF_REPO_ROOT" \
  --env-file "$LCF_REPO_ROOT/.lcf/runtime.env" \
  -f "$LCF_REPO_ROOT/docker-compose.yml" \
  ps
```

把最后的 `ps` 换成以下**只读**动作之一：

```text
logs --since=30m --no-color api mcp web
exec api qmd status
exec api qmd collection list
```

完成后清除临时变量：

```bash
unset LCF_REPO_ROOT LCF_CONTEXT
```

不要在不明确 downtime、备份和恢复点时把最后一行换成 `down`、`up`、`build`、`pull`、
`rm` 或 QMD write 命令。任何 mutation 仍回到本章的 `lcf_managed` 或对应 runbook。

## 3. 路径 B：Electron source mode

### 3.1 用途与前置

用于开发 UI、Main、IPC 和 Python domain。需要 Git、uv/Python、Node/npm 和源码，不证明
all-in-one。

版本矩阵：

| 用途 | 版本 |
| --- | --- |
| Backend source 支持 | Python 3.11+ |
| 普通 source CI | Python 3.12 |
| 正式 bundled runtime | CPython 3.13.14 |
| Desktop/Web source CI | Node 24 |
| QMD/release runtime | Node 22.23.2 |

不同模式的 venv：

| 路径 | venv |
| --- | --- |
| `make ci-python-install` / Electron source | `backend/.venv` |
| `./scripts/macos-bootstrap.sh --native` | 仓库根 `.venv` |

不要混用两者的可执行路径。

### 3.2 安装和验证

```bash
make ci-python-install
npm --prefix web ci
npm --prefix desktop ci
```

运行全量 source aggregate：

```bash
make ci-source
```

`make ci-source` 当前不包含 QMD worker tests，需另行：

```bash
npm --prefix desktop/workers/qmd ci
npm --prefix desktop/workers/qmd test
```

构建 renderer 并启动：

```bash
npm --prefix web run build
make renderer-stage

LCF_RENDERER_DIR="$(pwd)/web/dist" \
LCF_SIDECAR_BIN="$(pwd)/backend/.venv/bin/lcf-service" \
npm --prefix desktop run start:source
```

Main 只接受绝对 renderer/sidecar 路径，不从 PATH 发现 sidecar。若没有提供经过审计的 QMD
source runtime 环境，QMD supervisor fail closed，查询保留 lexical。

### 3.3 Source mode 不证明什么

- packaged resources 和 nested Mach-O；
- 自签名身份或 DMG；
- clean-user 和 Gatekeeper；
- 无系统 Python/Node/Git；
- 真实 QMD native/model；
- 真实签名 Codex discovery/onboarding；
- update feed 或跨版本恢复。

本地 ad-hoc 打包：

```bash
npm --prefix desktop run dist:mac
```

还要求 Python/QMD/renderer/companion staging 已按构建工具生成和审计，且 public trust pins
已 provision。当前 `unprovisioned` locks 应让 `beforePack` fail closed；即便成功也只是
`*-UNOFFICIAL`。

### 3.4 规划中的非发行工程包

当前 `dist:mac` 不能作为 W02：base `beforePack` 会无条件审计 production update trust，而当前
locks 正确地是 `unprovisioned`。后续实现必须新增与 formal release 隔离的显式 mode，不得把
trust audit 改成全局宽松。

| Class | 最低用途 | 必须具备 | 禁止 |
| --- | --- | --- | --- |
| W02 engineering smoke | 每个 removal slice 的 feedback | exact commit/digest/arch/inventory、launch、renderer/preload、private UDS health/domain request、quit/no orphan、no INET listener、exercised path 无 system runtime discovery | production secret/pins、tag/upload/Draft/Release、update network |
| W03 engineering test package | cleaned tree 的 W04–W12 物理载体 | 完整 renderer/Python/QMD/companion staging、inventory/SBOM/notices/test entry | 冒充 formal pack/install/release evidence |

两者必须标记 `UNOFFICIAL`、`engineering-only`、`publishable=false`，使用 unsigned/ad-hoc identity，
updater `unavailable` 且不联网。当前两条门禁均 `not-run`；本手册没有可复制的实现命令。

## 4. 路径 C：普通用户的 Electron 安装

当前没有推荐安装资产。本节只定义将来的合格入口。

公开 Release 必须同时包含并相互绑定：

- arm64 DMG；
- `SHA256SUMS`；
- `release-manifest.json`；
- canonical update manifest 与 detached Ed25519 signature；
- public update key；
- runtime manifest、SBOM/notices 所需证据；
- 明确的 self-signed、not notarized、not hardened、automatic apply disabled 声明。

用户流程：

1. 从 canonical GitHub Release 下载同一版本的完整资产；
2. 核对 DMG SHA-256 和 manifest；
3. 拖 App 到 `/Applications`；
4. Gatekeeper 阻止时使用 Finder“打开”或“系统设置 → 隐私与安全性 → 仍要打开”；
5. 不关闭 Gatekeeper、不清除 quarantine、不使用 `sudo`；
6. 在当前用户运行 `codex login`；
7. 打开 App，完成仓库、队列、审核、查询、embedding 和 MCP。

详见[Electron 完整指南](16-electron-desktop-guide.md)。

## 5. Desktop 数据、备份、恢复和卸载

当前实现：

```text
~/Library/Application Support/Local Context Forge/
~/Library/Caches/Local Context Forge/qmd-runtime/
```

第一处包含 SQLite、snapshots、facts、proposals、Wiki、jobs、QMD state、MCP metadata 和
update downloads。第二处是可重建 QMD/model cache。

当前 desktop 只有退出 App 后的手工副本方法，尚无通过 `VAL-DATA-001` 的 manifest、
checksum、schema/integrity、writer detection 和物理恢复流程。手工备份整个 Application
Support 会把可重下载的 update DMG 也复制进去；这是当前实现与 ADR-0004 目标的已知差距。

在修复完成前：

1. 完全退出 App；
2. 确认没有 Python/QMD/companion 仍在运行；
3. 对整个 Application Support 创建只读、加密副本；
4. 单独记录 App 版本、schema、文件计数和摘要；
5. 恢复到 staging 位置做 SQLite integrity 和只读检查；
6. 不把 legacy `data/` 原地覆盖进该目录；
7. 不把缓存存在视为可恢复数据的充分条件。

卸载顺序：

1. App 可运行时先在设置中清除 App 自有 Codex MCP target；
2. 退出 App；
3. 删除 `/Applications/Local Context Forge.app`；
4. 默认保留 Application Support；
5. cache 可单独删除并在下次使用时重建；
6. 只有验证备份和精确 target 后，才考虑删除持久数据。

当前 App 无法启动时，MCP ownership ledger 的人工恢复流程仍需实现和真机验证，不应凭猜测
编辑 `~/.codex`。

## 6. GitHub 发布控制面

本节是 W14，必须等待 W13 final `VAL-ELECTRON-CUTOVER-001` 与
`VAL-LEGACY-ABSENCE-001` 同时通过。它不是 W02/W03 工程包的前置，当前不得提前配置。

正式发布前需要两个 Environment：

### 6.1 `macos-signing`

- required reviewer；
- prevent self review；
- GitHub UI 中关闭 administrator bypass；
- deployment policy 精确只允许 tag `v*.*.*`；
- release workflow 使用的唯一 private credential：
  `DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`。

这里的“唯一”限定为本 release workflow 的私有 credential，不声称组织或仓库不存在其他无关
secret。

### 6.2 `macos-release`

- required reviewer；
- prevent self review；
- GitHub UI 中关闭 administrator bypass；
- deployment policy 精确只允许 branch `main`；
- Environment/repository release secret 集合为空且无长期签名凭据；promotion job 仍使用
  GitHub 自动签发的短期 `GITHUB_TOKEN`。

### 6.3 Rulesets 与 immutable

| 名称 | Target | 必需合同 |
| --- | --- | --- |
| `protected-main` | `refs/heads/main` | PR、独立 approval、dismiss stale、last-push approval、resolve threads、no force/delete、无 bypass |
| `release-tag-creation` | `refs/tags/v*.*.*` | creation 只允许 canonical owner bypass |
| `immutable-release-tags` | `refs/tags/v*.*.*` | 禁止 update/delete、无 bypass |

同时开启 GitHub Immutable Releases。

Bootstrap 验证的是 exact policy，不只是最低集合。当前工具会拒绝额外 rule type、额外
include/exclude、错误 bypass 或 Environment secret membership；若管理员希望增加 required
status checks 等常见规则，必须先审查并更新 bootstrap/source policy，不能在 UI 中悄悄加完
后假设工具仍会接受。

真实设置证据应保存脱敏的 Environment/ruleset/immutable API 输出、admin-bypass UI 截图、
时间和独立复核人；源码单元测试不证明 GitHub 当前状态。

## 7. Provision 自签名与更新凭据

本节是 W15，只能在 W14 的真实设置证据通过后执行。工程包不得读取或生成这些材料。

在可信管理员主机和 clean canonical checkout：

```bash
python3 tools/bootstrap_desktop_release_keys.py --help
```

确认 GitHub UI 中两个 Environment 都禁止 admin bypass，然后：

```bash
python3 tools/bootstrap_desktop_release_keys.py \
  --repo fredgnr/local-context-forge \
  --upload \
  --confirm-admin-bypass-disabled
```

脚本生成一个 versioned credential bundle，经 stdin 上传到 `macos-signing` Environment。
私有 Ed25519 key、PKCS#12、certificate password 和 bundle 不得进入仓库、artifact、cache、
日志、shell history 或聊天。

只允许提交：

- `desktop/resources/update/update-metadata-ed25519-public.pem`
- `runtime/update-metadata-key.lock.json`
- `runtime/macos-codesign-certificate.lock.json`

评审要求：

- 两个 lock 均为 `provisioned`；
- 三个 public artifact 属于同一 32-hex generation；
- public key 是 Ed25519，PEM digest 与 lock 一致；
- certificate fingerprint、固定 identity 和 generation 一致；
- diff 中没有 `.p12`、private PEM、password、bundle、keychain 或 secret export。

轮换必须使用显式 `--rotate`，并按新的 generation 重新执行完整发布/更新门禁。

## 8. 正式候选、真机测试与 promotion

本节属于 W15/W16，只接受 W13/W14 完成后的 formal candidate。W02/W03 或任一 legacy slice
artifact 不能上传为 Draft，也不能被 promotion。W13 engineering evidence 只解锁 W14；正式
候选还必须通过 `VAL-RELEASE-CONTINUITY-001`。

### 8.1 当前待删除的同 tag 耦合

在 W11 尚未实施的当前仓库中，同一个 `vX.Y.Z` tag 会同时触发：

- container image SemVer 发布；
- desktop build/sign 与 Draft 创建。

两条 workflow 并行且不是一个原子事务：GHCR SemVer 镜像可能在 desktop 等待
`macos-signing` 审批、构建失败或尚未完成真机门禁时已经公开。Desktop Draft 成功也不证明
container job 成功。发布记录必须分别保存两条 workflow 的 run、commit/tag 和 artifact/image
digest，并明确任何“只完成一半”的状态。

因此当前禁止 push release tag。W11 必须删除 container/GHCR trigger 与 tag coupling，并在
source policy 上证明 tag 只进入 desktop candidate；不得删除远端既有 GHCR package。W14/W15
启用 immutable tag 后错误 tag 不能移动或删除。Tag 必须与 `runtime/version.json` 完全一致，
并按 [Release runbook](development/desktop-release.md)统一评审。

### 8.2 阶段一：只创建 Draft

创建 tag 前，W15 必须先实现并运行独立 continuity verifier：绑定 W13 checkpoint，证明到
formal tag 候选 commit 的 diff 只含 allowlisted production public pins/release metadata/version，
并重跑 source/aggregate absence。当前 workflow 没有 checkpoint 输入或 diff allowlist，这项
evidence 为 `not-run`。verifier/allowlist/schema 必须在 W13 checkpoint 前落地并冻结；若 W15
才新增或修改，必须先建立新 W13 checkpoint 并重跑。在补齐前本节仍不可执行。

该前置通过后，owner 才从受保护 `main` 创建 exact tag。`macos-signing` reviewer 审批后，
现有 workflow：

1. 校验 tag、commit、version、main ancestry 和 manifest source；
2. 构建/审计 Python、QMD、renderer、companion；
3. 临时 keychain 导入 credential；
4. 生成 self-signed arm64 DMG/ZIP 和 release/update manifests；
5. 校验完整资产集合；
6. 不读取任何配置的 Environment/repository release secret 或长期签名凭据的 job，使用短期
   `GITHUB_TOKEN` 创建唯一 Draft；
7. 远端重新下载/核对后停止。

不要手工编辑、添加、覆盖、删除 Draft assets。失败时修复 `main`、提升版本、创建新 tag。

### 8.3 同一 Draft 的物理 M4 门禁

必须从 Draft 下载待公开的精确 bytes，并记录：

- machine model、macOS build、架构、测试用户；
- tag、source commit、workflow run、Release ID；
- `release-manifest.json` 小写 SHA-256；
- 每个资产摘要、credential generation、certificate/public key digest；
- clean-user Gatekeeper；
- 无 Docker/Homebrew/Python/Node/Git/QMD/ctags；
- packaged Python/QMD/MCP UDS、crash/restart/quit；
- 真实 Codex 采集、审核、发布和查询；
- embedding 首次下载、offline/ENOSPC/interrupt、rebuild/hybrid/switch；
- home/外置卷/private/move/delete/restart；
- MCP connect、Codex restart、两个工具、App 退出；
- data count、rollback 和全部故障注入。
- exact Draft digest 上重新运行的完整 `VAL-ELECTRON-CUTOVER-001`、
  `VAL-LEGACY-ABSENCE-001` 与最终 `VAL-RELEASE-CONTINUITY-001`；不得复用 W13 结果。

不要记录用户名、私有绝对路径、仓库内容、auth cache 或 credential。

### 8.4 阶段二：公开 promotion

只有同一 Draft 的完整 cutover/absence、continuity 与全部物理结论允许公开时：

```bash
gh workflow run desktop-release.yml \
  --repo fredgnr/local-context-forge \
  --ref main \
  -f release_tag="vX.Y.Z" \
  -f candidate_manifest_sha256="<64位小写SHA-256>" \
  -f confirm_publish=true
```

这是高风险、不可逆发布入口。开启 Immutable Releases 后，成功公开的 Release/资产不能编辑。

`macos-release` reviewer 第二次审批后，trusted `main` verifier：

1. 把 tag 当数据，隔离到 detached worktree；
2. fresh-peel tag 并验证属于 fresh `origin/main`；
3. 严格选出唯一 Draft 和固定 Release ID；
4. 下载并重验候选与人工 digest；
5. `PATCH` 前再次 fresh-fetch tag、Release 和 `origin/main`；
6. 用新的 comparison ref 计算 promotion order/`make_latest`；
7. 唯一 mutation 是固定 ID 的 `draft=false` PATCH；
8. 公开后运行 `gh release verify`，复核同一 ID、`immutable=true`、notes 和完整资产。

已 published 的 pre-state、tag/ID/asset drift 或 post-publish mismatch 都是发布安全事件。
停止公告和 update feed，保留证据；不要用重跑、覆盖 tag 或编辑 Release“洗绿”。

## 9. 更新门禁

仓库中的 `0.0.1 → 0.0.2` 是早期 ADR 的示例版本对。实际执行必须使用两个真实、单调且与
manifest/tag 完全一致的版本，统一记为 `N-1 → N`；当前版本是 `0.3.0-alpha.1`，不能伪造旧
tag 来满足门禁。

当前客户端只能：

- signed check；
- 下载并验证 DMG；
- 用户确认后打开 DMG；
- signed 路径不可用时显式打开固定 Releases 页面。

它不会自动安装、替换、重启或回滚。若要交付 automatic apply：

1. 新增或 supersede ADR-0011；
2. 设计 apply/restart/data migration/rollback；
3. 完成实现与安全复核；
4. 用真实 `N-1 → N` 测试成功路径；
5. 注入下载、校验、替换、重启和数据失败；
6. 验证 verified DMG fallback、数据保留和旧 App 恢复；
7. 保存独立 reviewer 的物理证据。

在此之前 UI/文档只能说“下载并打开已验证 DMG”，不能说“自动更新可用”。

## 10. 快速排障

### Legacy

```bash
lcf_managed doctor
lcf_managed status
lcf_managed logs
```

若必须进入 container：

1. 先从 `.lcf/runtime.env` 读取安装时记录；
2. 使用本章定义的 `lcf_managed` 调用已有子命令；
3. 不复制裸 Compose 示例到未知 checkout/context。

标准受管 checkout 数据布局的端口变化应重新运行
`lcf_managed install --web-port ... --api-port ... --mcp-port ...`，不要只改 `.env`。手工外置
active data 属于未托管部署；当前安装器会把路径重置回 checkout，不能用重跑安装器改端口。

### Electron source

- runtime 显示 configuration：检查 `LCF_RENDERER_DIR`、`LCF_SIDECAR_BIN` 是否为绝对路径；
- QMD unavailable：source mode 未配置受审计 QMD runtime 时属于预期 fail-closed；
- MCP onboarding unavailable：source/debug 不写持久 Codex 配置；
- updater unavailable：source 或 unprovisioned build 不联网是设计行为。

### Electron packaged

在 public Release 之前，任何“安装失败”都不能通过关闭 Gatekeeper、`sudo` 或清除 quarantine
绕过。记录 DMG SHA、manifest、macOS build、错误状态和脱敏日志，回到 Draft gate。

完整问题索引见[排错手册](11-troubleshooting.md)；仍缺的 desktop doctor/support bundle 已列入
[TODO](development/todo.md)。

## 11. 运维证据

每次 release、migration、backup/restore 或 physical gate 都应按
[证据记录规范](development/evidence/README.md)保存：

- 精确 commit/tag/Release ID/Actions URL；
- 环境、命令、expected/actual result；
- artifact digest；
- 数据前后计数和 rollback；
- 独立 reviewer；
- 脱敏确认；
- `pass`、`fail` 或带原因的 `not-run`。

不能用“当前工作树”、截图外观、mock 或 CI 绿灯替代真实环境证据。
