# Local Context Forge TODO

项目剩余工作的权威清单位于：

- [详细 TODO、依赖、Owner 与验收条件](docs/development/todo.md)
- [当前状态与阻塞](docs/development/status.md)
- [活动迭代](docs/development/iterations/0002-bundled-runtimes.md)
- [需求—决策—验证矩阵](docs/development/traceability.md)
- [Electron-only legacy retirement 严格范围](docs/development/legacy-retirement.md)
- [Pre-1.0 W01–W16 execution rank](docs/development/work-plan.md)

当前总体结论：

> **source merge GO / public release NO-GO**

当前已接受 Electron-only 的 pre-1.0 不兼容收敛方向。Docker/Compose、browser Web、公开 TCP
API、legacy MCP、Host Runner 与 container/GHCR 均进入删除计划；`web/src` renderer、
`backend/app` private UDS sidecar/domain、Desktop MCP/QMD/release 路径明确受保护。旧数据不迁移，
也不会被自动删除。实际顺序是 W01 governance/source exits → W02 最小 packaged smoke → W10/W11 独立 slices → W03 cleaned
engineering package → W04–W12 工程物理矩阵 → W13 final cutover/absence → W14–W16 production
controls/credentials/formal Release；单个 slice 不再等待完整聚合 cutover，但必须满足自己的
before/after packaged、absence、protected-path 和数据安全门禁。正式候选还要绑定 W13 checkpoint
到 tag 的受限 diff，并在 exact Draft 重新运行完整 cutover/absence。

不要在本文件复制任务正文，以免与迭代和追踪矩阵漂移。开始工作前先在详细 TODO 中认领稳定
task ID，并按 [开发者手册](docs/development/contributor-handbook.md)更新证据链。
