# ADR-0001：Electron、Python sidecar 与 QMD worker 边界

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-PLATFORM-001、REQ-TRUST-001、REQ-PY-001、REQ-QMD-001、
  REQ-CLI-001、REQ-MCP-001

## 上下文

现有系统由 Python API、Web UI、MCP、QMD 与宿主 CLI/Docker 组合运行。目标发行物是
macOS Apple Silicon Electron all-in-one，终端用户不应安装 Docker、Homebrew、Python、
Node.js、Git 或 ctags。把现有服务直接暴露给 renderer，或让 renderer 获得 Node 权限，
会把不可信仓库内容、Markdown 和模型输出带入宿主权限域。

Python 领域逻辑需要保留；QMD 需要 Node 运行时。两者有不同的依赖、故障和升级周期，
不能用“单一进程”掩盖边界。CLI provider 还会接触用户现有登录状态，必须在任务执行前
冻结选择。

## 决策

采用以下进程拓扑：

```text
untrusted content
      |
React renderer (sandboxed)
      |
typed preload IPC
      |
Electron Main (trust boundary)
      ├── private UDS ── Python 3.12 PyInstaller onedir sidecar
      ├── private UDS ── bundled Node 22 / QMD worker
      └── allowlisted launch ── selected Codex or Cursor CLI
```

1. Electron Main 是唯一桌面信任边界，拥有窗口、权限、文件访问、子进程生命周期、
   runtime 路径、模型下载、更新和外部打开操作。
2. React renderer 启用 sandbox 和 context isolation，关闭 `nodeIntegration`。renderer
   不能获得 Electron 原始 IPC、令牌、socket 路径、任意文件路径、命令执行或 updater 对象。
3. preload 只公开版本化、类型化、allowlist 的用户意图。Main 在执行前再次验证 schema、
   大小、状态和路径范围；取消和错误也使用稳定契约。
4. 现有 Python 领域能力固定以 Python 3.12 构建为 PyInstaller `onedir` sidecar。应用从
   自身 resources 启动它，绝不发现或调用系统 Python/Git/ctags。
5. QMD 在独立 Node 22 worker 中运行。Node runtime 与 QMD 依赖随应用交付；worker 不与
   renderer 直接通信，也不提供 shell/任意模块入口。
6. Main 负责启动、探活、超时、取消、优雅停止和崩溃处理。Python 与 Node 各有独立
   socket 和每次启动令牌，协议见 [ADR-0002](0002-uds-startup-token-protocol.md)。
7. CLI provider 在任务开始前 preflight：Codex CLI 是默认；只有 Codex 在 preflight
   不可用或未登录时，才可选择已安装且已登录的 Cursor CLI。provider 一经选定即写入任务；
   执行开始后的失败、超时或不确定结果不得切换 provider 重试。
8. MCP 保持现有 Context7 兼容的 `resolve-library-id` 与 `query-docs` 工具名、输入字段和
   结果语义。内部传输可以改变，外部兼容契约必须由回放测试保护。
9. 模型权重不进入应用 bundle，按
   [ADR-0004](0004-runtime-paths-legacy-data-migration.md) 的规则按需获取。

## 后果

正面后果：

- renderer 漏洞不会自动获得宿主 Node、文件或子进程能力；
- Python 与 QMD 可独立打包、崩溃恢复和升级；
- 目标机不依赖用户运行时，问题可由明确的 bundle 版本复现；
- provider 不在未知执行结果后重复消费或产生冲突输出；
- MCP 消费端不需要随桌面内部架构迁移。

成本与限制：

- 需要维护三类契约：renderer/Main、Main/Python、Main/QMD；
- PyInstaller `onedir` 和内置 Node 增大 DMG，并要求资源清单/许可证审计；
- sidecar 是本机同用户进程隔离，不是操作系统沙箱；Main 仍须把输出视为不可信；
- Cursor 不能在 Codex 已开始执行后“救援”任务，用户需要明确重试；
- 旧 Docker 与新桌面会在迁移期形成两套启动路径。

## 替代方案

1. **把 Python 服务继续放在 Docker 中。** 拒绝：违反无需 Docker 的发行目标。
2. **把 Python 嵌入 Electron/renderer。** 拒绝：扩大 renderer 权限并耦合崩溃与依赖。
3. **将现有领域逻辑全部重写为 TypeScript。** 暂不采用：迁移范围和回归风险过大。
4. **让 Python 进程同时托管 QMD。** 拒绝：仍需 Node，且混合依赖/生命周期。
5. **调用用户系统 Python/Node/Git。** 拒绝：不可复现且违反 all-in-one。
6. **运行时从 Codex 自动切换 Cursor。** 拒绝：可能重复消费和产生不可判定副作用。

## 验证门禁

- VAL-TRUST-001：安全设置和负向 IPC 测试证明 renderer 无特权逃逸面。
- VAL-PY-001：在无系统 Python/Git/ctags 的干净 arm64 用户中运行打包 sidecar 回归。
- VAL-QMD-001：在无系统 Node/QMD 的干净 arm64 用户中完成索引和查询。
- VAL-CLI-001：覆盖 Codex 默认、preflight Cursor、缺失/登出、超时，以及任务开始后
  不 fallback。
- VAL-MCP-001：对 `resolve-library-id` 和 `query-docs` 执行 Context7 兼容回放。
- VAL-INSTALL-001：从 DMG 启动完整进程树，不借用目标机外部运行时。

以上门禁当前均尚未运行；决策被接受不代表实现已经通过。
