# MCP companion 与 Main bridge 协议

本页记录桌面包内 stdio MCP companion 和正在运行的 Electron Main 之间的私有只读协议。
权威决策见 [ADR-0008](../adr/0008-mcp-companion-main-bridge.md) 和
[ADR-0013](../adr/0013-codex-mcp-onboarding-signed-cli-discovery.md)；当前 source 证据见
[ITER-0002/R08](iterations/0002-r08-mcp-onboarding.md)。

## 对外工具合同

companion 通过 stdio MCP 只公开两个 Context7 兼容工具：

| 工具 | 输入 | 结果 |
| --- | --- | --- |
| `resolve-library-id` | NFC `libraryName`（≤512 bytes）、NFC `query`（≤8 KiB） | 最多 20 个候选的只读文本 |
| `query-docs` | `/local/<safe-id>`（≤256 bytes）、NFC `query`（≤8 KiB） | 最多 8 个结果的只读文本 |

两种 bridge 请求都携带当前 `corpusRevision`。revision stale、应用未运行、未获批准、授权
过期、响应过大或 Backend 不可用时 fail closed；companion 不自行读取数据库、Wiki、
用户目录或网络。

## 发现与 runtime 文件

协议版本固定为 `1.0`。每次应用启动：

1. Main 在系统 per-user temp root 下创建一个直接的 `lcf-mcp-*` mode-0700 私有目录；
2. 该目录包含 mode-0600 的 `launch.json`，真实 socket 固定名为 `mcp.sock` 且 mode-0600；
3. Application Support 数据目录写 mode-0600 `mcp-rendezvous.json`，内容是 runtime
   directory；它不包含 socket 名、launch ID、token 或 capability；同一数据目录还保存
   per-Codex-scope ownership ledger，见下一节；
4. companion 只用 absolute normalized、非 root 的 home 构造固定路径；随后验证
   data/temp/runtime/marker/socket 的 owner、类型、mode、无 symlink、realpath，并要求
   runtime 是 temp root 的直接子目录；
5. shutdown 删除 rendezvous、socket、launch marker 与 runtime directory。

UDS 全路径不得超过 100 bytes，rendezvous JSON 不得超过 4 KiB。stale、额外字段、
错误 owner/mode/type、嵌套 runtime、symlink 或 identity drift 均映射为 `unavailable`。

## 连接与授权

companion 首先向 `/authorize` 发送 exact client descriptor 和当前 launch identity。Main
最多保留一个待批授权，并要求用户在应用内显式批准。批准后 Main 返回绑定到该连接的
256-bit base64url capability、UUID session、corpus revision、到期时间和协议版本。

- 授权 deadline：30 秒；
- session lifetime：8 小时或应用退出/显式撤销，以先发生者为准；
- 最多 4 个 active sessions；
- 每个 session 每分钟最多 30 个请求，且同一 session 只允许一个 active request；
- resolve deadline：30 秒；query deadline：120 秒；
- request body 上限：16 KiB；response body 上限：4 MiB。

capability 只在 Main 内存和已授权连接中存在，不写 rendezvous、日志、配置或 renderer。
换 socket、换 launch、重连、过期、撤销或应用重启后必须重新授权。

## Codex target ownership 文件

ownership 与 bridge authorization 是两个独立协议。Main 取显式规范化 absolute
`CODEX_HOME`，未设置时取规范化 `$HOME/.codex`，按以下逻辑形成 scope：

```text
sha256("lcf-codex-config-scope-v1\0" || normalized_codex_home)
```

Application Support 数据目录本身必须 canonical non-symlink、由当前 effective UID 拥有且
exact mode `0700`。每个 scope 的文件名是：

```text
mcp-target-ownership-<64 lowercase hex scope>.json
```

ledger 必须是同一 UID 的 canonical non-symlink regular/single-link 文件，exact mode `0600`；
目录和文件的 exact mode 检查包含 setuid/setgid/sticky bits。exact JSON schema v1 只含：

- `marker`：应用以 256-bit 随机数生成的 `lcf-mcp-v1-<64 lowercase hex>`；
- `targets`：一个 exact bundled Node command + 唯一 companion argument；App move/reconnect
  staging 最多暂存 old/new 两个不同 target，完成后收敛到一个；
