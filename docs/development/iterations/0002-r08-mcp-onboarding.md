# ITER-0002/R08：Desktop MCP onboarding

- 状态：`in-progress`
- 日期：2026-07-31
- 父迭代：[ITER-0002](0002-bundled-runtimes.md)
- 决策：[ADR-0013](../../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md)
- 需求：REQ-MCP-ONBOARD-001、REQ-MCP-001、REQ-CLI-001、REQ-TRUST-001
- 验证：VAL-MCP-ONBOARD-001、VAL-MCP-001

## 范围

为已打包且位于 Applications 的 Local Context Forge 增加 Main-owned Codex 一键接入。
设置页只显示脱敏状态和操作，不显示或接收路径/argv。Codex 自动接入覆盖经验证的官方
npm、`install.sh` standalone、Homebrew cask 与固定 GitHub release 布局；Cursor 保持
明确的手动后备。

本记录同时收口 R04 的 bridge 发现：真实 UDS 移入每次启动的系统 per-user temp 私有
目录；Application Support 保留最小、私有、非 secret rendezvous，以及按规范化
`CODEX_HOME` scope 隔离的私有 ownership ledger。ledger 不进 renderer/bridge，但包含
应用生成的 marker 与 bundled command/arg 路径。

本轮不移动 `.app`、不自动配置 Cursor、不编辑任意 provider 配置文件、不持久化 MCP
capability，也不把 source/Linux fake 当作 packaged macOS 或真实签名证据。

## 任务

- [x] 增加无参数 typed IPC/preload facade 与 Settings 状态、连接、重新连接、清除 UI。
- [x] 固定 `codex mcp list --json`、`add`、`remove` argv；无 shell、bounded process、
  strict JSON、操作内串行化与 mutation 前后复核；replacement 不是跨 CLI 的 CAS 事务。
- [x] 按规范化 `CODEX_HOME` 的 domain-separated SHA-256 scope 写
  `mcp-target-ownership-<hash>.json`；以 256-bit marker + scope ledger + exact command/arg
  共同证明 ownership，move staging 最多 old/new 两个 target。
- [x] missing/damaged/legacy/mismatch/extra-env/lookalike ownership 均 fail closed；source、
  非 `/Applications` 或 invalid bundle 不 mutation。
- [x] 验证 `.app/Contents/Resources`、所有中间目录、bundle 内 Node/companion 的 canonical
  non-symlink、root/effective-UID owner、group/world-write 与 setuid/setgid/sticky 策略；
  ledger/数据目录 exact mode 包含 special bits。
- [x] 支持官方 npm、standalone、Homebrew cask 和 `/usr/local/bin/codex` signed release；
  固定 arm64 Mach-O、OpenAI TeamIdentifier/Authority、owner/mode/layout 并在 spawn 前
  重校验。
- [x] 将 `mcp.sock` 与 launch marker 放入 per-launch `0700` temp directory；发布
  `0600` rendezvous，companion 逐层验证、在 bridge 前删除 ownership marker，并在 shutdown
  清理 runtime。
- [x] 明确 Cursor 只手动配置，不猜测或静默调用未验证 CLI。
- [ ] 在 clean macOS arm64 packaged app 上，用真实官方签名 Codex 安装完成一键接入、
  Codex 重启、两工具调用、app move/reconnect 和清除。

## 验收

- renderer 不能选择 executable、server name、argv、env 或配置文件，也不能读取 CLI
  输出、bundle path、socket、launch ID 或 capability；
- 无外部并发 writer 时，仅 marker + 当前 scope ledger + exact command/arg 全匹配的旧 target
  可 reconnect/clear；其他同名状态在该次操作中 fail closed；
- `status/configure/clear` 串行化，shutdown 会 abort 在途命令，所有错误只返回稳定枚举；
- signed 安装只有固定布局与 OpenAI 签名可进入执行，任意 PATH spoof、错误架构/owner/
  mode/symlink/realpath、签名或 identity drift 均 fail closed；
- stable Application Support rendezvous 不含 socket 名、launch ID、token 或 capability；
  per-scope ledger 只含 marker 与 bundled target 路径，数据目录 exact `0700`、ledger exact
  `0600`；runtime 必须是系统 temp root 的直接私有子目录并在退出时删除；
- Codex CLI 没有 CAS/shared lock；二次 recheck 只缩小最终 list 与 add/remove 间的竞态。
  hostile same-UID 可读写 Codex config/ledger 并利用 bundle/state check-use，本轮不宣称 OS
  sandbox 或对抗同 UID。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| MCP ownership/onboarding core | `pass` | 2026-07-31；`fcca1e4` | `cd desktop && ./node_modules/.bin/vitest run tests/mcpTargetOwnership.test.ts tests/mcpOnboarding.test.ts tests/mcpCompanion.test.ts` | 3 files / 37 pass；scope/ledger/marker、move staging、bundle chain、fail-closed matrix 与 marker 删除 |
