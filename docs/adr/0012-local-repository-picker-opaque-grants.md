# ADR-0012：桌面本地仓库选择与一次性不透明授权

- 状态：Accepted
- 日期：2026-07-31
- 关联需求：REQ-LOCAL-SOURCE-001、REQ-TRUST-001、REQ-GIT-001、REQ-IPC-001
- 依赖：ADR-0001、ADR-0002、ADR-0006

## 上下文

桌面端原有 IPC 只接受无凭据的公开 GitHub HTTPS URL。这能阻止 renderer 把任意本地路径
送入 sidecar，却也使已经克隆到 Mac 的私有仓库无法使用。把绝对路径直接放进输入框或
renderer API 会扩大被注入页面读取、记录或重放本地路径的风险；让应用接管 GitHub token、
SSH key 或 Keychain 凭据则会引入另一套高风险凭据生命周期。

本地仓库还需要在应用重启后继续支持采集和重建。只给当前 sidecar 一次性的临时根目录会
导致数据库中已登记的仓库在下次启动后不可用。

## 决策

1. 私有远程仓库由用户使用现有 Git/SSH 工具预先克隆。Local Context Forge 不接收、
   保存或代理 GitHub token、SSH key、cookie 或 Keychain 凭据。
2. renderer 通过类型化 preload 能力请求 Main 打开原生目录选择器。选择器结果只返回
   `{grantId, displayName}`；不返回绝对路径、父目录、设备号或 inode。
3. `grantId` 是 256-bit 随机值，固定前缀和语法，保存在 Main 内存中，按单调时钟计算
   五分钟过期且只能消费一次。新选择会撤销尚未消费的旧授权；应用退出后选择器永久关闭并
   清空授权。创建仓库请求可携带该不透明值，但未知、过期、重放或身份变化的授权一律拒绝。
4. Main 发放和消费授权时都验证：绝对规范路径、非符号链接、当前 uid 所有的目录、相同
   device/inode、与父目录相同的 device（不能是嵌套挂载点根）、不是文件系统根、不是
   home/volume 根，并且不与应用数据或缓存目录互相包含。device/inode 必须是 JavaScript
   可精确表示的安全整数。当前支持用户 home 的严格子目录以及 `/Volumes/<volume>/...`。
   `~/.codex`、有效 `CODEX_HOME`、`~/.ssh`、`~/.kube`、`~/.aws` 等凭据/配置根及其
   realpath 被明确排除。
5. Main 只在消费授权后把路径改写到内部 sidecar 请求。renderer 日志、状态、library
   列表和错误不得返回本地绝对路径；既有 `ApiProxy` 继续只公开经过审核的远程 URL。
6. Main 以固定 argv 重复参数把 home 和 `/Volumes` 传给 desktop sidecar。sidecar 不从
   renderer 或 `LCF_LOCAL_SOURCE_ROOTS` 环境继承桌面授权根；它只接受绝对、规范、非根、
   去重的 Main 参数。Docker/browser 的环境配置行为保持不变。
7. sidecar 可在本地数据库保存已授权仓库的规范路径，以便应用重启后的采集和重建。每次
   使用仍由 Backend 权威检查规范目录、允许根、敏感配置目录和当前 desktop uid；Docker/
   browser 保持旧的显式 imports 策略，不强加 desktop owner 规则。该数据只位于当前用户的
   mode-0700 Application Support 数据目录；外部 API/MCP 不返回该路径。
8. 路径授权只代表读取所选工作树，不代表信任仓库内容。快照大小、文件类型、符号链接、
   Git 对象和 Wiki 输出仍受 ADR-0006 的受控 source boundary 约束。

## 后果

- 用户可以通过“选择本地仓库”导入私有仓库，无需在应用中配置凭据；
- renderer 即使遭到注入也无法枚举或自行指定文件系统路径，猜中有效授权的概率可忽略；
- 用户移动、删除或更换目录 inode 后，未消费授权会失效；已登记仓库的后续任务则由
  sidecar 再次执行本地 source 校验并在缺失时明确失败；
- 把凭据/配置目录本身选作仓库会在 Main 和 Backend 两层被拒绝，避免相对过滤把 Codex
  session、SSH/Kubernetes 配置等送入 facts/evidence；
- sidecar 进程仍运行在同一 macOS 用户权限下，本决策不是 OS App Sandbox。抵御同一 uid
  恶意进程的完整 TOCTOU 需要 security-scoped bookmark、fd-based snapshot 或独立沙箱，
  留给后续物理门禁评估。

## 替代方案

1. **继续只支持公开 HTTPS。** 拒绝：无法覆盖本地私有仓库这一核心桌面用例。
2. **把绝对路径直接暴露给 renderer。** 拒绝：扩大路径泄露和任意路径注入边界。
3. **在应用里登录 GitHub/读取 SSH 凭据。** 拒绝：不必要地承担高风险凭据管理。
4. **把整个 home 作为 renderer 可提交的路径根。** 拒绝：一旦 renderer 被控制即可读取
   任意用户目录。
5. **把授权目录复制进 Application Support 后再处理。** 暂不采用：隔离更强，但大型
   monorepo 会产生双倍空间和明显等待；可作为后续可选“隔离导入”模式。

## 验证门禁

- VAL-LOCAL-SOURCE-001：Main 单元测试覆盖取消、单调 TTL、单次消费、猜测/重放、退出
  竞态、符号链接、owner、home/volume/嵌套挂载根、敏感配置根、数据/缓存目录重叠、
  inode 变化、安全整数和 renderer 无路径泄露。
- VAL-LOCAL-SOURCE-002：desktop sidecar 测试覆盖 argv-only 根目录、环境变量不生效、
  重启 owner/敏感目录重验、缺失目录、ApiProxy 脱敏和敏感根在 catalog/evidence 前拒绝。
- VAL-LOCAL-SOURCE-003：物理 macOS arm64 应用覆盖 home 仓库、外置卷仓库、私有仓库、
  移动/删除目录和应用重启；未执行前保持 `not-run`。
