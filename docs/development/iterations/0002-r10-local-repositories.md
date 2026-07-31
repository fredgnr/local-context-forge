# ITER-0002/R10：Local and private repositories

- 状态：`in-progress`
- 日期：2026-07-31
- 父迭代：[ITER-0002](0002-bundled-runtimes.md)
- 决策：[ADR-0012](../../adr/0012-local-repository-picker-opaque-grants.md)
- 需求：REQ-LOCAL-SOURCE-001、REQ-TRUST-001、REQ-GIT-001、REQ-IPC-001
- 验证：VAL-LOCAL-SOURCE-001、VAL-LOCAL-SOURCE-002、VAL-LOCAL-SOURCE-003

## 目标与固定范围

为 desktop 用户提供原生目录选择器，使已经用现有 Git/SSH 工具克隆的本地或私有仓库可被
采集和重建。renderer 只持有一次性不透明 grant 与目录显示名；绝对路径只在 Main 和
desktop sidecar 内部流动。

Local Context Forge 不接收、保存或代理 GitHub token、SSH key、cookie 或 Keychain
凭据。browser/Docker 的公开 HTTPS 和显式 imports 策略保持兼容。本轮不引入
security-scoped bookmark、fd-based snapshot、OS App Sandbox 或仓库凭据登录。

## 任务

- [x] **R10-01 grant 生命周期**：256-bit 随机值、固定语法、单调五分钟 TTL、单次消费；
  新选择撤销旧值，未知/猜测/重放/退出竞态 fail closed。
- [x] **R10-02 Main 路径策略**：canonical absolute、非 symlink、当前 uid、safe
  dev/inode、消费时身份重验；仅 home/volume 严格子目录，拒绝 root/mount root、敏感
  配置根和 Application Support/cache 重叠。
- [x] **R10-03 最小 IPC**：无参数 picker，只返回 `{grantId, displayName}`；创建请求仅可
  传 opaque grant，preload/status/error/library 不泄露本地路径。
- [x] **R10-04 sidecar 注入**：Main 消费授权后改写内部 create payload，并以固定重复
  argv 传 home 与 `/Volumes` 根；desktop sidecar 不信任 renderer 或环境变量根。
- [x] **R10-05 Backend 权威重验**：在 catalog/evidence 前重验 canonical root、当前 uid、
  敏感目录、允许根和缺失目录；已登记路径可供应用重启后的 ingest/rebuild 使用。
- [x] **R10-06 Web UX**：选择/取消/创建状态有限且可恢复，显示名不作为路径或授权输入，
  browser 模式不暴露 picker。
- [x] **R10-07 负向与回归**：覆盖 inode/device、owner、mount、symlink、数据/cache、
  sensitive roots、env bypass、ApiProxy 脱敏和 Docker/browser 兼容。
- [ ] **R10-08 物理门禁**：packaged macOS arm64 上覆盖 home、外置卷、私有仓库、移动/
  删除目录、应用重启和同 uid TOCTOU 观察。

## 验收

- renderer 不能提交、枚举或读取绝对路径，也不能控制允许根、uid、device/inode 或
  sidecar argv/env；
- grant 难以猜测、只消费一次，过期/重放/新选择/退出/inode drift 均拒绝；取消不产生
  grant；
- home/volume 根、嵌套挂载根、symlink、其他 owner、unsafe integer、Application
  Support/cache 和 `~/.codex`/`CODEX_HOME`/SSH/Kubernetes/AWS 等敏感根均在 Main 拒绝；
- desktop sidecar 只接受 Main 的 canonical argv roots，每次重启和使用前重验 owner 与
  敏感根；`LCF_LOCAL_SOURCE_ROOTS` 不能扩大 desktop 边界；
- 失败错误、library/API/MCP/evidence 输出不含本地绝对路径或凭据内容；
- 路径授权不放宽 ADR-0006 的 snapshot 文件、大小、symlink、Git 对象和 Wiki 输出约束；
- Docker/browser 保持旧的显式 imports 行为，不被 desktop uid 策略意外阻断。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| VAL-LOCAL-SOURCE-001 core | `pass` | 2026-07-31；`8eedd7e` | `cd desktop && ./node_modules/.bin/vitest run tests/localSourceGrants.test.ts tests/localSourcePicker.test.ts tests/localSourcePolicy.test.ts tests/ipc.test.ts` | 4 files / 30 pass；grant 生命周期、路径/owner/device/inode/mount/sensitive roots、无路径 IPC |
| VAL-LOCAL-SOURCE-001 full source | `pass` | 2026-07-31；`fcca1e4` | `cd desktop && npm test -- --run`；`cd web && npm test -- --run` | Desktop 30 files / 235 pass / 7 skip；Web 7 files / 51 pass |
| VAL-LOCAL-SOURCE-002 focused | `pass` | 2026-07-31；`8eedd7e` | `cd backend && .venv/bin/pytest -q ../tests/backend/test_source_security.py ../tests/backend/test_desktop_transport.py` | 103 pass / 1 AF_UNIX skip；argv-only roots、owner/sensitive root 重验、环境绕过和 transport 脱敏 |
| VAL-LOCAL-SOURCE-002 full Backend | `pass` | 2026-07-31；`8eedd7e` | `cd backend && .venv/bin/pytest -q ../tests/backend` | 313 pass / 1 skip |
| VAL-LOCAL-SOURCE-003 packaged macOS | `not-run` | — | 需物理 macOS arm64 packaged app、home/外置卷/私有 repo 与重启矩阵 | source/Linux 测试不能证明 NSOpenPanel、真实卷或 packaged 数据目录 |

## 风险与回滚点

| 风险 | 缓解/回滚点 |
| --- | --- |
| grant 已消费但 renderer 未收到结果 | 消费结果保持 uncertain；不允许 replay，用户重新选择 |
| 用户移动、删除目录或换 uid | 未消费授权 identity 重验失败；已登记任务由 Backend 明确报不可用 |
| 同 uid 原位替换已登记目录 | Backend 当前不持久保存登记时 inode，残余风险留给 bookmark/fd 方案 |
| 检查与读取之间同 uid TOCTOU | Main/Backend 双层 canonical/owner/sensitive 检查；不宣称抵御同 uid 恶意进程 |
| Backend 原始异常包含路径 | 稳定错误映射和 ApiProxy/MCP 脱敏；packaged 错误路径实测仍待物理门禁 |

## 当前变更清单

- `docs/adr/0012-local-repository-picker-opaque-grants.md`
- `docs/development/iterations/0002-r10-local-repositories.md`
- `docs/development/traceability.md`
- `desktop/src/main/{localSourceGrants,localSourcePolicy,localSourcePicker,ipc,index,sidecar}.ts`
- `desktop/src/{contracts}.ts`
- `desktop/src/preload/index.ts`
- `desktop/tests/{localSourceGrants,localSourcePicker,localSourcePolicy,ipc,preload,sidecar}.test.ts`
- `backend/app/{cli,config,source}.py`
- `tests/backend/{test_source_security,test_desktop_transport}.py`
- `web/src/{App,App.test}.tsx`
- `web/src/{desktopBridge,desktopBridge.test}.ts`
- `web/src/styles.css`

R10 的 source 纵切已验证，但 physical `VAL-LOCAL-SOURCE-003` 未运行；父迭代因此继续
`in-progress`。
