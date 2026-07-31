# ADR-0005：桌面 CLI provider 选择与 attempt 执行边界

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-CLI-001、REQ-TRUST-001

> **后续关系：** 本 ADR 仍为 Accepted；保留 legacy browser/Docker provider/Host Runner 的要求
> 已由 [ADR-0015](0015-electron-only-legacy-retirement.md#对既有-adr-的影响)部分取代。Desktop
> attempt CAS、preflight-only fallback 与 no-replay 边界继续有效。

## 上下文

桌面版默认复用用户已经登录的 Codex CLI，Cursor CLI 仅作为可选 fallback。CLI 会读取
自身凭据并执行模型请求；如果 renderer 能选择 executable/argv，或任务在未知结果后切换
provider 重试，会形成命令注入、重复计费和重复发布风险。现有 browser/Docker 的
`host_runner` 仍需兼容，但不能成为桌面 Main 的执行代理。

## 决策

1. 桌面模式只提供 `codex_only` 和 `codex_then_cursor` 两种策略；默认
   `codex_only`。不提供 `cursor_only`、反向优先级或 renderer 自定义命令。
2. Cursor fallback 必须有版本化的当前用户同意记录。没有同意、同意版本过期或 Cursor
   preflight 失败时，策略退化为 `codex_only` 并给出可操作诊断。
3. Main 先验证官方 npm wrapper 元数据与安装布局，再解析、固定并重新校验 macOS arm64
   原生 executable。真正执行时直接启动该原生目标，不调用 shell、登录 shell、npm wrapper
   或系统 Node。
4. Python 领域层创建并持久化 `provider_attempt`，包含策略、候选、选择、状态、输入摘要、
   有界 evidence 路径和 corpus/job 关联。Main 通过 desktop-only、已认证接口 claim attempt。
5. Main 在 preflight 后以 compare-and-swap 写入选定 provider 和 executable identity。
   `execution_committed_at` 写入成功后才可 spawn；同一 attempt 最多一次从
   `selected` 进入 `executing`。
6. 只有 Codex 在 spawn 前明确为 `not_installed` 或 `not_authenticated` 时，且用户已同意，
   才能选择 Cursor。spawn、超时、取消、崩溃、输出解析失败或结果不确定之后绝不切换
   provider，也不自动开始新的 attempt。
7. 子进程使用固定参数模板、最小环境、独立进程组、超时/取消、输出与 schema 上限。
   renderer 只得到稳定状态和脱敏错误，不得到 executable、argv、PID、socket、令牌或 stderr。
8. App 启动恢复发现 `execution_committed_at` 已写但没有确定终态的 attempt 时，将其标记为
   `uncertain`，需要用户明确重试；不得再次执行。
9. legacy browser/Docker provider 行为继续保留，直到独立退出门禁授权删除。

## 后果

- provider fallback 的合法窗口、执行唯一性和崩溃恢复可以由数据库状态证明；
- 用户现有 CLI 登录仍由 CLI 自己拥有，应用不复制或迁移凭据；
- provider 状态机、Main supervisor 和 UI 需要共同维护稳定契约；
- 运行中失败不能自动“换模型救援”，用户必须看到不确定状态并决定下一步。

## 替代方案

1. **renderer 传入 CLI 路径和参数。** 拒绝：扩大命令执行面。
2. **始终通过 npm wrapper 启动 Codex。** 拒绝：目标机将隐式依赖系统 Node/npm。
3. **失败后自动切 Cursor。** 拒绝：无法区分未执行和已产生副作用。
4. **只把 provider 写在 job JSON。** 拒绝：缺少可恢复的 claim/commit/终态证据。

## 验证门禁

- VAL-CLI-001 覆盖两种允许策略、Cursor consent、Codex 缺失/登出、identity 漂移、
  compare-and-swap 竞争、固定 argv/env、超时、取消、崩溃和输出上限。
- cut-point 测试覆盖 create、claim、select、commit、spawn 和 complete 之间的进程终止；
  commit 之后恢复必须为 `uncertain` 且不得重放。
- 进程与日志检查不得出现 CLI 凭据、完整环境、私有仓库内容或 renderer 可控命令。
