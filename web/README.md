# Local Context Forge Web

本目录是管理工作台，使用 Vite、React 和 TypeScript。

```bash
npm install
npm run dev
```

提交前可运行契约测试、类型检查和生产构建：

```bash
npm test
npm run typecheck
npm run build
```

开发环境默认将 `/api` 代理到 `http://localhost:8000`。可通过
`VITE_DEV_API_TARGET` 修改代理目标，或通过构建期变量 `VITE_API_BASE`
指定绝对 API 地址：

```bash
VITE_API_BASE=http://localhost:8000 npm run build
```

`VITE_API_BASE=/api` 也受支持，前端会避免与端点中的 `/api` 重复。
Docker 镜像使用 Nginx 提供静态文件，并将 `/api/` 代理到 Compose
网络中的 `api:8000`。健康检查端点为 `/healthz`。

这是管理面，不是只读文档站：它可以创建 library、启动 ingest、批准或
拒绝 proposal、删除 library 并触发重新索引。当前后端没有应用级认证、
ACL、TLS 或多租户隔离，默认部署仅面向 loopback 上的受信任单用户。若要
供团队共享，必须先增加认证反向代理、TLS、审计以及请求/响应大小限制。