| VAL-MCP-ONBOARD-001 Desktop source | `pass` | 2026-07-31；`fcca1e4` | `cd desktop && ./node_modules/.bin/vitest run tests/provider-discovery.test.ts tests/provider-policy.test.ts tests/mcpTargetOwnership.test.ts tests/mcpOnboarding.test.ts tests/ipc.test.ts tests/preload.test.ts` | 6 files / 73 pass；固定 argv、四类官方布局、ownership、串行/退出、preload/IPC 脱敏 |
| VAL-MCP-ONBOARD-001 Web source | `pass` | 2026-07-31；`fcca1e4` | `cd web && ./node_modules/.bin/vitest run src/McpOnboarding.test.tsx src/App.test.tsx src/desktopBridge.test.ts` | 3 files / 25 pass；设置状态、操作与 browser fail-closed |
| VAL-MCP-001 source bridge | `pass` | 2026-07-31；`fcca1e4` | `cd desktop && ./node_modules/.bin/vitest run tests/mcpBridge.test.ts tests/mcpCompanion.test.ts tests/mcpCompanionPackaging.test.ts tests/mcpSidecarRead.test.ts` | 4 files / 15 pass / 7 skip；7 个 skip 需要当前 sandbox 不允许的真实 AF_UNIX/native 条件，未折算为 pass |
| Desktop 全量回归 | `pass` | 2026-07-31；`fcca1e4` | `cd desktop && npm test -- --run` | 30 files / 235 pass / 7 skip |
| Web 全量回归 | `pass` | 2026-07-31；`fcca1e4` | `cd web && npm test -- --run` | 7 files / 51 pass |
| packaged clean-user / 真实 OpenAI 签名 | `not-run` | — | 需物理 macOS arm64、`/Applications` packaged app 与官方签名 Codex | source 注入不证明真实 codesign、Mach-O、app move/reconnect 或跨进程工具调用 |

## 风险与回滚点

| 风险 | 缓解/回滚点 |
| --- | --- |
| Codex 后续更改官方安装布局或 `mcp` JSON schema | exact allowlist/strict schema fail closed；用户退回手动配置 |
| 同名 MCP target 无完整 ownership proof | 在无外部竞态的该次检查中返回 conflict；不把它写成 CAS 保证 |
| app 移动导致旧 companion argv 失效 | status 标记 stale；用户把 app 放回 `/Applications` 后显式 reconnect |
| Codex writer 在最终 list 后并发 mutation | mutation 前二次 recheck 缩小窗口；Codex CLI 无 CAS/shared lock，用户核对 conflict/结果 |
| 同 uid 恶意进程观察或修改本地状态 | 0700 runtime/data、0600 rendezvous/ledger、逐层身份验证和每连接 UI 授权；同 UID 可读写 config/ledger，不宣称 OS 沙箱 |
| shutdown 中 CLI 或 bridge 操作未结束 | abort/超时并清理 runtime；不隐式重放配置操作 |

## 当前变更清单

- `docs/adr/0013-codex-mcp-onboarding-signed-cli-discovery.md`
- `docs/development/{mcp-companion-protocol,traceability}.md`
- `docs/development/iterations/0002-r08-mcp-onboarding.md`
- `README.md`、`SECURITY.md`、`desktop/README.md`
- `docs/{03-hardware-deployment,04-quickstart,06-api-and-mcp,10-security,14-all-in-one-macos,16-electron-desktop-guide}.md`
- `desktop/src/main/mcpOnboarding.ts`
- `desktop/src/main/mcpTargetOwnership.ts`
- `desktop/src/main/providers/{contracts,discovery,environment,execution,preflight,providerResolver}.ts`
- `desktop/src/{contracts,mcpProtocol}.ts`
- `desktop/src/main/{index,ipc,mcpBridge,mcpSidecarRead}.ts`
- `desktop/src/preload/index.ts`
- `desktop/companion/src/{bridgeClient,index}.ts`
- `desktop/tests/{mcpTargetOwnership,mcpOnboarding,mcpBridge,mcpCompanion,mcpCompanionPackaging,mcpSidecarRead,provider-discovery,provider-policy,ipc,preload}.test.ts`
- `web/src/{McpOnboarding,McpOnboarding.test,App,App.test}.tsx`
- `web/src/{desktopBridge,desktopBridge.test}.ts`
- `web/src/styles.css`

本记录的 `[x]` 只表示 source 纵切已实现；父迭代和 packaged/physical 门禁仍为
`in-progress` / `not-run`。
