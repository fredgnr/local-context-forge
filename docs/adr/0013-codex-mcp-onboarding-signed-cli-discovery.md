# ADR-0013：Codex MCP onboarding 与签名 CLI discovery

- 状态：Accepted
- 日期：2026-07-31
- 关联需求：REQ-MCP-ONBOARD-001、REQ-MCP-001、REQ-CLI-001、REQ-TRUST-001
- 依赖：ADR-0001、ADR-0002、ADR-0005、ADR-0008、ADR-0009

## 上下文

内置 stdio MCP companion 已能把 Codex 的两个 Context7 兼容工具连接到正在运行的应用，
但要求用户手写可执行路径、bundle 路径和环境变量既易错，也会把敏感 runtime 细节暴露给
renderer。直接在 `PATH` 中寻找 `codex`、把任意 CLI 交给 shell、覆写同名 MCP server，
或猜测 Cursor 配置格式都会把一键接入变成命令执行和配置篡改边界。

原 R04 bridge 还把真实 socket 放在稳定 Application Support 目录。即使 token 不持久化，
稳定 socket 名和 launch 标识也会扩大同 uid 进程观察和重放窗口。onboarding 必须同时收口
CLI discovery、配置 ownership 和每次启动 runtime rendezvous。

## 决策

1. renderer 只能调用无参数 typed IPC 并接收稳定枚举；executable、argv、资源路径、
   socket、launch ID、capability、CLI JSON/stdout/stderr 和配置文件内容都留在 Main。
2. Main 只执行固定的 `codex mcp list --json`、`codex mcp add` 和 `codex mcp remove`
   argv，不使用 shell。进程有固定 cwd/env allowlist、超时和输出上限；list 输出使用 strict
   JSON schema，错误只映射为稳定状态。
3. ownership 按有效 Codex 配置根隔离：显式规范化 absolute `CODEX_HOME`，否则为
   `$HOME/.codex`。Main 对该路径使用带 `lcf-codex-config-scope-v1\0` domain separation 的
   SHA-256，并在 exact mode-0700 Application Support 数据根保存 mode-0600
   `mcp-target-ownership-<64hex>.json`。目录和 ledger 必须 canonical non-symlink、由当前
   effective UID 拥有；ledger 还必须 regular、single-link，exact mode 检查包含 special bits。
4. ledger exact schema 保存应用生成的 256-bit
   `lcf-mcp-v1-<64hex>` marker 和 bundled command/唯一 arg。正常状态只有一个 target；
   app move/reconnect staging 最多同时保存 old/new 两个 exact target。Codex target 的
   environment 必须仅含 `LCF_MCP_OWNER_ID=<同一 marker>`；只有 marker、当前 scope ledger
   和 exact command/arg 全匹配才算 owned。missing/damaged/legacy/unscoped ledger、
   mismatch、extra-env 和 path lookalike 都 fail closed。
5. `status`、`configure` 和 `clear` 在应用内串行化，shutdown abort 在途命令；Main 在
   `add/remove` 前再次读取 Codex config、复核 ledger 和 CLI/bundle identity，并在命令后读取
   结果。Codex CLI 没有 CAS 或与应用共享的配置锁，因此最终 list 与 mutation 之间仍有小竞态；
   本决策不能无条件保证并发第三方 writer 的 target 不受影响。
6. 自动接入只在 packaged app 位于 `/Applications` 时开放。`.app`、`Contents`、
   `Resources`、通往 Node/companion 的每个中间目录以及两个文件都必须 canonical
   non-symlink，由 root 或当前 effective UID 拥有，并拒绝 group/world write 与
   setuid/setgid/sticky。source/debug、其他位置或 invalid bundle 不执行配置 mutation。
7. CLI discovery 只接受经验证的官方 npm、`install.sh` standalone、Homebrew cask 和固定
   GitHub release 布局。npm shim 必须解析到受控、不可写的 package 布局；后三种 native
   CLI 必须是 macOS arm64 Mach-O，路径/owner/mode/layout 符合策略，且 `codesign`
   TeamIdentifier 与 Authority 匹配 OpenAI。每次 spawn 前重新验证 canonical identity；
   PATH spoof、symlink、writable binary、架构/签名/identity drift 一律拒绝。
