# ADR-0002：私有 UDS 与每次启动令牌协议

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-IPC-001、REQ-TRUST-001

## 上下文

Electron Main 需要与 Python sidecar 和 Node/QMD worker 双向通信。loopback TCP 仍会暴露
端口发现、跨进程请求和浏览器网络面；单靠“只在 localhost”不能证明调用者是本次 Main。
固定 token、命令行 secret 或持久 token 文件会跨启动复用或泄露到进程列表、日志和备份。

macOS Unix domain socket 有路径长度限制，也容易受到 stale socket、symlink、目录权限和
并发启动问题影响，因此路径、认证、协议和清理必须一起定义。

## 决策

### Transport 与路径

1. Python sidecar 和 QMD worker 各使用一个 Unix domain socket；不提供 TCP fallback。
2. Main 在 `NSTemporaryDirectory()` 下创建
   `dev.local-context-forge.desktop/<launch-id>/` 私有 runtime 目录，mode `0700`，并验证
   owner 是当前有效 UID、路径组件不是 symlink。
3. socket 使用短固定名（如 `py.sock`、`qmd.sock`），sidecar 以 `umask 077` 绑定并保持
   mode `0600`。启动前按 UTF-8 byte 长度检查完整路径；超限则在同一系统 temp root 下使用
   更短随机目录，绝不退回 TCP。
4. Main 只能在本次已验证的私有 runtime 目录中清理 socket。不得根据 child 输出或 renderer
   输入 unlink 任意路径。

### 启动 token

1. Main 为每个 child、每次启动生成独立 256-bit CSPRNG token 和随机 `launch-id`。
2. token 通过专用 inherited pipe/file descriptor 传给 child，不出现在 argv、环境变量、
   磁盘、renderer、诊断 UI 或日志中。socket 路径和协议版本可作为非 secret 启动参数。
3. token 不在 child 重启间复用。Main 关闭或控制 pipe EOF 时，child 进入停止流程。
4. child 对 token 做 constant-time 比较；认证失败只返回通用错误并立即关闭连接，不记录
   token 或其可重放摘要。

### 应用协议

1. 在 UDS 上使用有版本的 HTTP/1.1 JSON 契约。每个请求携带
   `Authorization: Bearer <startup-token>`、协议版本、`launch-id`、request ID 和截止时间。
2. 所有 endpoint（包括 health）都要求认证。ready 只有在授权 health 返回匹配的协议版本、
   child role、`launch-id` 和构建版本后成立。
3. endpoint、method、content type 和 schema 使用 allowlist；设置 header/body/response
   上限、解析超时、并发上限与结构化错误。未知字段按契约规则拒绝，不把异常栈返回 renderer。
4. Main 为 renderer 重新建模响应，绝不透传 token、socket 信息、child stderr 或任意 header。
5. 协议版本不兼容时 fail closed，并给出可诊断但不含 secret 的版本错误。

### 生命周期

1. Main 持有 child PID、control pipe、socket、token 和状态机的唯一权威记录。
2. 启动有截止时间；超时或异常 ready 时终止 child，等待退出，再清理本次 runtime 目录。
3. shutdown 先关闭本次 control pipe 写端，由 child 通过 EOF 验证父进程持有关系并进入
   graceful stop；若后续 child 契约增加显式 shutdown endpoint，可在 EOF 前发送授权请求。
   Main 随后等待有界 grace period，最后只强制终止本次 PID；不得按进程名广泛 kill。
4. 崩溃可按有界 backoff 重启；每次重启生成新目录和 token。正在进行的非幂等请求标记为
   结果不确定，不自动跨 child 重放。

## 后果

正面后果：

- 不打开 TCP 端口，renderer 和其他本机进程不能仅凭端口调用 sidecar；
- token 的泄露窗口局限于单次 child 生命周期；
- 独立 token/目录可区分 Python 与 QMD，并支持并发安装或测试；
- 版本、大小和超时成为可测试契约。

成本与限制：

- 同一 macOS 用户下的恶意高权限进程仍可能读取目标进程内存；这不是强沙箱或多用户认证；
- inherited FD、UDS HTTP client、路径上限和 crash cleanup 增加平台实现复杂度；
- 调试工具不能依赖匿名 health endpoint，必须由 Main 提供脱敏诊断。

## 替代方案

1. **随机 loopback TCP port。** 拒绝：增加网络面且认证问题仍存在。
2. **stdio 作为全部 RPC transport。** 不采用：流式、多并发和独立健康检查复杂；保留 control
   pipe 只传 token/生命周期。
3. **固定 token 文件。** 拒绝：持久、可备份、容易权限漂移。
4. **token 放 argv 或环境变量。** 拒绝：会进入进程检查、崩溃报告或 child 继承环境。
5. **只有目录权限，不做应用认证。** 拒绝：无法绑定“本次 Main”和 child。
6. **复用一个 token/socket 给两个 child。** 拒绝：扩大泄露和混淆半径。

## 修订记录

| 日期 | 修订 | 原因 |
| --- | --- | --- |
| 2026-07-30 | 明确 P1 graceful shutdown 使用已认证父进程持有的 control pipe EOF；HTTP shutdown endpoint 不是必需条件 | 与 fd3 token/liveness 的同一所有权协议及已实现状态机保持一致，避免把尚不存在的 endpoint 误写成实现要求 |

## 验证门禁

- VAL-IPC-001 必须覆盖：合法请求、错误/缺失 token、错误 role/launch/version、权限与
  owner、symlink/stale socket、超长路径、超大 payload、超时、并发、child crash、
  有界 restart 和 shutdown。
- 进程列表、环境快照、普通/错误日志、诊断导出和迁移/备份扫描不得出现 token。
- renderer 测试必须证明 preload API 不返回 socket、token、raw headers 或 child stderr。
- packet/process 检查必须证明没有 sidecar TCP listener。

以上门禁当前尚未运行。
