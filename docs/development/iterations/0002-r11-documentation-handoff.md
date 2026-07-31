# ITER-0002/R11：Documentation handoff

- 状态：`in-progress`
- 日期：2026-07-31
- 父迭代：[ITER-0002](0002-bundled-runtimes.md)
- 审计基线：`main@fb8bbbc3d0b4e4b5a20c943bd7fd71b2450651a8`
- 工作分支：`agent/documentation-handoff`
- 需求：REQ-GOV-001、REQ-DOC-001
- 验证：VAL-GOV-001、VAL-DOC-HANDOFF-001

## 目标与固定范围

把 PR #7、#8、#17 合并后的真实源码状态、架构、部署路径、开发流程、剩余任务和发布
NO-GO 边界整理成可由下一位贡献者独立执行的文档集。

本轮是 documentation/governance 变更：

- 不改变 accepted runtime/release architecture；
- 不 provision GitHub secret、证书或更新私钥；
- 不创建 tag、Draft、Release、DMG 或 container image；
- 不把 source evidence 提升为 packaged/physical `pass`；
- 只允许修正会误导命令执行的 user-facing help/文档。

## 审计输入

三路独立只读审计：

1. 系统架构和代码所有权；
2. Electron/legacy 部署、backup、Release 和危险命令；
3. 新贡献者路径、CI、traceability 和完整剩余任务。

主执行者另行逐份读取 ADR-0001–0014、父迭代、路线图、追踪矩阵、Release runbook 和关键
代码装配文件。审计不作为 packaged/physical gate。

## 任务

- [x] **R11-01 状态权威页**：建立 commit-bound status、gate summary、blocker 和 next action。
- [x] **R11-02 组合系统设计**：记录 desktop/legacy topology、六条时序、trust/data/recovery、
  ownership 和 implemented/planned/unsupported。
- [x] **R11-03 部署运维**：建立路径决策、legacy control、source mode、backup/restore、
  GitHub settings、credential、Draft/promotion/update 门禁。
- [x] **R11-04 开发手册**：记录 onboarding、版本/venv、目录、测试矩阵、ADR/iteration/
  traceability/evidence/PR 工作流。
- [x] **R11-05 TODO**：为全部未完成工作分配稳定 task ID、priority、component owner、
  dependency、artifact 和 acceptance。
- [x] **R11-06 Evidence 规范**：建立 source/settings/release/physical/not-run 模板和脱敏规则。
- [x] **R11-07 入口同步**：README、AGENTS、CONTRIBUTING、docs/dev/component indexes。
- [x] **R11-08 冲突修复**：安装入口、Docker context/env、统一 release tag、版本门禁、
  data/API/MCP mode 边界。
- [ ] **R11-09 验证与发布**：link/diff/help consistency，提交、PR、最终 head CI、合并。

## 关键纠正

1. `make install`/`install.sh` 是 legacy Docker，不是 Electron。
2. 已安装 legacy 实例应通过最小 `env -i` 包装调用 `scripts/lcf`；当前脚本本身尚未隔离
   `COMPOSE_PROJECT_NAME` 和调用者插值变量，不能只靠“不是裸 Compose”判断实例安全。
3. `.lcf/runtime.env` 才是安装器记录，不是普通 `.env`。
4. 同一个 `v*.*.*` tag 同时触发 container SemVer 与 desktop Draft；必须作为统一产品
   Release 管理。
5. 早期 ADR 的 `0.0.1 → 0.0.2` 是示例，实际门禁必须使用真实单调 `N-1 → N`。
6. “桌面源码完成”改为“主要 source foundation 已合并”，packaged/data/release 仍未完成。
7. 当前 desktop 数据布局只部分实现 ADR-0004；backup/restore/migration 不得写成已交付。
8. Release workflow 使用的唯一 private credential 不等于整个组织不存在其他无关 secret。
9. ITER-0002 的 exit 不再依赖 P5/P6 物理 Release，从而消除 P2/P3 → P4 → P5/P6 → ITER-0002
   的循环；R09 只记录提前完成的 source foundation。

## 验收