- `schemaVersion`：`1`。

Codex `mcp list --json` 中对应 stdio target 的 `env` 必须只含
`LCF_MCP_OWNER_ID=<marker>`。只有 marker、当前 scope ledger、command 和唯一 arg 全部
exact match 时，Main 才把 target 视为 owned。missing/damaged ledger、旧版 unscoped ledger、
marker mismatch、extra env、command/arg mismatch、path lookalike 或额外 target 都 fail closed。

marker 不保密，也不授予 bridge 权限。它不返回 renderer、不写 rendezvous、不进入任何 bridge
request/response；companion 在调用 endpoint discovery 前删除进程环境中的
`LCF_MCP_OWNER_ID`。Cursor 手工配置不由应用管理，不应复制该 marker。

自动 mutation 还要求 packaged App 位于 `/Applications`。从 `.app`、`Contents`、
`Resources` 到 `qmd/node/bin/node`/`companion/index.mjs` 的每个目录和文件都必须 canonical
non-symlink，由 root 或当前 effective UID 拥有，并拒绝 group/world write 与任意
setuid/setgid/sticky。source/debug、非 `/Applications` 或 invalid bundle 不 mutation。

Main 串行化自身 onboarding 操作，在 `codex mcp add/remove` 前重新检查 CLI、bundle、
ledger 和最终 list，命令后再 list。Codex CLI 不提供 CAS 或共享锁，所以最终 list 与 mutation
之间仍有小竞态；另一个 writer 可在窗口内改变 target。hostile same-UID 也能读写 Codex
config/ledger，bundle/state 检查本身也有 check-use 窗口。本协议是单用户、同 UID 非对抗边界，
不是 OS sandbox，也不承诺第三方 target 在任意竞态下不受影响。

## 请求与错误

所有请求使用 exact JSON、协议/launch/session/capability/deadline header，并在 Main
边界重新验证 corpus revision、文本上限和 safe local library ID。Main 只调用 sidecar 的
只读 resolve/query port，不向 companion 暴露任意 HTTP、SQL、路径或命令入口。

稳定错误码为：

`approval_denied`、`backend_unavailable`、`busy`、`expired`、`forbidden`、
`invalid_request`、`invalid_response`、`not_found`、`protocol_mismatch`、
`rate_limited`、`request_too_large`、`revoked`、`stale_revision`、`timeout`、
`unauthorized`、`unavailable`。

原始异常、路径、socket、token、capability、Backend body 和 native stderr 不跨越 stdio
工具结果或 renderer 状态边界。

## source/debug 例外

source contract tests 只有同时设置 `LCF_MCP_DEBUG=1`、absolute normalized socket、
UUID launch ID 和 absolute normalized temp root 时才可绕过默认 rendezvous discovery。
runtime 必须仍是 temp root 的直接 `lcf-mcp-*` 子目录，socket 仍固定名 `mcp.sock`；
部分或额外 debug 环境变量一律拒绝。该入口不得出现在 packaged app 的 Codex 配置中。

## 打包与验证

`desktop/scripts/auditCompanion.cjs` 和 Electron `beforePack` 对 companion 的 bundle Node、
入口、inventory、SBOM、notices、schema 与 build manifest 执行 fail-closed 审计。

2026-07-31 的 source 测试已覆盖 SDK contract replay、授权/撤销、revision、上限、rate
limit、tamper、rendezvous、marker 删除、per-scope ownership、ledger exact mode、bundle
chain 和清理。MCP core 为 3 files / 37 pass；onboarding Desktop 为 6 files / 73 pass；
bridge 为 4 files / 15 pass / 7 skip；Web onboarding 为 3 files / 25 pass，代码证据在
`fcca1e4`。7 个 skip 未执行，不得折算为通过。真实 packaged macOS arm64、官方签名 Codex、
Codex 重启、两个工具调用以及 app move/reconnect/clear 仍为 `not-run`；详见
[R08 验证日志](iterations/0002-r08-mcp-onboarding.md#验证日志)。
