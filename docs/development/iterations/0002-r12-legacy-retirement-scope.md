# ITER-0002/R12：Electron-only 与 legacy retirement 范围冻结

- 状态：`in-progress`（继承 ITER-0002）
- 日期：2026-07-31
- 类型：治理、架构决策与后续实施计划；不删除产品代码
- 关联需求：REQ-ELECTRON-ONLY-001、REQ-PRE1-BREAKING-001、REQ-GOV-001
- 关联验证：VAL-LEGACY-SCOPE-001、VAL-GOV-001

## 背景

用户确认项目仍处于早期研发阶段；Electron 达到功能替代门槛后，可以进行大范围不兼容
收敛，不再维持 Docker/Compose、browser Web、公开 TCP API、legacy HTTP MCP、Host Runner、
container image/GHCR 或旧数据导入兼容。旧计划要求先做 migration/rollback rehearsal，与此
决定冲突，必须用新 ADR 和新 iteration 取代，不能只改一条 TODO。

## 本轮固定范围

包含：

- 新增 ADR-0015，并在 ADR 索引和被部分取代 ADR 的 metadata banner 标记精确后续关系；不改写
  既有决策正文；
- 建立逐路径 `remove` / `retain` / `split` 清单和 Electron 能力替代表；
- 新建 ITER-0007 和稳定 TODO/REQ/VAL；
- 把旧 migration/control/exit 任务保留为 `superseded` tombstone；
- 同步 roadmap、status、traceability、system design、README 和开发入口。

不包含：

- 删除或重构 runtime、源码、脚本、workflow、Dockerfile 或测试；
- 改写 ADR-0001–0014 的历史正文；
- 宣称 Electron packaged/physical gate 已通过；
- 创建 tag、Draft、Release、DMG、container image 或公开发布；
- 删除、转换或自动发现任何用户 data、Docker volume、imports、backup 或 Application Support。

### 本 PR 的 exact repository write scope

只允许修改以下治理/说明表面；这不是未来 removal 的文件授权：

- root governance：`AGENTS.md`、`README.md`、`TODO.md`、`CONTRIBUTING.md`、`SECURITY.md`、
  `.github/PULL_REQUEST_TEMPLATE.md`；
- project skill metadata：`.agents/skills/lcf-desktop-development/{SKILL.md,references/architecture.md,references/testing.md}`；
- component/tool guidance：`backend/README.md`、`mcp/README.md`、`web/README.md`、`tools/README.md`；
- current numbered/index docs：`docs/README.md`、`docs/{00,01,03,04,05,06,07,08,09,10,11,12,14,15,16,17,18}-*.md`；
- ADR metadata/index and new decision：`docs/adr/{README,0001-*,0004-*,0005-*,0006-*,0012-*,0015-*}.md`；
- development governance：`docs/development/{README,status,roadmap,todo,traceability,legacy-retirement,contributor-handbook,desktop-release}.md`、
  `docs/development/iterations/{README,0002-bundled-runtimes,0002-r12-legacy-retirement-scope,0003-runtime-data-models,0006-legacy-exit,0007-electron-only-retirement}.md`。
- commit-bound validation：`docs/development/evidence/VAL-LEGACY-SCOPE-001/**`。

明确禁止本 PR 修改或删除：`desktop/**`、`backend/app/**`、`web/src/**`、`mcp/**`、
`host_runner/**`、`docker/**`、`scripts/**`、`runtime/**`、`guide-site/**`、Makefile、任何 product/
release workflow、dependency/lock、generated artifact 或用户/远端资产。`guide-site` 因缺失可验证
Sites identity 只记录为后续阻塞任务，不在未知 lifecycle checkout 中编辑或发布。

未来实现 PR 必须重新声明自己的 exact changed paths，并逐项引用
[strict manifest](../legacy-retirement.md)；本节不会把 planned removal 自动授权给当前 PR。

## 任务

- [x] **R12-01 冲突识别**：确认 ADR-0004、旧 ITER-0006、TODO 与当前决策冲突。
- [x] **R12-02 边界盘点**：证明 `web/src/**` 和 `backend/app/**` 存在 Electron 复用，禁止按
  顶层目录粗暴删除。
- [x] **R12-03 决策落盘**：接受 ADR-0015，并更新 ADR 索引。
- [x] **R12-04 实施计划**：新增严格 retirement 清单、ITER-0007 与分阶段 TODO。
- [x] **R12-05 全局同步**：更新 roadmap、status、traceability、system design 和入口文档。
- [ ] **R12-06 文档验证**：相对链接、稳定 ID、task roll-up 与 legacy 冲突审计通过。

## 验收

- 每个 legacy surface 都能找到 owner、替代能力、删除门槛与目标 disposition；
- `web/`、`backend/` 等共享目录没有被误列为整目录删除；
- “不兼容”明确不等于“允许自动删除用户数据”；
- 旧任务/验证保持可追溯且不伪造完成；
- `VAL-LEGACY-SCOPE-001` 与 `VAL-GOV-001` 有 commit-bound evidence 后，本 R12 才可完成。