8. Main 在系统 per-user temp root 下为每次启动创建直接的 mode-0700 runtime 子目录；
   launch marker 和 `mcp.sock` 为 mode-0600。稳定 Application Support 同时保存 mode-0600、
   不含 secret 的最小 rendezvous，以及上述 per-scope ownership ledger；ledger 不进入
   renderer 或 bridge，但内容包含 marker 与 bundled command/arg 路径。
9. companion 启动后先删除 `LCF_MCP_OWNER_ID`，再从 rendezvous 开始逐层验证 owner、类型、
   mode、无 symlink、canonical
   realpath、系统 temp 的直接私有子目录以及 launch marker/socket 身份，随后按 ADR-0008
   进行每连接授权。shutdown 删除 rendezvous、socket 和 runtime directory；stale 或 tamper
   状态 fail closed。ownership marker 只是配置归属元数据，不是 secret、认证 token 或 MCP
   capability。
10. Cursor 继续使用文档化手动配置。应用不猜测其 CLI、配置位置或 schema，也不静默调用
    未验证的 provider；用户手工创建的 Cursor 条目不由应用管理，不应复制 Codex marker。
11. source/Linux 测试可注入签名与 Mach-O contract 结果，但这种注入只证明策略分支，
   不证明真实 OpenAI 签名、packaged bundle 或物理 macOS 接入。

## 后果

- 用户可在设置页检查、连接、重新连接或清除 Codex MCP，无需看到路径或 argv；
- 在无外部并发 writer 且 ownership proof 完整时，未知/不匹配同名配置会 fail closed；
- PATH 中的恶意 shim、可写 CLI 和错误架构/签名不能进入 Main 的执行边界；
- Application Support 不再持久保存真实 socket 名、launch ID、token 或 capability；
- Application Support 会保存按 Codex 配置根隔离的 marker/target ledger；它不是 credential，
  但同一 UID 可读写；
- 应用移动后自动接入会明确失效，用户把应用放回 `/Applications` 后可显式 reconnect；
- Cursor 缺少自动 onboarding 是有意的安全范围，不是隐式兼容承诺；
- hostile same-UID 进程可修改 Codex config/ledger，bundle/state 检查也有 check-use 窗口；
  这是单用户、同 UID 非对抗边界，不是 OS sandbox。

## 替代方案

1. **允许用户选择 Codex executable。** 拒绝：renderer 输入会直接影响 Main 进程执行。
2. **只运行 `which codex` 或信任 `PATH`。** 拒绝：不能证明安装布局、owner、架构和签名。
3. **无条件覆盖固定 MCP server name。** 拒绝：会破坏用户或第三方已有配置。
4. **把 socket/token 写进稳定配置。** 拒绝：扩大跨启动观察、重放和残留窗口。
5. **同时自动编辑 Cursor 配置。** 拒绝：当前没有可固定、签名验证的 CLI/schema 契约。

## 验证门禁

- VAL-MCP-ONBOARD-001：Main/preload/Web focused source tests 覆盖无参数 IPC、固定 argv、
  strict JSON、per-`CODEX_HOME` scope、marker/ledger/exact target ownership、move staging、
  missing/damaged/legacy/mismatch/extra-env/lookalike 拒绝、串行/取消、bundle chain、
  四类官方布局、PATH/symlink/owner/mode/special-bits/arch/signature/identity drift 拒绝、
  脱敏和 Cursor 手动后备。
- VAL-MCP-001：bridge/companion source tests 覆盖 per-launch temp、rendezvous 权限、
  marker 在 bridge 前删除、SDK contract replay、授权、stale/tamper/oversize 和 shutdown 清理。
- packaged clean-user gate：物理 macOS arm64 的 `/Applications` 应用必须用真实官方签名
  Codex 完成连接、Codex 重启、两个工具调用、app move/reconnect 和清除；当前保持
  `not-run`，source/Linux fake 不得替代。
