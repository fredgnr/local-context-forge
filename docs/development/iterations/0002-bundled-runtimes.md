# ITER-0002：Bundled runtimes

- 状态：`planned`
- 依赖：ITER-0001 的源码模式 trust/IPC 契约通过
- 路线图阶段：P2、P3

## 目标与范围

把已冻结的源码模式进程边界变成无需系统 Python/Node 的应用内置运行时：

- 固定 Python 3.12，以 PyInstaller `onedir` 交付 sidecar；
- 固定 Node 22，以独立 worker 交付 QMD；
- 保持 Context7 兼容的 `resolve-library-id`、`query-docs` 契约；
- 任务开始前对 Codex CLI 做默认 preflight，失败时才可选择 Cursor CLI；
- 任务进入执行态后不进行 provider fallback 或隐式重试。

不包含 DMG 发布、旧数据切换或自动更新。

## 计划任务

- [ ] R01 生成可审计、可复现的 Python `onedir` 资源清单。
- [ ] R02 从 Electron Main 启动内置 sidecar，并回归现有领域测试。
- [ ] R03 交付独立 Node 22/QMD worker，禁止 renderer 命令入口。
- [ ] R04 回放 MCP 兼容契约。
- [ ] R05 完成 Codex/Cursor preflight 与无执行后 fallback 的负向测试。

## 退出门禁

- VAL-PY-001、VAL-QMD-001、VAL-CLI-001、VAL-MCP-001 为 `pass`；
- packaged runtimes 不读取系统 Python、Node、Git 或 ctags；
- 资源清单、许可证、版本和失败恢复均有可复现证据。
