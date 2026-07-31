# ADR-0008：内置 MCP companion 与 Main 私有桥接

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-MCP-001、REQ-TRUST-001、REQ-IPC-001

## 上下文

桌面版需要像 Context7 一样被本机 coding client 调用，但不能要求 Python/Node/npm，也不能
把 Python/QMD 的启动 token、管理 API 或审核/发布能力暴露给任意 MCP client。MCP client
通常启动 stdio server；Electron app 可能尚未运行、重启或 corpus 已变化。

## 决策

1. 应用 resources 内置固定 Node runtime 和一个最小 stdio MCP companion。用户配置中的
   command 指向 bundle 内绝对路径和固定入口，不使用 `npx`、shell 或系统 Node。
2. companion 只实现 Context7 兼容的 `resolve-library-id` 与 `query-docs` 两个工具，并用
   canonical JSON schema 与官方 MCP SDK client 回放保护名称、字段和结果语义。
3. companion 通过 Electron Main 拥有的独立私有 `mcp.sock` 访问只读查询桥。它不连接
   Python/QMD socket，也不获得其 token；Main 为 MCP 使用独立 capability、大小/并发/超时
   和速率限制。
4. Main 只向 MCP 桥暴露 resolve/query 格式化结果。ingest、review、publish、settings、
   provider、路径、模型、更新和原始文件能力不在该接口中。
5. source/debug 阶段每个新 client 连接都需要用户在 UI 明确批准，并可撤销；未知、过期、
   超大、断连、app 未运行或 corpus revision 不一致均 fail closed。不得弹出或记录 secret。
6. production 的持久配对、Keychain 和 client code-identity 绑定推迟到后续迭代。在对应门禁
   完成前，文档必须说明 app 需运行且 source/debug 配对为手动授权。
7. companion 的 stdout 只承载 MCP framing；诊断写入有界 stderr 且脱敏，不包含 repository
   内容、capability、socket 路径或 sidecar 输出。

## 后果

- coding client 获得稳定 Context7 风格入口，同时无法触达桌面管理能力；
- app 未运行时 MCP 明确失败，不会偷偷启动另一套数据库 writer；
- source/debug 可以验证协议，但持久、安全的 production pairing 仍是后续门禁；
- bundle 需要同时分发 companion、SDK 依赖和共享 Node runtime。

## 替代方案

1. **继续要求 `python -m mcp_server`。** 拒绝：违反无系统 Python。
2. **companion 直连 Python/QMD。** 拒绝：泄露内部 capability 并绕过 Main policy。
3. **把 HTTP API 暴露到 localhost。** 拒绝：扩大网络面和认证复杂度。
4. **MCP 自动拥有全部桌面操作。** 拒绝：Context7 兼容不需要写权限。

## 验证门禁

- VAL-MCP-001 使用官方 SDK ClientSession 回放两个工具的 list/call、schema、分页/上限、
  not-found 和格式化结果。
- 负向测试覆盖 app 未运行、未批准/已撤销 client、错误 capability、stale revision、
  oversize、超时、未知工具和 companion 崩溃。
- packaged smoke 使用 bundle 内 Node/companion 且 `PATH` trap 失败时仍通过；验证 stdout
  无非协议输出，renderer 不获得 MCP capability。

