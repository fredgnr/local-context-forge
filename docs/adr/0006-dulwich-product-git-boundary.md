# ADR-0006：产品运行时以 Dulwich 取代系统 Git

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-PY-001、REQ-INSTALL-001、REQ-TRUST-001

> **后续关系：** 本 ADR 仍为 Accepted；legacy shell/Docker 产品运行时可依赖系统 Git 的例外
> 已由 [ADR-0015](0015-electron-only-legacy-retirement.md#对既有-adr-的影响)部分取代。Packaged
> 产品禁用系统 Git 与测试 fixture 例外继续有效。

## 上下文

源码 snapshot 和生成 Wiki 当前通过 `git` subprocess 工作。all-in-one 目标不允许依赖
目标机 Git；同时仓库、`.git/config`、include、hooks、attributes、credential helper、
alternate object store、linked worktree 和远端 redirect 都是不可信输入。简单改用
Dulwich porcelain 默认值仍可能读取宿主配置或改变既有安全语义。

## 决策

1. 产品 Python sidecar 固定使用受审计的 Dulwich 版本完成本地/远端 snapshot、ref 解析、
   tree 导出及 Wiki repository 的 init/status/stage/commit/reset/rollback。产品路径不得
   启动 `git` executable；测试可使用系统 Git 创建互操作 fixture。
2. 打开本地 repository 前先做纯路径验证：必须是顶层、standalone `.git` 目录，拒绝
   gitfile、linked worktree、`commondir`、alternate objects、symlink config 和逃逸路径。
3. 不使用宿主 global/system/XDG Git config，不展开不可信 include，不运行 hooks、filters、
   credential helper、fsmonitor、外部 attributes 或签名程序。
4. ref 解析保留既有语义：拒绝危险 ref；显式检查原名、tag、head 和 `origin/*`；annotated
   tag peel 到 commit；不同候选落到不同 commit 时拒绝 ambiguous。
5. tree 导出按 mode 预检，拒绝 gitlink/submodule、special entry、portable path collision、
   超限和 Git LFS pointer；symlink 只按已有安全规则物化。snapshot 仍以 commit SHA 标识，
   不包含未提交 worktree。
6. 远端只允许既有 HTTPS allowlist/443 规则，禁止 userinfo、redirect、proxy credential
   泄漏和交互认证；设置连接/读取/整体截止时间并验证所需 object 全部到位。
7. Wiki commit 固定 identity、`main`、无签名/无 hook；发布、SQLite 失败回滚、dirty 检查、
   lint 语义和 C Git 可读性保持兼容。
8. legacy shell、Docker 构建和测试 fixture 可以继续使用 Git；“无系统 Git”门禁只针对
   packaged 产品进程及其子进程。

## 后果

- 打包 sidecar 不再需要携带或发现 Git；
- Git 安全行为从命令行环境隔离转为显式 library policy，代码和测试规模增加；
- remote clone 的 redirect、timeout 和 object completeness 必须自行维护；
- C Git 互操作测试仍重要，但不是产品依赖。

## 替代方案

1. **在 DMG 内打包 Git。** 拒绝：体积、许可证、子程序和配置面显著扩大。
2. **继续发现 `/usr/bin/git`。** 拒绝：违反 all-in-one 与可复现门禁。
3. **直接调用 Dulwich porcelain 默认配置。** 拒绝：可能继承宿主/仓库配置。
4. **Wiki 不保留 Git 历史。** 拒绝：破坏审核、回滚和证据链。

## 验证门禁

- VAL-GIT-001：原有 source/Wiki/rollback/lifecycle 回归与新增恶意 config、redirect、
  object 缺失、tag/ref、submodule/LFS、collision 和 remote timeout 测试通过。
- fixture 创建后清空 `PATH`，并令任何产品 subprocess 立即失败；完整 ingest、publish、
  lint、rollback 仍通过。
- 使用 C Git 对 Dulwich 生成的 Wiki 执行只读 `fsck/log/rev-list` 互操作验证；该命令只在
  测试阶段运行。
