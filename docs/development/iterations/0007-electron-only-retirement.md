# ITER-0007：Electron-only cutover 与 legacy retirement

- 状态：`planned`
- 依赖：ADR-0015；E02 只依赖各能力的 source replacement 子门禁；E03–E07 依赖聚合
  `VAL-ELECTRON-CUTOVER-001=pass` 和相关 packaged M4 gate
- 路线图阶段：P7
- 关联需求：REQ-ELECTRON-ONLY-001、REQ-PRE1-BREAKING-001
- 关联验证：VAL-ELECTRON-CUTOVER-001、VAL-LEGACY-ABSENCE-001

## 目标

把 macOS Apple Silicon Electron 客户端收敛为唯一受支持的产品路径，并彻底删除只服务于
legacy Docker/browser/public-HTTP/container 形态的代码、依赖、运维和发布面。项目不提供
legacy 数据 importer、配置转换器、API compatibility shim 或并行运行期。

## 严格边界

实施必须遵循 [legacy retirement manifest](../legacy-retirement.md)：

- 只删除清单中标为 `remove` 的 surface；
- `split` 路径必须先把 Electron 所需部分分离并有回归证据；
- `retain` 路径属于 Electron 产品，不因目录名包含 Web/API/MCP 而删除；
- 删除代码不自动删除用户的旧 data、volume、imports 或 backup；
- 历史 ADR、iteration 和 evidence 继续保留。

## 计划任务

- [ ] E01 完成 `TODO-ELECTRON-CUTOVER-001` capability matrix，记录 source 与 packaged/physical
  证据，未通过的能力不得靠文档声明替代。
- [ ] E02 完成 `TODO-LEGACY-DECOUPLE-001`，只抽离 renderer/sidecar/provider 的 Electron
  caller 和 legacy 分支；聚合 cutover 通过前不删除 capability。
- [ ] **E02a Full-cutover checkpoint**：在 E02 的解耦后 tree 上完成 E01 的 clean-M4 packaged
  聚合验证；只有 `VAL-ELECTRON-CUTOVER-001=pass` 才能开始 E03/E04 的任何删除。
- [ ] E03 完成 `TODO-LEGACY-REMOVE-DEPLOY-001`，删除 Compose、Dockerfiles、Nginx、旧安装器、
  lifecycle/backup/restore/smoke 脚本和 Host Runner。
- [ ] E04 完成 `TODO-LEGACY-REMOVE-TRANSPORT-001`，删除 browser HTTP adapter、公开 TCP/CORS、
  legacy MCP gateway 和兼容分支，同时保留 private UDS sidecar 与 stdio companion。
- [ ] E05 完成 `TODO-LEGACY-REMOVE-RELEASE-001`，删除 container workflow/GHCR、container tag
  文档与旧 Make/CI targets。
- [ ] E06 完成 `TODO-LEGACY-REMOVE-DOCS-001`，删除或改写用户可执行的 legacy 指南、示例和
  环境变量；历史记录不删。
- [ ] E07 完成 `TODO-LEGACY-ABSENCE-001`，在最终 removal commit 执行
  `VAL-LEGACY-ABSENCE-001` 和 Electron aggregate/package 回归，记录允许的历史命中 allowlist。

## 退出门禁

- `VAL-ELECTRON-CUTOVER-001` 对本次删除涉及的每项能力为 `pass`；
- clean Apple Silicon packaged candidate 能完成索引、审核、排队、查询、Wiki、embedding
  model/rebuild、Codex/Cursor provider 和 Context7 MCP 核心流程；
- `VAL-LEGACY-ABSENCE-001` 为 `pass`，生产路径无 legacy listener、container 或兼容 shim；
- 最终 removal commit 构建的新 candidate digest 已重新通过完整核心 packaged capability matrix；
  删除前 candidate 或 final smoke 不能证明最终 bytes；
- Electron renderer、private UDS sidecar、MCP companion、QMD worker、数据与发布安全回归通过；
- 删除行为不触碰用户旧数据；公开 Release 仍服从独立 P5/P6 门禁。

## 回退语义

代码变更可通过普通 Git revert 回退；这不构成 legacy 产品兼容承诺。删除后的 Electron 版本
不会自动恢复旧 Docker 服务，也不会读取、迁移或删除旧数据。若切换门禁失败，应停止 removal
PR 并修复 Electron 替代能力，而不是重新扩展 legacy 长期支持。