- [x] 新贡献者可从根 README/AGENTS/CONTRIBUTING 进入同一 status、design、deployment、
  contributor、TODO 和 evidence 权威页；
- [x] Electron、source 和 legacy 命令不会混淆；
- [x] 每个剩余任务有 owner component、dependency、artifact 和 gate；
- [x] 所有“已实现”与 `not-run` 分开；
- [x] 相对 Markdown 链接在本地预提交检查中全部有效；
- [x] 本地预提交 `git diff --check` 通过；
- [x] Makefile help 明确 legacy；
- [ ] documentation PR 最终 head CI 成功；
- [ ] 合并后仍保持 **source merge GO / public release NO-GO**。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令/证据 | 说明 |
| --- | --- | --- | --- | --- |
| VAL-DOC-HANDOFF-001 首轮 content audit | `fail` | 2026-07-31；`main@fb8bbbc` input + R11 worktree | 三路独立只读审计 + 主执行者 ADR/代码复核 | 发现进程边界、legacy instance control、evidence/task mapping 等阻断项；已进入修复 |
| VAL-DOC-HANDOFF-001 修复后 content audit 本地观察 | `pass` | 2026-07-31；dirty R11 worktree | 三路最终只读复核 | 架构、部署/发布、开发交接均无剩余 Critical/High/Medium；仅证明当前工作树内容 |
| VAL-DOC-HANDOFF-001 commit-bound checkpoint | `pass` | 2026-07-31；`625db7647d47fb6ff8f23c3136c4f45ded80384f` | [脱敏证据记录](../evidence/VAL-DOC-HANDOFF-001/2026-07-31-625db76.md) | 冻结全部实质文档；三路复核和精确命令可追溯 |
| Markdown links checkpoint | `pass` | 2026-07-31；`625db76` clean checkout | `python3 -B tools/check_markdown_links.py` | 76 files |
| Diff whitespace checkpoint | `pass` | 2026-07-31；`625db76` clean checkout | `git diff --check HEAD^ HEAD` | exit 0 |
| Version sync checkpoint | `pass` | 2026-07-31；`625db76` clean checkout | `python3 tools/check_version_sync.py` | `0.3.0-alpha.1`、desktop protocol `1.0` |
| Make help checkpoint | `pass` | 2026-07-31；`625db76` clean checkout | `make help` | legacy/Electron 与 aggregate exclusions 明确 |
| VAL-DOC-HANDOFF-001 final head | `not-run` | — | clean checkout + 最终 PR head 复核 | 本地 content pass 不能绑定尚未产生的 commit bytes |
| VAL-GOV-001 R11 final head | `not-run` | — | 最终 PR head Actions | dirty worktree 的成功不能绑定最终 bytes |
| PR CI | `not-run` | — | 最终 PR head Actions | 本地验证后运行 |
| Packaged/physical/release gates | `not-run` | — | 非本轮范围 | 不能由 docs PR 提升 |

## 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 多份文档复制状态再次漂移 | `status.md` 为当前状态权威；其他入口链接它 |
| TODO 与 iteration 重复 | TODO 只 roll-up；task 细节回链迭代/ADR/VAL |
| 误把设计目标写成实现 | 使用 implemented-source/validated/planned/unsupported |
| 命令适用于错误部署模式 | 每个代码块先标 Electron/source/legacy/release |
| 文档修复改变历史决策 | Accepted ADR 不改写；差异写入 status/TODO |
| 误触公开 Release | 本轮不创建 tag/Release，不调用 promotion |

回滚本轮只需 revert documentation commit；不涉及用户数据、GitHub settings、secret 或
runtime artifact。

## 当前变更清单

新增：

- `docs/17-system-design.md`
- `docs/18-deployment-operations.md`
- `docs/development/{status,contributor-handbook,todo}.md`
- `docs/development/evidence/README.md`
- `docs/development/iterations/0002-r11-documentation-handoff.md`
- `TODO.md`
- `.github/PULL_REQUEST_TEMPLATE.md`

同步：

- root/index/contributor/component documentation；
- active iteration、roadmap、traceability；
- legacy operations/backup/troubleshooting/GHCR warnings；
- Makefile user-facing help。

最终文件列表以本轮 commit diff 为准。
