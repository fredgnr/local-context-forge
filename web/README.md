# Local Context Forge Web

本目录是 Electron renderer 的管理工作台，使用 Vite、React 和 TypeScript。独立 browser
hosting 已 deprecated/unsupported，并将在 ITER-0007 中删除。

当前源码尚可观察到两种宿主，但只有第一种属于目标产品：

- Electron 桌面模式由 `lcf://app/` 加载，只能通过 typed preload IPC 调用 Main；
- legacy Web/Docker 模式由 Nginx 提供并通过 loopback HTTP 调用 FastAPI；只作为 removal
  inventory，不得用于新开发或部署。

不要在桌面 renderer 中恢复任意 HTTP base URL、Node integration 或直接 socket 访问。系统边界见
[`docs/17-system-design.md`](../docs/17-system-design.md)，当前可交付状态见
[`docs/development/status.md`](../docs/development/status.md)。

依赖安装、build/test 和 Electron source 启动以根 `CONTRIBUTING.md` 为准。`npm run dev` /
`preview` 当前会建立 browser listener，属于 `web/package.json` 的 `split` 范围，不是受支持
产品入口。

提交前可运行契约测试、类型检查和生产构建：

```bash
npm test
npm run typecheck
npm run build
```

这里的 Vite 开发服务器默认将 `/api` 代理到 `http://localhost:8000`。可通过
`VITE_DEV_API_TARGET` 修改代理目标，或通过构建期变量 `VITE_API_BASE`
指定绝对 API 地址：

```bash
VITE_API_BASE=http://localhost:8000 npm run build
```

`VITE_API_BASE=/api` 也受支持，前端会避免与端点中的 `/api` 重复。
legacy Docker 镜像使用 Nginx 提供静态文件，并将 `/api/` 代理到 Compose
网络中的 `api:8000`。健康检查端点为 `/healthz`。

这是管理面，不是只读文档站：当前客户端可以创建 library、启动 ingest、
批准或拒绝 proposal、查询已发布文档，并按宿主暴露的能力触发重建、graph
或 lint。legacy 后端仍有原始 library `DELETE` API，但当前 Web 客户端和
Desktop Renderer allowlist 都没有删除操作。当前后端没有应用级认证、ACL、
TLS 或多租户隔离，默认部署仅面向 loopback 上的受信任单用户。若要供团队
共享，必须先增加认证反向代理、TLS、审计以及请求/响应大小限制。

Electron 模式同样按单用户、同 UID 非对抗模型设计，但它不开放公共 HTTP
监听；Main 是 renderer 与本地 sidecar、QMD worker、provider、文件选择器和 updater
之间的安全边界。
