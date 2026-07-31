# ADR-0004：macOS 运行时路径与旧 Docker 数据迁移

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-DATA-001、REQ-MODEL-001、REQ-LEGACY-001

> **后续关系：** 本 ADR 仍为 Accepted，但 legacy import/migration/lifecycle 与相应兼容门禁已由
> [ADR-0015](0015-electron-only-legacy-retirement.md#对既有-adr-的影响)部分取代；只保留该链接
> 所列的 non-legacy 路径、数据安全、模型和当前 desktop backup 条款。

## 上下文

现有安装可在仓库目录或 Docker bind mount/volume 中保存 SQLite、Wiki、源码 snapshot、
facts、proposal、QMD 索引、imports 和 backup。Electron `.app` bundle 是只读、可替换的发行物，
不能承载用户数据。缓存、日志、临时 socket、模型权重和不可替代数据也需要不同的清理与备份
语义。

桌面版不能依赖 Docker 或 Git 来完成迁移。迁移必须面对中断、磁盘不足、不可信 `.git`/
配置、旧 writer 仍运行、schema 漂移和重复执行；直接在原目录升级会破坏回滚。

## 决策

### 标准路径

bundle identifier 固定为 `dev.local-context-forge.desktop`。Main 在启动早期设置并验证路径，
sidecar 只能使用 Main 下发的已解析路径，renderer 不能提供根目录。

| 数据类别 | 路径 | 语义 |
| --- | --- | --- |
| 持久状态 | `~/Library/Application Support/Local Context Forge/` | 用户拥有、备份、升级保留 |
| 数据库/内容 | 上述目录的 `state/`, `libraries/`, `wiki/`, `indexes/` | 不可替代或重建成本高；版本化 |
| 导入/备份/迁移 journal | 上述目录的 `imports/`, `backups/`, `migration/` | 私有；迁移 staging 与回滚记录 |
| 可重建缓存/模型文件 | `~/Library/Caches/Local Context Forge/` | 可清除；缺失时按需重建/下载 |
| 日志 | `~/Library/Logs/Local Context Forge/` | 脱敏、轮转、有限保留 |
| UDS/runtime | 系统 per-user temp 下的每次启动目录 | 临时、0700；见 ADR-0002 |
| 凭据 | macOS Keychain 或既有 CLI 自有存储 | 不进入应用数据、日志或迁移 |

应用 bundle、安装 DMG、release keys 和 CLI auth 永不进入上述用户数据备份。

### 模型权重

1. DMG 不预装模型权重。只有用户启用需要本地模型/embedding 的能力后才显示来源、大小、
   许可和磁盘需求并开始下载。
2. 下载写入 cache 中的 `.partial`，支持有界 resume；验证固定 manifest 中的发布者签名/
   digest、期望大小和模型 ID 后，才以同卷原子 rename 激活。
3. 持久状态只记录模型 ID、digest、兼容 profile 和激活状态，不信任文件名。缓存被系统清除时
   功能进入“需要下载/离线不可用”，不得损坏 library 数据。
4. 模型或向量 profile 改变时标记相关 index stale；新 index 在 staging 完成后原子切换。

### 支持的 legacy 输入

1. 首选输入是由现有 legacy backup 流程生成、带校验 sidecar 的 archive。
2. 也可由用户明确选择一个已经停止 writer 的 legacy bind-mount 数据根。应用不递归扫描 home，
   不自动寻找或启动 Docker。
3. Docker named volume 必须先用 legacy 工具导出为受支持 archive/目录；桌面应用本身不调用
   Docker。该导出步骤属于旧环境，不构成桌面版运行依赖。
4. 不能证明一致、仍有 owner lock/活动 writer、来源路径是 symlink、版本未知或容量不足时，
   preflight fail closed。

### 迁移事务

1. 对输入做只读 inventory：格式版本、文件类型/大小、owner、可用空间、checksum、SQLite
   integrity、library/content 计数和不可信 Git metadata。不得执行 legacy hook、Git config、
   credential helper 或仓库代码。
2. 为本次迁移创建唯一 journal 和 `migration/staging/<id>`；只复制或安全解包，不修改 source。
3. 在 staging 上逐版本运行 schema/data converter。每一步记录输入/输出版本、计数、digest、
   错误和恢复点；未知字段/版本不得猜测。
4. 完成 domain invariants、引用抽样、SQLite integrity 与 index/profile 判定。派生 index 可标为
   `stale` 后重建，不能伪装为已验证。
5. 停止桌面 sidecars，在同一 volume 内把旧 target 移到 quarantine，再将 staging 原子 rename
   为 active；启动后 smoke 失败则反向 rename 回滚。
6. source、quarantine 和 journal 默认保留，直到用户完成验证并明确清理。重复迁移由 source
   fingerprint + migration ID 识别，不重复导入。
7. 任一时刻只允许 legacy 或 desktop writer 使用一份 active 数据。迁移 UI 必须说明如何停止
   旧服务，不能自行删除旧容器/volume。

### Legacy 生命周期

Docker、Compose、旧安装器和对应文档在 P0–P6 期间保留为 `legacy`。只有
VAL-DATA-001、VAL-UPDATE-001 和 VAL-LEGACY-001 通过、真实样本可回滚、阻断缺陷关闭且新增
弃用 ADR/用户公告后，才可在 P7 决定删除。迁移成功本身不自动授权删除。

## 后果

正面后果：

- `.app` 可替换而不覆盖用户数据，缓存/日志/凭据有明确边界；
- 模型不膨胀 DMG，损坏下载不会进入 active；
- 迁移不修改原数据，中断和 schema 错误有明确回滚点；
- 桌面运行与迁移均不要求 Docker/Git。

成本与限制：

- 首次模型使用需要网络、等待时间和额外磁盘；
- staging + quarantine 可能需要接近两到三份数据空间；
- named volume 用户需要在旧环境先导出；
- 原数据默认保留会占用磁盘，需要后续显式清理体验；
- 当前决策不承诺跨用户、多机或网络卷上的原子迁移。

## 替代方案

1. **把数据写入 `.app` 或安装目录。** 拒绝：更新会覆盖且通常不可写。
2. **继续使用仓库相对 `./data`。** 拒绝：DMG/App 启动目录不稳定且不符合 macOS 约定。
3. **自动扫描并就地升级旧目录。** 拒绝：不可审计、不可回滚、可能碰到错误目录。
4. **桌面应用自动控制 Docker/volume。** 拒绝：违反无 Docker 依赖并扩大权限。
5. **在 DMG 预装全部模型。** 拒绝：产物过大、许可/版本和需求不匹配。
6. **迁移后立即删除旧数据/Docker。** 拒绝：在真实迁移/更新门禁完成前失去恢复路径。

## 验证门禁

- VAL-DATA-001：fresh、archive、bind-mount、repeat、interrupt、corrupt、unknown-version、
  symlink、active-writer、low-disk、rollback 和 post-start smoke 矩阵。
- VAL-MODEL-001：用户触发、来源展示、离线、resume、digest/signature mismatch、磁盘不足、
  atomic activation、cache eviction 和 stale index。
- VAL-LEGACY-001：代表性旧版本/数据规模迁移，核对计数、引用、Wiki、索引状态、原数据读取和
  rollback；记录不能迁移的版本。
- 卸载/更新测试必须证明默认保留 Application Support 数据，不宣称 secure erase。

以上门禁当前尚未运行，Docker 仍为 legacy 且不得弃用。
